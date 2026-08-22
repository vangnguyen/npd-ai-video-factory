from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

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
    AttributionDeliveryFailure,
    DeliveryFailureCode,
)
from npd_agent_hub.delivery_observability import AttributionDeliveryService
from npd_agent_hub.main import app
from npd_agent_hub.orchestrator import hub
from npd_agent_hub.provider_health import ProviderHealthService
from npd_agent_hub.provider_health_models import (
    ProviderAlertStatus,
    ProviderHealthAlert,
)
from npd_agent_hub.store import MemoryHubStore, RedisHubStore
from npd_agent_hub.tool_registry import TOOL_REGISTRY
from npd_agent_hub.tools import ToolExecutor


UTC = timezone.utc
SIGNING_KEY = "phase-8-7-test-signing-key-00000000000000000000"


def settings() -> HubSettings:
    return HubSettings(
        attribution_receipt_signing_key=SIGNING_KEY,
        attribution_receipt_key_id="test-provider-health-v1",
        attribution_freshness_slos_json='{"n8n_lead_intake":15}',
    )


def services(store, *, clock):
    attribution = AttributionService(store)
    delivery = AttributionDeliveryService(
        store, attribution, settings(), clock=clock
    )
    provider_health = ProviderHealthService(store, delivery, clock=clock)
    return attribution, delivery, provider_health


def envelope(now: datetime) -> AttributionDeliveryEnvelope:
    return AttributionDeliveryEnvelope(
        delivery_id="lead-intake:provider-health-871",
        producer="n8n_lead_intake",
        source_system=IdentitySource.META_ADS,
        attempt_number=1,
        max_attempts=4,
        sent_at=now,
        events=[
            SourceTouchpointEvent(
                source_event_id="meta-lead-provider-health-871",
                source_system=IdentitySource.META_ADS,
                event_type=TouchpointType.LEAD_CREATED,
                occurred_at=now,
                channel="paid_social",
                source_campaign_id="source-campaign-871",
                lead_id="lead-ref-871",
            )
        ],
    )


CONFIGURED = {"crm": "configured", "meta_ads": "configured", "ga4": "configured", "social": "configured"}
AVAILABLE = {"crm": "available", "meta_ads": "available", "ga4": "available", "social": "available"}


def test_read_only_refresh_creates_deduplicated_no_data_alert_then_resolves():
    now = [datetime(2026, 8, 22, 12, 0, tzinfo=UTC)]
    store = MemoryHubStore()
    _, delivery, provider_health = services(store, clock=lambda: now[0])

    first = provider_health.refresh(
        configuration=CONFIGURED, probes=AVAILABLE, actor="operator@example.com"
    )
    assert first.latest_snapshot is not None
    assert first.latest_snapshot.healthy == 4
    assert first.latest_snapshot.no_data == 1
    assert first.open_alerts == 1
    alert = first.alerts[0]
    assert alert.provider == "n8n_lead_intake"
    assert alert.alert_type == "no_data"
    assert alert.external_notifications_enabled is False

    repeated = provider_health.refresh(
        configuration=CONFIGURED, probes=AVAILABLE, actor="operator@example.com"
    )
    assert repeated.open_alerts == 1
    assert repeated.alerts[0].alert_id == alert.alert_id
    assert repeated.alerts[0].occurrence_count == 1

    acknowledged = provider_health.acknowledge(
        alert.alert_id, actor="operator@example.com"
    )
    assert acknowledged.status == ProviderAlertStatus.ACKNOWLEDGED
    assert provider_health.status().acknowledged_alerts == 1

    delivery.ingest(envelope(now[0]), actor="n8n_lead_intake")
    healthy = provider_health.refresh(
        configuration=CONFIGURED, probes=AVAILABLE, actor="operator@example.com"
    )
    assert healthy.open_alerts == 0
    assert healthy.acknowledged_alerts == 0
    resolved = provider_health.list_alerts(status=ProviderAlertStatus.RESOLVED)
    assert resolved[0].alert_id == alert.alert_id
    assert resolved[0].resolved_at == now[0]


def test_failed_and_stale_conditions_are_critical_and_reopen_after_resolution():
    now = [datetime(2026, 8, 22, 12, 0, tzinfo=UTC)]
    store = MemoryHubStore()
    _, delivery, provider_health = services(store, clock=lambda: now[0])
    delivery.ingest(envelope(now[0]), actor="n8n_lead_intake")
    now[0] += timedelta(minutes=16)

    status = provider_health.refresh(
        configuration=CONFIGURED,
        probes={**AVAILABLE, "meta_ads": "failed"},
        actor="operator@example.com",
    )
    assert status.critical_alerts == 2
    assert {item.alert_type for item in status.alerts} == {
        "probe_failed",
        "freshness_stale",
    }

    delivery.ingest(
        envelope(now[0]).model_copy(
            update={"delivery_id": "lead-intake:provider-health-872"}
        ),
        actor="n8n_lead_intake",
    )
    provider_health.refresh(
        configuration=CONFIGURED, probes=AVAILABLE, actor="operator@example.com"
    )
    assert provider_health.status().critical_alerts == 0

    reopened = provider_health.refresh(
        configuration=CONFIGURED,
        probes={**AVAILABLE, "meta_ads": "failed"},
        actor="operator@example.com",
    )
    meta_alert = next(item for item in reopened.alerts if item.provider == "meta_ads")
    assert meta_alert.status == ProviderAlertStatus.OPEN
    assert meta_alert.occurrence_count == 2


def test_retry_alert_tracks_only_latest_attempt_for_each_delivery():
    now = [datetime(2026, 8, 22, 12, 0, tzinfo=UTC)]
    store = MemoryHubStore()
    _, delivery, provider_health = services(store, clock=lambda: now[0])
    failure = AttributionDeliveryFailure(
        delivery_id="lead-intake:provider-health-retry-871",
        producer="n8n_lead_intake",
        source_system=IdentitySource.META_ADS,
        attempt_number=1,
        max_attempts=4,
        occurred_at=now[0],
        error_code=DeliveryFailureCode.NETWORK_TIMEOUT,
    )
    delivery.record_failure(failure, actor="n8n_lead_intake")

    pending = provider_health.refresh(
        configuration=CONFIGURED, probes=AVAILABLE, actor="operator@example.com"
    )
    retry_alert = next(
        item for item in pending.alerts if item.alert_type == "retry_pending"
    )
    assert retry_alert.status == ProviderAlertStatus.OPEN

    delivery.ingest(
        envelope(now[0]).model_copy(
            update={
                "delivery_id": failure.delivery_id,
                "attempt_number": 2,
            }
        ),
        actor="n8n_lead_intake",
    )
    recovered = provider_health.refresh(
        configuration=CONFIGURED, probes=AVAILABLE, actor="operator@example.com"
    )
    assert all(item.alert_type != "retry_pending" for item in recovered.alerts)
    resolved = provider_health.list_alerts(status=ProviderAlertStatus.RESOLVED)
    assert any(item.alert_id == retry_alert.alert_id for item in resolved)


def test_not_configured_is_visible_but_does_not_page_and_no_external_effects():
    now = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
    store = MemoryHubStore()
    _, _, provider_health = services(store, clock=lambda: now)
    status = provider_health.refresh(
        configuration={
            "crm": "configured",
            "meta_ads": "not_configured",
            "ga4": "not_configured",
            "social": "incomplete",
        },
        probes={"crm": "available", "social": "not_configured"},
        actor="operator@example.com",
    )
    snapshot = status.latest_snapshot
    assert snapshot is not None
    assert snapshot.not_configured == 2
    assert all(item.provider != "meta_ads" for item in status.alerts)
    assert all(item.provider != "ga4" for item in status.alerts)
    assert any(item.provider == "social" for item in status.alerts)
    assert snapshot.external_notifications_enabled is False
    assert snapshot.production_write_enabled is False
    audit = store.list_attribution_audit(limit=20)
    assert all(item.metadata["external_side_effect"] is False for item in audit)
    assert all(item.metadata["external_notification"] is False for item in audit)


def test_alert_contract_rejects_external_routing_or_notifications():
    now = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
    base = {
        "alert_id": "pha_" + "a" * 24,
        "dedupe_key": "provider_health:ga4:probe_failed",
        "provider": "ga4",
        "alert_type": "probe_failed",
        "severity": "critical",
        "detail": "Read-only probe failed.",
        "first_detected_at": now,
        "last_detected_at": now,
    }
    with pytest.raises(ValidationError, match="internal targets"):
        ProviderHealthAlert(**base, routing_targets=["email"])
    with pytest.raises(ValidationError, match="external effects"):
        ProviderHealthAlert(**base, external_notifications_enabled=True)


def test_fakeredis_recovers_snapshots_alerts_and_namespace():
    now = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
    client = fakeredis.FakeRedis(decode_responses=True)
    store = RedisHubStore(client=client, namespace="test:agent-hub")
    _, _, provider_health = services(store, clock=lambda: now)
    created = provider_health.refresh(
        configuration=CONFIGURED, probes=AVAILABLE, actor="operator@example.com"
    )

    restarted_store = RedisHubStore(client=client, namespace="test:agent-hub")
    _, _, restarted = services(restarted_store, clock=lambda: now)
    assert restarted.status().latest_snapshot == created.latest_snapshot
    assert restarted.status().alerts[0].alert_id == created.alerts[0].alert_id
    keys = {str(key) for key in client.scan_iter("*")}
    assert any("provider-health:snapshot:" in key for key in keys)
    assert any("provider-health:alert:" in key for key in keys)
    assert not any("npd:video-jobs" in key for key in keys)


def test_provider_health_api_rbac_refresh_and_acknowledge(monkeypatch):
    old_settings = authorizer.settings
    old_store = hub.store
    old_delivery = hub.delivery
    old_provider_health = hub.provider_health
    authorizer.settings = HubSettings(
        auth_mode="static_token",
        viewer_token="viewer-secret",
        operator_token="operator-secret",
        owner_token="owner-secret",
    )
    store = MemoryHubStore()
    _, delivery, provider_health = services(
        store, clock=lambda: datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
    )
    hub.store, hub.delivery, hub.provider_health = store, delivery, provider_health

    async def probe():
        return {"configuration": CONFIGURED, "probes": AVAILABLE}

    monkeypatch.setattr(hub.executor, "probe_provider_health", probe)
    client = TestClient(app)
    viewer = {"Authorization": "Bearer viewer-secret"}
    operator = {"Authorization": "Bearer operator-secret"}
    try:
        assert client.post("/api/v1/provider-health/refresh", headers=viewer).status_code == 403
        refreshed = client.post("/api/v1/provider-health/refresh", headers=operator)
        assert refreshed.status_code == 200
        assert refreshed.json()["external_notifications_enabled"] is False
        status = client.get("/api/v1/provider-health/status", headers=viewer)
        assert status.status_code == 200
        alert_id = status.json()["alerts"][0]["alert_id"]
        url = f"/api/v1/provider-health/alerts/{alert_id}/acknowledge"
        body = {"expected_status": "open"}
        assert client.post(url, headers=viewer, json=body).status_code == 403
        acknowledged = client.post(url, headers=operator, json=body)
        assert acknowledged.status_code == 200
        assert acknowledged.json()["status"] == "acknowledged"
        assert client.post(url, headers=operator, json=body).status_code == 409
    finally:
        authorizer.settings = old_settings
        hub.store, hub.delivery, hub.provider_health = (
            old_store,
            old_delivery,
            old_provider_health,
        )


def test_dashboard_and_tool_registry_keep_alert_routing_internal_only():
    assert "Provider Health & Internal Alerts" in DASHBOARD_HTML
    assert "/api/v1/provider-health/status" in DASHBOARD_HTML
    assert "/api/v1/provider-health/refresh" in DASHBOARD_HTML
    assert "External notifications: disabled" in DASHBOARD_HTML
    assert TOOL_REGISTRY["provider.health.read"].mode.value == "read"
    assert TOOL_REGISTRY["provider.health.refresh"].mode.value == "read"
    acknowledge = TOOL_REGISTRY["provider.alert.acknowledge"]
    assert acknowledge.mode.value == "draft"
    assert acknowledge.execution_state.value == "planning_only"
    assert TOOL_REGISTRY["ads.launch"].execution_state.value == "disabled"


def test_unconfigured_provider_probe_is_explicit_and_makes_no_network_request():
    result = asyncio.run(ToolExecutor(HubSettings()).probe_provider_health())
    assert result["configuration"] == {
        "crm": "not_configured",
        "meta_ads": "not_configured",
        "ga4": "not_configured",
        "social": "not_configured",
    }
    assert result["probes"] == {
        "crm": "not_configured",
        "meta_ads": "not_configured",
        "ga4": "not_configured",
        "social": "not_configured",
    }
