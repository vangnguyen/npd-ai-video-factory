from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import fakeredis
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from npd_agent_hub.attribution import AttributionService
from npd_agent_hub.attribution_models import (
    IdentitySource,
    SourceTouchpointEvent,
    TouchpointType,
)
from npd_agent_hub.auth import authorizer
from npd_agent_hub.config import HubSettings
from npd_agent_hub.dashboard import DASHBOARD_HTML
from npd_agent_hub.delivery_models import (
    AttributionDeliveryEnvelope,
    AttributionProducerHeartbeat,
    DeliveryFreshnessEvidence,
    DeliveryFreshnessState,
)
from npd_agent_hub.delivery_observability import (
    AttributionDeliveryService,
    DeliveryIntegrityConflict,
)
from npd_agent_hub.main import app
from npd_agent_hub.orchestrator import hub
from npd_agent_hub.provider_health import ProviderHealthService
from npd_agent_hub.provider_health_models import (
    ProviderAlertStatus,
    ProviderHealthSchedulerState,
)
from npd_agent_hub.provider_health_scheduler import ProviderHealthScheduler
from npd_agent_hub.store import MemoryHubStore, RedisHubStore
from npd_agent_hub.tool_registry import TOOL_REGISTRY


UTC = timezone.utc
SIGNING_KEY = "phase-8-8-heartbeat-signing-key-000000000000000000"
CONFIGURED = {
    "crm": "configured",
    "meta_ads": "configured",
    "ga4": "configured",
    "social": "configured",
}
AVAILABLE = {
    "crm": "available",
    "meta_ads": "available",
    "ga4": "available",
    "social": "available",
}


def settings(*, scheduler_enabled: bool = False) -> HubSettings:
    return HubSettings(
        attribution_receipt_signing_key=SIGNING_KEY,
        attribution_receipt_key_id="phase-8-8-heartbeat-v1",
        attribution_freshness_slos_json='{"n8n_lead_intake":15}',
        provider_health_scheduler_enabled=scheduler_enabled,
        provider_health_scheduler_interval_seconds=300,
    )


def services(store, *, now, scheduler_enabled: bool = False):
    attribution = AttributionService(store)
    delivery = AttributionDeliveryService(
        store, attribution, settings(scheduler_enabled=scheduler_enabled), clock=now
    )
    provider_health = ProviderHealthService(store, delivery, clock=now)
    scheduler = ProviderHealthScheduler(
        store,
        provider_health,
        settings(scheduler_enabled=scheduler_enabled),
        clock=now,
        worker_id="phase-8-8-test-worker",
    )
    return delivery, provider_health, scheduler


def delivery_envelope(now: datetime) -> AttributionDeliveryEnvelope:
    return AttributionDeliveryEnvelope(
        delivery_id="lead-intake:phase-8-8-001",
        producer="n8n_lead_intake",
        source_system=IdentitySource.META_ADS,
        sent_at=now,
        events=[
            SourceTouchpointEvent(
                source_event_id="meta-lead-phase-8-8-001",
                source_system=IdentitySource.META_ADS,
                event_type=TouchpointType.LEAD_CREATED,
                occurred_at=now,
                channel="paid_social",
                source_campaign_id="source-campaign-phase-8-8",
                lead_id="lead-ref-phase-8-8",
            )
        ],
    )


def heartbeat(now: datetime, *, sequence: int = 1787400000000):
    return AttributionProducerHeartbeat(
        heartbeat_id=f"heartbeat:n8n-lead-intake:{sequence}",
        producer="n8n_lead_intake",
        emitted_at=now,
        sequence=sequence,
        metadata={"workflow": "lead_intake", "environment": "production"},
    )


def test_heartbeat_is_signed_idempotent_and_rejects_changed_or_pii_payload():
    now = datetime(2026, 8, 22, 14, 0, tzinfo=UTC)
    store = MemoryHubStore()
    delivery, _, _ = services(store, now=lambda: now)
    request = heartbeat(now)

    receipt = delivery.ingest_heartbeat(request, actor="n8n_lead_intake")
    assert receipt == delivery.ingest_heartbeat(request, actor="n8n_lead_intake")
    assert receipt.external_writes_enabled is False
    assert delivery.verify_heartbeat(receipt).valid is True

    with pytest.raises(DeliveryIntegrityConflict):
        delivery.ingest_heartbeat(
            request.model_copy(update={"emitted_at": now + timedelta(seconds=1)}),
            actor="n8n_lead_intake",
        )
    with pytest.raises(ValidationError, match="raw PII"):
        AttributionProducerHeartbeat(
            heartbeat_id="heartbeat:n8n-lead-intake:1787400000001",
            producer="n8n_lead_intake",
            emitted_at=now,
            sequence=1787400000001,
            metadata={"phoneNumber": "0900000000"},
        )
    with pytest.raises(ValidationError, match="timezone"):
        AttributionProducerHeartbeat.model_validate(
            {
                **heartbeat(now).model_dump(),
                "emitted_at": now.replace(tzinfo=None),
            }
        )
    with pytest.raises(ValidationError, match="2048 bytes"):
        AttributionProducerHeartbeat(
            heartbeat_id="heartbeat:n8n-lead-intake:1787400000002",
            producer="n8n_lead_intake",
            emitted_at=now,
            sequence=1787400000002,
            metadata={"note": "x" * 2100},
        )


def test_heartbeat_sequence_and_replay_window_are_bounded():
    now = datetime(2026, 8, 22, 14, 0, tzinfo=UTC)
    store = MemoryHubStore()
    delivery, _, _ = services(store, now=lambda: now)
    delivery.ingest_heartbeat(heartbeat(now, sequence=20), actor="n8n_lead_intake")
    with pytest.raises(ValueError, match="sequence must increase"):
        delivery.ingest_heartbeat(
            heartbeat(now, sequence=19), actor="n8n_lead_intake"
        )
    with pytest.raises(ValueError, match="replay window"):
        delivery.ingest_heartbeat(
            heartbeat(now - timedelta(hours=25), sequence=21),
            actor="n8n_lead_intake",
        )


def test_freshness_prefers_heartbeat_and_keeps_lead_activity_separate():
    now = [datetime(2026, 8, 22, 14, 0, tzinfo=UTC)]
    store = MemoryHubStore()
    delivery, provider_health, _ = services(store, now=lambda: now[0])
    delivery.ingest(delivery_envelope(now[0]), actor="n8n_lead_intake")
    provider_health.refresh(
        configuration=CONFIGURED, probes=AVAILABLE, actor="operator@example.com"
    )
    now[0] += timedelta(minutes=60)

    fallback = delivery.status().sources[0]
    assert fallback.state == DeliveryFreshnessState.STALE
    assert fallback.evidence == DeliveryFreshnessEvidence.DELIVERY_FALLBACK
    provider_health.evaluate_cached(actor="provider_health_scheduler")
    stale = provider_health.status()
    stale_alert = next(
        item for item in stale.alerts if item.alert_type == "freshness_stale"
    )

    receipt = delivery.ingest_heartbeat(
        heartbeat(now[0], sequence=1787403600000), actor="n8n_lead_intake"
    )
    provider_health.evaluate_cached(actor="provider_health_scheduler")
    current = delivery.status().sources[0]
    assert current.state == DeliveryFreshnessState.FRESH
    assert current.evidence == DeliveryFreshnessEvidence.HEARTBEAT
    assert current.heartbeat_age_minutes == 0
    assert current.activity_age_minutes == 60
    assert current.last_receipt_id == receipt.receipt_id
    assert all(item.alert_type != "freshness_stale" for item in provider_health.status().alerts)
    resolved = provider_health.list_alerts(status=ProviderAlertStatus.RESOLVED)
    assert any(item.alert_id == stale_alert.alert_id for item in resolved)


def test_scheduler_uses_cached_state_lease_and_persists_in_redis():
    now = [datetime(2026, 8, 22, 14, 0, tzinfo=UTC)]
    client = fakeredis.FakeRedis(decode_responses=True)
    store = RedisHubStore(client=client, namespace="test:agent-hub")
    delivery, provider_health, scheduler = services(
        store, now=lambda: now[0], scheduler_enabled=True
    )
    provider_health.refresh(
        configuration=CONFIGURED, probes=AVAILABLE, actor="operator@example.com"
    )
    delivery.ingest_heartbeat(heartbeat(now[0]), actor="n8n_lead_intake")

    completed = asyncio.run(scheduler.run_once())
    assert completed.state == ProviderHealthSchedulerState.SUCCEEDED
    assert completed.run_count == 1
    assert completed.external_provider_probes_enabled is False
    assert completed.external_notifications_enabled is False
    assert completed.production_write_enabled is False

    restarted_store = RedisHubStore(client=client, namespace="test:agent-hub")
    _, restarted_health, restarted = services(
        restarted_store, now=lambda: now[0], scheduler_enabled=True
    )
    assert restarted.status().run_count == 1
    assert restarted_health.status().latest_snapshot is not None
    assert restarted_store.acquire_provider_health_scheduler_lease(
        "another-worker", 300
    )
    skipped = asyncio.run(restarted.run_once())
    assert skipped.skipped_lease_count == 1
    keys = {str(key) for key in client.scan_iter("*")}
    assert any("heartbeat-receipt:" in key for key in keys)
    assert any("provider-health:scheduler:status" in key for key in keys)
    assert not any("npd:video-jobs" in key for key in keys)


def test_api_rbac_heartbeat_immediately_evaluates_cached_health():
    now = datetime(2026, 8, 22, 14, 0, tzinfo=UTC)
    old_settings = authorizer.settings
    old_store = hub.store
    old_delivery = hub.delivery
    old_provider_health = hub.provider_health
    old_scheduler = hub.provider_health_scheduler
    authorizer.settings = HubSettings(
        auth_mode="static_token",
        viewer_token="viewer-secret",
        operator_token="operator-secret",
        owner_token="owner-secret",
    )
    store = MemoryHubStore()
    delivery, provider_health, scheduler = services(store, now=lambda: now)
    provider_health.refresh(
        configuration=CONFIGURED, probes=AVAILABLE, actor="operator@example.com"
    )
    hub.store = store
    hub.delivery = delivery
    hub.provider_health = provider_health
    hub.provider_health_scheduler = scheduler
    viewer = {"Authorization": "Bearer viewer-secret"}
    operator = {"Authorization": "Bearer operator-secret"}
    client = TestClient(app)
    try:
        body = heartbeat(now).model_dump(mode="json")
        assert (
            client.post(
                "/api/v1/attribution/deliveries/heartbeats",
                headers=viewer,
                json=body,
            ).status_code
            == 403
        )
        created = client.post(
            "/api/v1/attribution/deliveries/heartbeats",
            headers=operator,
            json=body,
        )
        assert created.status_code == 200
        receipt = created.json()
        assert receipt["external_writes_enabled"] is False
        listed = client.get(
            "/api/v1/attribution/deliveries/heartbeats", headers=viewer
        )
        assert listed.status_code == 200
        assert listed.json()[0]["receipt_id"] == receipt["receipt_id"]
        verify = client.post(
            "/api/v1/attribution/deliveries/heartbeats/verify",
            headers=viewer,
            json={"receipt": receipt},
        )
        assert verify.status_code == 200
        assert verify.json()["valid"] is True
        schedule = client.get("/api/v1/provider-health/scheduler", headers=viewer)
        assert schedule.status_code == 200
        assert schedule.json()["external_notifications_enabled"] is False
        assert (
            client.post("/api/v1/provider-health/evaluate", headers=viewer).status_code
            == 403
        )
        assert (
            client.post(
                "/api/v1/provider-health/evaluate", headers=operator
            ).status_code
            == 200
        )
    finally:
        authorizer.settings = old_settings
        hub.store = old_store
        hub.delivery = old_delivery
        hub.provider_health = old_provider_health
        hub.provider_health_scheduler = old_scheduler


def test_dashboard_and_tool_policy_expose_internal_only_phase_8_8():
    assert "Heartbeat receipts" in DASHBOARD_HTML
    assert "/api/v1/attribution/deliveries/heartbeats" in DASHBOARD_HTML
    assert "/api/v1/provider-health/scheduler" in DASHBOARD_HTML
    assert "Cached-only" in DASHBOARD_HTML
    assert TOOL_REGISTRY["attribution.heartbeat.read"].mode.value == "read"
    assert (
        TOOL_REGISTRY["attribution.heartbeat.ingest"].execution_state.value
        == "planning_only"
    )
    assert (
        TOOL_REGISTRY["provider.health.evaluate"].execution_state.value
        == "planning_only"
    )
    assert TOOL_REGISTRY["ads.launch"].execution_state.value == "disabled"


def test_n8n_heartbeat_workflow_is_inactive_pii_free_and_internal_only():
    repo = Path(__file__).resolve().parents[3]
    payload = json.loads(
        (repo / "workflows/n8n/phase-8-8-lead-intake-heartbeat.json").read_text(
            encoding="utf-8"
        )
    )
    assert str(uuid.UUID(payload["id"])) == payload["id"]
    assert payload["active"] is False
    assert len(payload["nodes"]) == 3
    schedule = next(node for node in payload["nodes"] if node["type"].endswith("scheduleTrigger"))
    acceptance = next(
        node
        for node in payload["nodes"]
        if node["type"].endswith("executeWorkflowTrigger")
    )
    request = next(node for node in payload["nodes"] if node["type"].endswith("code"))
    assert schedule["parameters"]["rule"]["interval"][0]["minutesInterval"] == 5
    assert acceptance["name"] == "Internal acceptance trigger"
    assert payload["connections"][acceptance["name"]]["main"][0][0]["node"] == request["name"]
    code = request["parameters"]["jsCode"]
    assert "NPD_AGENT_HUB_ATTRIBUTION_URL" in code
    assert "NPD_AGENT_HUB_ATTRIBUTION_TOKEN" in code
    assert "/api/v1/attribution/deliveries/heartbeats" in code
    assert "this.helpers.httpRequest" in code
    raw = json.dumps(payload, ensure_ascii=False).lower()
    assert "bearer ${token}" in raw
    assert "customer" not in raw
    assert "phone" not in raw
    assert "email" not in raw
    assert "zalo" not in raw
    assert payload["meta"]["production_write"] is False
    assert payload["meta"]["external_notifications"] is False
