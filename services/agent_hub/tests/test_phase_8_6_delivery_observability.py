from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import fakeredis
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from npd_agent_hub.attribution import AttributionService
from npd_agent_hub.attribution_models import (
    CampaignIdentityMappingCreate,
    IdentitySource,
    SourceTouchpointEvent,
    TouchpointType,
)
from npd_agent_hub.auth import authorizer
from npd_agent_hub.campaign_models import CampaignBudget, CampaignCreate, KPITarget
from npd_agent_hub.campaigns import CampaignService
from npd_agent_hub.config import HubSettings
from npd_agent_hub.dashboard import DASHBOARD_HTML
from npd_agent_hub.delivery_models import (
    AttributionDeliveryEnvelope,
    AttributionDeliveryFailure,
    AttributionDeliveryReceipt,
    AttributionReceiptVerificationRequest,
    DeliveryFailureCode,
)
from npd_agent_hub.delivery_observability import (
    AttributionDeliveryService,
    DeliveryIntegrityConflict,
    DeliveryNotConfigured,
)
from npd_agent_hub.main import app
from npd_agent_hub.orchestrator import hub
from npd_agent_hub.store import MemoryHubStore, RedisHubStore
from npd_agent_hub.tool_registry import TOOL_REGISTRY


UTC = timezone.utc
SIGNING_KEY = "phase-8-6-test-signing-key-00000000000000000000"


def settings(**overrides: object) -> HubSettings:
    values = {
        "attribution_receipt_signing_key": SIGNING_KEY,
        "attribution_receipt_key_id": "test-attribution-v1",
        "attribution_delivery_max_attempts": 4,
        "attribution_freshness_slos_json": '{"n8n_lead_intake":15,"ga4":1440}',
    }
    values.update(overrides)
    return HubSettings(**values)


def create_campaign(campaigns: CampaignService):
    return campaigns.create(
        CampaignCreate(
            name="Phase 8.6 delivery acceptance",
            project="Vịnh Tiên",
            project_code="VGP",
            objective="Observe read-only attribution delivery health",
            audience=["Pseudonymous delivery events"],
            budget=CampaignBudget(amount=0),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
            kpi_targets=[
                KPITarget(name="Lead", target=1, unit="lead", funnel_stage="lead")
            ],
            owner="owner@example.com",
        ),
        actor="operator@example.com",
    )


def event(event_id: str = "meta-lead-861") -> SourceTouchpointEvent:
    return SourceTouchpointEvent(
        source_event_id=event_id,
        source_system=IdentitySource.META_ADS,
        event_type=TouchpointType.LEAD_CREATED,
        occurred_at=datetime(2026, 8, 22, 9, 0, tzinfo=UTC),
        channel="paid_social",
        source_account_id="act-001",
        source_campaign_id="1200861",
        source_ad_id="1200861001",
        lead_id=f"lead-ref-{event_id}",
        metadata={"source_page_id": "page-001", "source_form_id": "form-001"},
    )


def envelope(
    *,
    delivery_id: str = "lead-intake:delivery-861",
    attempt: int = 1,
    events: list[SourceTouchpointEvent] | None = None,
) -> AttributionDeliveryEnvelope:
    return AttributionDeliveryEnvelope(
        delivery_id=delivery_id,
        producer="n8n_lead_intake",
        source_system=IdentitySource.META_ADS,
        attempt_number=attempt,
        max_attempts=4,
        sent_at=datetime(2026, 8, 22, 9, 0, tzinfo=UTC),
        events=events or [event()],
        metadata={"workflow_id": "lead-intake-v1"},
    )


def register_mapping(service: AttributionService, campaign_id: str) -> None:
    service.register_identity_mapping(
        CampaignIdentityMappingCreate(
            source_system=IdentitySource.META_ADS,
            source_account_id="act-001",
            source_campaign_id="1200861",
            source_ad_id="1200861001",
            campaign_id=campaign_id,
            note="Owner verified delivery acceptance IDs.",
        ),
        actor="owner@example.com",
    )


def services(store: MemoryHubStore | RedisHubStore, clock=None):
    campaigns = CampaignService(store)
    campaign = create_campaign(campaigns)
    attribution = AttributionService(store)
    register_mapping(attribution, campaign.campaign_id)
    delivery = AttributionDeliveryService(
        store, attribution, settings(), clock=clock
    )
    return campaigns, campaign, attribution, delivery


def test_signed_receipt_is_valid_idempotent_and_tamper_evident():
    store = MemoryHubStore()
    _, campaign, attribution, delivery = services(store)

    receipt = delivery.ingest(envelope(), actor="n8n-lead-intake")
    repeated = delivery.ingest(envelope(), actor="n8n-lead-intake")

    assert receipt == repeated
    assert receipt.outcome.value == "accepted"
    assert receipt.inserted == 1
    assert receipt.external_writes_enabled is False
    assert receipt.signature.startswith("hmac-sha256:")
    assert delivery.verify(receipt).valid is True
    tampered = receipt.model_copy(update={"inserted": 99})
    assert delivery.verify(tampered).valid is False
    assert len(delivery.list_receipts()) == 1
    assert attribution.list_touchpoints()[0].campaign_id == campaign.campaign_id


def test_unknown_identity_is_partial_but_not_transport_retry():
    store = MemoryHubStore()
    attribution = AttributionService(store)
    delivery = AttributionDeliveryService(store, attribution, settings())

    receipt = delivery.ingest(envelope(), actor="n8n-lead-intake")

    assert receipt.outcome.value == "partial"
    assert receipt.unknown == 1
    assert receipt.retry_allowed is False
    assert receipt.dead_lettered is False
    assert len(attribution.list_intake_issues()) == 1
    assert delivery.verify(receipt).valid is True


def test_bounded_failure_retry_then_dead_letter():
    now = datetime(2026, 8, 22, 9, 0, tzinfo=UTC)
    store = MemoryHubStore()
    attribution = AttributionService(store)
    delivery = AttributionDeliveryService(store, attribution, settings(), clock=lambda: now)

    first = delivery.record_failure(
        AttributionDeliveryFailure(
            delivery_id="lead-intake:failure-861",
            producer="n8n_lead_intake",
            source_system=IdentitySource.META_ADS,
            attempt_number=1,
            max_attempts=3,
            occurred_at=now,
            error_code=DeliveryFailureCode.NETWORK_TIMEOUT,
        ),
        actor="n8n-lead-intake",
    )
    final = delivery.record_failure(
        AttributionDeliveryFailure(
            delivery_id="lead-intake:failure-861",
            producer="n8n_lead_intake",
            source_system=IdentitySource.META_ADS,
            attempt_number=3,
            max_attempts=3,
            occurred_at=now,
            error_code=DeliveryFailureCode.PROVIDER_5XX,
        ),
        actor="n8n-lead-intake",
    )

    assert first.outcome.value == "retry_pending"
    assert first.retry_allowed is True
    assert first.next_retry_at == now + timedelta(seconds=30)
    assert final.outcome.value == "dead_lettered"
    assert final.retry_allowed is False
    assert final.dead_lettered is True
    assert len(delivery.list_dead_letters()) == 1
    status = delivery.status()
    assert status.retry_pending == 1
    assert status.dead_lettered == 1
    assert status.dead_letter_count == 1


def test_changed_payload_for_same_attempt_is_dead_lettered_as_integrity_conflict():
    store = MemoryHubStore()
    _, _, attribution, delivery = services(store)
    delivery.ingest(envelope(), actor="n8n-lead-intake")
    changed = envelope(events=[event("meta-lead-changed")])

    with pytest.raises(DeliveryIntegrityConflict, match="different immutable payload"):
        delivery.ingest(changed, actor="n8n-lead-intake")

    assert len(attribution.list_touchpoints()) == 1
    dead = delivery.list_dead_letters()[0]
    assert dead.reason_code == DeliveryFailureCode.INTEGRITY_CONFLICT


def test_freshness_slo_moves_from_no_data_to_fresh_to_stale():
    clock_value = [datetime(2026, 8, 22, 9, 0, tzinfo=UTC)]
    store = MemoryHubStore()
    _, _, _, delivery = services(store, clock=lambda: clock_value[0])

    initial = delivery.status()
    n8n = next(item for item in initial.sources if item.producer == "n8n_lead_intake")
    ga4 = next(item for item in initial.sources if item.producer == "ga4")
    assert n8n.state.value == "no_data"
    assert ga4.state.value == "no_data"

    delivery.ingest(envelope(), actor="n8n-lead-intake")
    fresh = next(
        item for item in delivery.status().sources if item.producer == "n8n_lead_intake"
    )
    assert fresh.state.value == "fresh"
    clock_value[0] += timedelta(minutes=16)
    stale = next(
        item for item in delivery.status().sources if item.producer == "n8n_lead_intake"
    )
    assert stale.state.value == "stale"
    assert stale.age_minutes == 16


def test_delivery_contract_rejects_pii_write_flags_and_unbounded_retry():
    with pytest.raises(ValidationError, match="raw PII"):
        envelope().model_copy(
            update={"metadata": {"customer_email": "person@example.com"}}
        ).model_validate(
            {**envelope().model_dump(), "metadata": {"customer_email": "person@example.com"}}
        )
    with pytest.raises(ValidationError, match="cannot enable writes"):
        AttributionDeliveryEnvelope(
            **{**envelope().model_dump(), "metadata": {"publish_enabled": True}}
        )
    safe_receipt = services(MemoryHubStore())[3].ingest(
        envelope(), actor="operator"
    )
    with pytest.raises(ValidationError, match="raw contact data"):
        AttributionDeliveryReceipt.model_validate(
            {**safe_receipt.model_dump(), "delivery_id": "person@example.com"}
        )
    store = MemoryHubStore()
    attribution = AttributionService(store)
    delivery = AttributionDeliveryService(
        store,
        attribution,
        settings(attribution_delivery_max_attempts=3),
    )
    with pytest.raises(ValueError, match="configured maximum 3"):
        delivery.ingest(envelope(), actor="operator")


def test_redis_recovers_signed_receipts_dead_letters_and_namespace():
    client = fakeredis.FakeRedis(decode_responses=True)
    store = RedisHubStore(client=client, namespace="test:agent-hub")
    _, _, _, delivery = services(store)
    receipt = delivery.ingest(envelope(), actor="n8n-lead-intake")
    delivery.record_failure(
        AttributionDeliveryFailure(
            delivery_id="lead-intake:redis-dead",
            producer="n8n_lead_intake",
            source_system=IdentitySource.META_ADS,
            attempt_number=4,
            max_attempts=4,
            occurred_at=datetime.now(UTC),
            error_code=DeliveryFailureCode.PROVIDER_5XX,
        ),
        actor="n8n-lead-intake",
    )

    restarted_store = RedisHubStore(client=client, namespace="test:agent-hub")
    restarted = AttributionDeliveryService(
        restarted_store, AttributionService(restarted_store), settings()
    )
    assert restarted.list_receipts()[1].receipt_id == receipt.receipt_id
    assert len(restarted.list_dead_letters()) == 1
    assert restarted.verify(receipt).valid is True
    keys = {str(key) for key in client.scan_iter("*")}
    assert any("attribution-os:delivery-receipt:" in key for key in keys)
    assert any("attribution-os:dead-letter:" in key for key in keys)
    assert not any("npd:video-jobs" in key for key in keys)


def test_delivery_api_rbac_status_and_verification():
    old_settings = authorizer.settings
    old_store = hub.store
    old_campaigns = hub.campaigns
    old_attribution = hub.attribution
    old_delivery = hub.delivery
    authorizer.settings = HubSettings(
        auth_mode="static_token",
        viewer_token="viewer-secret",
        operator_token="operator-secret",
        owner_token="owner-secret",
    )
    store = MemoryHubStore()
    campaigns, _, attribution, delivery = services(store)
    hub.store, hub.campaigns, hub.attribution, hub.delivery = (
        store,
        campaigns,
        attribution,
        delivery,
    )
    client = TestClient(app)
    viewer = {"Authorization": "Bearer viewer-secret"}
    operator = {"Authorization": "Bearer operator-secret"}
    payload = envelope(delivery_id="lead-intake:api-861").model_dump(mode="json")
    try:
        url = "/api/v1/attribution/deliveries"
        assert client.post(url, headers=viewer, json=payload).status_code == 403
        response = client.post(url, headers=operator, json=payload)
        assert response.status_code == 200
        receipt = response.json()
        assert receipt["external_writes_enabled"] is False
        assert client.get(f"{url}/status", headers=viewer).status_code == 200
        assert len(client.get(f"{url}/receipts", headers=viewer).json()) == 1
        verified = client.post(
            f"{url}/receipts/verify",
            headers=viewer,
            json=AttributionReceiptVerificationRequest(
                receipt=receipt
            ).model_dump(mode="json"),
        )
        assert verified.status_code == 200
        assert verified.json()["valid"] is True
    finally:
        authorizer.settings = old_settings
        hub.store, hub.campaigns, hub.attribution, hub.delivery = (
            old_store,
            old_campaigns,
            old_attribution,
            old_delivery,
        )


def test_dashboard_and_tool_policy_expose_observability_without_execution():
    assert "Delivery receipts & freshness SLO" in DASHBOARD_HTML
    assert "/api/v1/attribution/deliveries/status" in DASHBOARD_HTML
    assert "/api/v1/attribution/deliveries/dead-letters" in DASHBOARD_HTML
    assert "External write: disabled" in DASHBOARD_HTML
    assert TOOL_REGISTRY["attribution.delivery.status.read"].mode.value == "read"
    assert TOOL_REGISTRY["attribution.delivery.receipt.verify"].mode.value == "read"
    ingest = TOOL_REGISTRY["attribution.delivery.ingest"]
    failure = TOOL_REGISTRY["attribution.delivery.failure.record"]
    assert ingest.mode.value == "draft"
    assert failure.mode.value == "draft"
    assert ingest.execution_state.value == "planning_only"
    assert failure.execution_state.value == "planning_only"
    assert TOOL_REGISTRY["ads.launch"].execution_state.value == "disabled"


def test_missing_signing_key_is_explicitly_not_configured_and_has_no_side_effect():
    store = MemoryHubStore()
    _, _, attribution, _ = services(store)
    delivery = AttributionDeliveryService(
        store,
        attribution,
        HubSettings(attribution_receipt_signing_key=""),
    )

    status = delivery.status()
    assert status.configured is False
    assert status.production_write_enabled is False
    with pytest.raises(DeliveryNotConfigured):
        delivery.ingest(envelope(), actor="operator@example.com")

    assert delivery.list_receipts() == []
    assert attribution.list_touchpoints(limit=10) == []


def test_delivery_actions_are_audited_without_external_side_effects():
    store = MemoryHubStore()
    _, _, _, delivery = services(store)
    receipt = delivery.ingest(envelope(), actor="operator@example.com")
    delivery.record_failure(
        AttributionDeliveryFailure(
            delivery_id="lead-intake:failure-audit",
            producer="n8n_lead_intake",
            source_system=IdentitySource.META_ADS,
            attempt_number=4,
            max_attempts=4,
            error_code=DeliveryFailureCode.PROVIDER_5XX,
            occurred_at=datetime(2026, 8, 22, 9, 5, tzinfo=UTC),
        ),
        actor="operator@example.com",
    )

    events = store.list_attribution_audit(limit=20)
    delivery_events = [
        item
        for item in events
        if item.event_type in {"signed_delivery_received", "delivery_failure_recorded"}
    ]
    assert receipt.external_writes_enabled is False
    assert {item.event_type for item in delivery_events} >= {
        "signed_delivery_received",
        "delivery_failure_recorded",
    }
    assert all(item.metadata["external_side_effect"] is False for item in delivery_events)
