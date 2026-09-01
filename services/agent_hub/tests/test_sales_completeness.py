from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from npd_agent_hub.attribution import AttributionService
from npd_agent_hub.attribution_models import TouchpointEvent, TouchpointType
from npd_agent_hub.campaign_models import CampaignBudget, CampaignCreate, KPITarget
from npd_agent_hub.campaigns import CampaignService
from npd_agent_hub.config import HubSettings
from npd_agent_hub.delivery_models import AttributionHeartbeatReceipt, AttributionProducerHeartbeat
from npd_agent_hub.delivery_observability import AttributionDeliveryService
from npd_agent_hub.journeys import JourneyService
from npd_agent_hub.sales_completeness import (
    COMPLETENESS_DIGEST_METADATA_KEY,
    activity_batch_digest,
    digest_model,
)
from npd_agent_hub.sales_intelligence import SalesIntelligenceService
from npd_agent_hub.sales_intelligence_models import (
    SalesActivityCompletenessClaim,
    SalesActivityCompletenessProof,
    SalesActivityObservation,
    SalesActivityType,
    SalesIntelligencePreviewRequest,
    SalesSLAStatus,
)
from npd_agent_hub.store import MemoryHubStore


UTC = timezone.utc
BASE = datetime(2026, 9, 1, 8, tzinfo=UTC)
AS_OF = BASE + timedelta(hours=30)
SIGNING_KEY = "s" * 48
KEY_ID = "sales-completeness-test-v1"


def build_store():
    store = MemoryHubStore()
    campaign = CampaignService(store).create(
        CampaignCreate(
            name="Vịnh Tiên Completeness",
            project="Vinhomes Green Paradise – Vịnh Tiên",
            project_code="VGP",
            objective="Xác minh completeness trước khi xác nhận SLA breach",
            audience=["Nhà đầu tư"],
            budget=CampaignBudget(amount=100_000_000),
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30),
            kpi_targets=[
                KPITarget(name="Lead", target=300, unit="lead", funnel_stage="lead")
            ],
            owner="owner",
        ),
        actor="operator",
    )
    store.append_touchpoint(
        TouchpointEvent(
            event_id="tpt_" + "a" * 32,
            campaign_id=campaign.campaign_id,
            event_type=TouchpointType.LEAD_CREATED,
            occurred_at=BASE,
            source_system="EspoCRM",
            channel="crm",
            lead_id="lead-001",
        )
    )
    return store, campaign


def delivery_service(store: MemoryHubStore, *, clock_at: datetime = AS_OF):
    settings = HubSettings(
        attribution_receipt_signing_key=SIGNING_KEY,
        attribution_receipt_key_id=KEY_ID,
    )
    return AttributionDeliveryService(
        store,
        AttributionService(store),
        settings,
        clock=lambda: clock_at,
    )


def activity(
    activity_id: str,
    activity_type: SalesActivityType,
    occurred_at: datetime,
    campaign_id: str,
) -> SalesActivityObservation:
    return SalesActivityObservation(
        activity_id=activity_id,
        activity_type=activity_type,
        occurred_at=occurred_at,
        source_system="Sales Hub",
        source_record_ref=f"record-{activity_id}",
        campaign_id=campaign_id,
        lead_id="lead-001",
    )


def proof_for(
    delivery: AttributionDeliveryService,
    *,
    campaign_id: str,
    observations: list[SalesActivityObservation],
    covered_activity_types: list[SalesActivityType],
    complete_through: datetime,
    heartbeat_id: str = "sales-hub-completeness-001",
    sequence: int = 1,
) -> SalesActivityCompletenessProof:
    claim = SalesActivityCompletenessClaim(
        subject_ref="lead:lead-001",
        campaign_id=campaign_id,
        window_start=BASE,
        complete_through=complete_through,
        covered_activity_types=covered_activity_types,
        activity_batch_digest=activity_batch_digest(observations),
        record_count=len(observations),
    )
    heartbeat = AttributionProducerHeartbeat(
        heartbeat_id=heartbeat_id,
        producer="sales_hub",
        emitted_at=AS_OF,
        sequence=sequence,
        metadata={COMPLETENESS_DIGEST_METADATA_KEY: digest_model(claim)},
    )
    receipt = delivery.ingest_heartbeat(heartbeat, actor="operator")
    return SalesActivityCompletenessProof(
        claim=claim,
        heartbeat=heartbeat,
        receipt=receipt,
    )


def test_full_signed_completeness_can_confirm_missing_activity_as_breached():
    store, campaign = build_store()
    delivery = delivery_service(store)
    observations: list[SalesActivityObservation] = []
    proof = proof_for(
        delivery,
        campaign_id=campaign.campaign_id,
        observations=observations,
        covered_activity_types=list(SalesActivityType),
        complete_through=AS_OF,
    )

    snapshot = SalesIntelligenceService(
        store,
        JourneyService(store),
        delivery,
    ).preview(
        SalesIntelligencePreviewRequest(
            subject_ref="lead:lead-001",
            observations=observations,
            completeness_proof=proof,
            as_of=AS_OF,
        )
    )

    assert snapshot.completeness_verified is True
    assert snapshot.source_complete is True
    assert snapshot.completeness_receipt_id == proof.receipt.receipt_id
    assert snapshot.completeness_complete_through == AS_OF
    assert snapshot.first_response_sla.status == SalesSLAStatus.BREACHED
    assert snapshot.visit_booking_sla.status == SalesSLAStatus.BREACHED
    assert snapshot.first_response_sla.completeness_receipt_id == proof.receipt.receipt_id
    assert snapshot.visit_booking_sla.completeness_receipt_id == proof.receipt.receipt_id
    assert "sales_activity_source_completeness" not in snapshot.missing_inputs
    assert snapshot.persisted is False
    assert snapshot.execution_enabled is False
    assert snapshot.external_writes_enabled is False
    assert snapshot.customer_contact_enabled is False


def test_partial_completeness_only_confirms_the_covered_sla_deadline():
    store, campaign = build_store()
    delivery = delivery_service(store)
    observations: list[SalesActivityObservation] = []
    proof = proof_for(
        delivery,
        campaign_id=campaign.campaign_id,
        observations=observations,
        covered_activity_types=[SalesActivityType.FIRST_RESPONSE],
        complete_through=BASE + timedelta(minutes=30),
    )

    snapshot = SalesIntelligenceService(store, JourneyService(store), delivery).preview(
        SalesIntelligencePreviewRequest(
            subject_ref="lead:lead-001",
            observations=observations,
            completeness_proof=proof,
            as_of=AS_OF,
        )
    )

    assert snapshot.completeness_verified is True
    assert snapshot.source_complete is False
    assert snapshot.first_response_sla.status == SalesSLAStatus.BREACHED
    assert snapshot.visit_booking_sla.status == SalesSLAStatus.OVERDUE_MISSING_EVIDENCE
    assert "sales_activity_source_completeness" in snapshot.missing_inputs


def test_claim_tampering_breaks_heartbeat_digest_binding_and_blocks_confirmed_breach():
    store, campaign = build_store()
    delivery = delivery_service(store)
    observations: list[SalesActivityObservation] = []
    proof = proof_for(
        delivery,
        campaign_id=campaign.campaign_id,
        observations=observations,
        covered_activity_types=list(SalesActivityType),
        complete_through=AS_OF,
    )
    tampered_claim = proof.claim.model_copy(
        update={"complete_through": AS_OF - timedelta(minutes=1)}
    )
    tampered = SalesActivityCompletenessProof(
        claim=tampered_claim,
        heartbeat=proof.heartbeat,
        receipt=proof.receipt,
    )

    snapshot = SalesIntelligenceService(store, JourneyService(store), delivery).preview(
        SalesIntelligencePreviewRequest(
            subject_ref="lead:lead-001",
            observations=observations,
            completeness_proof=tampered,
            as_of=AS_OF,
        )
    )

    assert snapshot.completeness_verified is False
    assert snapshot.source_complete is False
    assert "not bound" in snapshot.completeness_detail
    assert snapshot.first_response_sla.status == SalesSLAStatus.OVERDUE_MISSING_EVIDENCE
    assert snapshot.visit_booking_sla.status == SalesSLAStatus.OVERDUE_MISSING_EVIDENCE


def test_activity_batch_tampering_breaks_completeness_even_with_valid_receipt():
    store, campaign = build_store()
    delivery = delivery_service(store)
    signed_batch = [
        activity(
            "act-response",
            SalesActivityType.FIRST_RESPONSE,
            BASE + timedelta(minutes=10),
            campaign.campaign_id,
        )
    ]
    proof = proof_for(
        delivery,
        campaign_id=campaign.campaign_id,
        observations=signed_batch,
        covered_activity_types=list(SalesActivityType),
        complete_through=AS_OF,
    )

    snapshot = SalesIntelligenceService(store, JourneyService(store), delivery).preview(
        SalesIntelligencePreviewRequest(
            subject_ref="lead:lead-001",
            observations=[],
            completeness_proof=proof,
            as_of=AS_OF,
        )
    )

    assert snapshot.completeness_verified is False
    assert snapshot.source_complete is False
    assert "record_count" in snapshot.completeness_detail
    assert snapshot.first_response_sla.status == SalesSLAStatus.OVERDUE_MISSING_EVIDENCE


def test_tampered_receipt_signature_blocks_completeness():
    store, campaign = build_store()
    delivery = delivery_service(store)
    observations: list[SalesActivityObservation] = []
    proof = proof_for(
        delivery,
        campaign_id=campaign.campaign_id,
        observations=observations,
        covered_activity_types=list(SalesActivityType),
        complete_through=AS_OF,
    )
    bad_receipt = AttributionHeartbeatReceipt(
        **proof.receipt.model_dump(exclude={"signature"}),
        signature=f"hmac-sha256:{'0' * 64}",
    )
    tampered = SalesActivityCompletenessProof(
        claim=proof.claim,
        heartbeat=proof.heartbeat,
        receipt=bad_receipt,
    )

    snapshot = SalesIntelligenceService(store, JourneyService(store), delivery).preview(
        SalesIntelligencePreviewRequest(
            subject_ref="lead:lead-001",
            observations=observations,
            completeness_proof=tampered,
            as_of=AS_OF,
        )
    )

    assert snapshot.completeness_verified is False
    assert snapshot.source_complete is False
    assert "signature" in snapshot.completeness_detail.lower()
    assert snapshot.first_response_sla.status == SalesSLAStatus.OVERDUE_MISSING_EVIDENCE


def test_signed_batch_with_duplicate_or_untrusted_rows_cannot_claim_complete_source():
    store, campaign = build_store()
    delivery = delivery_service(store)
    valid = activity(
        "act-response",
        SalesActivityType.FIRST_RESPONSE,
        BASE + timedelta(minutes=10),
        campaign.campaign_id,
    )
    observations = [valid, valid]
    proof = proof_for(
        delivery,
        campaign_id=campaign.campaign_id,
        observations=observations,
        covered_activity_types=list(SalesActivityType),
        complete_through=AS_OF,
    )

    snapshot = SalesIntelligenceService(store, JourneyService(store), delivery).preview(
        SalesIntelligencePreviewRequest(
            subject_ref="lead:lead-001",
            observations=observations,
            completeness_proof=proof,
            as_of=AS_OF,
        )
    )

    assert snapshot.duplicate_activity_count == 1
    assert snapshot.completeness_verified is False
    assert snapshot.source_complete is False
    assert "duplicate or untrusted" in snapshot.completeness_detail
    assert snapshot.first_response_sla.status == SalesSLAStatus.MET
