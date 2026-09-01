from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient

from npd_agent_hub.attribution import AttributionService
from npd_agent_hub.attribution_models import TouchpointEvent, TouchpointType
from npd_agent_hub.auth import authorizer
from npd_agent_hub.campaign_models import CampaignBudget, CampaignCreate, KPITarget
from npd_agent_hub.campaigns import CampaignService
from npd_agent_hub.config import HubSettings
from npd_agent_hub.delivery_models import AttributionProducerHeartbeat
from npd_agent_hub.delivery_observability import AttributionDeliveryService
from npd_agent_hub.journeys import JourneyService
from npd_agent_hub.lead_scoring import LeadScoringService
from npd_agent_hub.main import app
from npd_agent_hub.next_best_action_models import RecommendationPriority, RecommendedAction
from npd_agent_hub.orchestrator import hub
from npd_agent_hub.sales_completeness import (
    COMPLETENESS_DIGEST_METADATA_KEY,
    activity_batch_digest,
    digest_model,
)
from npd_agent_hub.sales_intelligence_models import (
    SalesActivityCompletenessClaim,
    SalesActivityCompletenessProof,
    SalesActivityType,
    SalesFunnelEvidence,
    SalesIntelligencePreviewRequest,
    SalesIntelligenceSnapshot,
    SalesSLAStatus,
    SalesSLAWindow,
)
from npd_agent_hub.sales_next_best_action import SalesAwareNextBestActionService
from npd_agent_hub.store import MemoryHubStore


UTC = timezone.utc
CAMPAIGN_ID = "CMP-VGP-VINHTIEN-202609-01"
AS_OF = datetime(2026, 9, 2, 14, tzinfo=UTC)
SIGNING_KEY = "n" * 48
KEY_ID = "sales-nba-test-v1"


def journeys() -> JourneyService:
    store = MemoryHubStore()
    store.append_touchpoint(
        TouchpointEvent(
            event_id="tpt_" + "1" * 32,
            campaign_id=CAMPAIGN_ID,
            event_type=TouchpointType.LEAD_CREATED,
            occurred_at=datetime(2026, 9, 1, 8, tzinfo=UTC),
            source_system="EspoCRM",
            channel="crm",
            lead_id="lead-001",
        )
    )
    return JourneyService(store)


def sales_snapshot(
    first_status: SalesSLAStatus,
    visit_status: SalesSLAStatus,
    *,
    verified: bool,
) -> SalesIntelligenceSnapshot:
    receipt_id = "ahr_" + "b" * 24 if verified else None
    return SalesIntelligenceSnapshot(
        subject_ref="lead:lead-001",
        as_of=AS_OF,
        campaign_id=CAMPAIGN_ID,
        project="Vinhomes Green Paradise – Vịnh Tiên",
        lead_start_at=datetime(2026, 9, 1, 8, tzinfo=UTC),
        lead_start_basis="lead_created",
        first_response_sla=SalesSLAWindow(
            name="first_response",
            target_minutes=15,
            status=first_status,
            clock_start_at=datetime(2026, 9, 1, 8, tzinfo=UTC),
            deadline_at=datetime(2026, 9, 1, 8, 15, tzinfo=UTC),
            observed_at=(
                datetime(2026, 9, 1, 8, 10, tzinfo=UTC)
                if first_status == SalesSLAStatus.MET
                else datetime(2026, 9, 1, 8, 30, tzinfo=UTC)
                if first_status == SalesSLAStatus.LATE
                else None
            ),
            elapsed_minutes=(
                10 if first_status == SalesSLAStatus.MET else 30 if first_status == SalesSLAStatus.LATE else None
            ),
            evidence_refs=(
                ["act-first"]
                if first_status in {SalesSLAStatus.MET, SalesSLAStatus.LATE}
                else []
            ),
            completeness_receipt_id=(receipt_id if first_status == SalesSLAStatus.BREACHED else None),
        ),
        visit_booking_sla=SalesSLAWindow(
            name="visit_booking",
            target_minutes=1440,
            status=visit_status,
            clock_start_at=datetime(2026, 9, 1, 8, tzinfo=UTC),
            deadline_at=datetime(2026, 9, 2, 8, tzinfo=UTC),
            observed_at=(
                datetime(2026, 9, 1, 20, tzinfo=UTC)
                if visit_status == SalesSLAStatus.MET
                else datetime(2026, 9, 2, 10, tzinfo=UTC)
                if visit_status == SalesSLAStatus.LATE
                else None
            ),
            elapsed_minutes=(
                720 if visit_status == SalesSLAStatus.MET else 1560 if visit_status == SalesSLAStatus.LATE else None
            ),
            evidence_refs=(
                ["act-visit"]
                if visit_status in {SalesSLAStatus.MET, SalesSLAStatus.LATE}
                else []
            ),
            completeness_receipt_id=(receipt_id if visit_status == SalesSLAStatus.BREACHED else None),
        ),
        funnel=SalesFunnelEvidence(),
        accepted_activity_count=0,
        duplicate_activity_count=0,
        untrusted_activity_count=0,
        missing_inputs=[],
        completeness_verified=verified,
        completeness_receipt_id=receipt_id,
        completeness_complete_through=(AS_OF if verified else None),
        completeness_detail=("verified" if verified else "unverified"),
        source_complete=verified,
    )


def recommend(first_status: SalesSLAStatus, visit_status: SalesSLAStatus, *, verified: bool):
    journey_service = journeys()
    sales = sales_snapshot(first_status, visit_status, verified=verified)
    score = LeadScoringService(journey_service).score(
        "lead:lead-001",
        as_of=AS_OF,
        sales_intelligence=sales,
    )
    return SalesAwareNextBestActionService(journey_service).recommend(
        "lead:lead-001",
        sales_intelligence=sales,
        lead_score=score,
    )


def test_verified_sla_breach_escalates_early_sales_review_to_high_and_15_minutes():
    result = recommend(
        SalesSLAStatus.BREACHED,
        SalesSLAStatus.BREACHED,
        verified=True,
    )

    assert result.recommendation_version == "phase-9b-nba-v2"
    assert result.recommended_action == RecommendedAction.REVIEW_SALES_FOLLOW_UP
    assert result.priority == RecommendationPriority.HIGH
    assert result.sla_minutes == 15
    assert result.sla_scope == "internal_review_only"
    assert result.project == "Vinhomes Green Paradise – Vịnh Tiên"
    assert "signed Sales Hub completeness proof confirms" in result.reason
    assert any(ref.startswith("ahr_") for ref in result.evidence_refs)
    assert result.execution_enabled is False
    assert result.external_writes_enabled is False
    assert result.customer_contact_enabled is False


def test_verified_late_sla_escalates_low_base_priority_to_at_least_medium_and_60_minutes():
    result = recommend(
        SalesSLAStatus.LATE,
        SalesSLAStatus.MET,
        verified=True,
    )

    assert result.recommended_action == RecommendedAction.REVIEW_SALES_FOLLOW_UP
    assert result.priority in {RecommendationPriority.MEDIUM, RecommendationPriority.HIGH}
    assert result.sla_minutes <= 60
    assert "late Sales SLA" in result.reason


def test_unverified_breach_like_input_cannot_escalate_recommendation():
    result = recommend(
        SalesSLAStatus.BREACHED,
        SalesSLAStatus.BREACHED,
        verified=False,
    )

    assert result.recommendation_version == "phase-9b-nba-v2"
    assert result.priority == RecommendationPriority.LOW
    assert result.sla_minutes == 1440
    assert "does not escalate" in result.reason
    assert "sales_sla_completeness" in result.missing_context


def test_overdue_without_completeness_coverage_does_not_escalate():
    result = recommend(
        SalesSLAStatus.OVERDUE_MISSING_EVIDENCE,
        SalesSLAStatus.OVERDUE_MISSING_EVIDENCE,
        verified=True,
    )

    assert result.priority == RecommendationPriority.LOW
    assert result.sla_minutes == 1440
    assert result.execution_enabled is False
    assert result.customer_contact_enabled is False


def build_api_fixture():
    store = MemoryHubStore()
    campaign = CampaignService(store).create(
        CampaignCreate(
            name="Vịnh Tiên SLA NBA",
            project="Vinhomes Green Paradise – Vịnh Tiên",
            project_code="VGP",
            objective="Preview SLA-aware NBA",
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
            event_id="tpt_" + "c" * 32,
            campaign_id=campaign.campaign_id,
            event_type=TouchpointType.LEAD_CREATED,
            occurred_at=datetime(2026, 9, 1, 8, tzinfo=UTC),
            source_system="EspoCRM",
            channel="crm",
            lead_id="lead-001",
        )
    )
    return store, campaign


def test_sales_nba_api_uses_signed_proof_is_operator_only_and_keeps_v1_unchanged():
    previous_auth = authorizer.settings
    previous_store = hub.store
    previous_journeys = hub.journeys
    previous_delivery = hub.delivery

    authorizer.settings = HubSettings(
        auth_mode="static_token",
        viewer_token="viewer-secret",
        operator_token="operator-secret",
        owner_token="owner-secret",
    )
    store, campaign = build_api_fixture()
    journey_service = JourneyService(store)
    delivery = AttributionDeliveryService(
        store,
        AttributionService(store),
        HubSettings(
            attribution_receipt_signing_key=SIGNING_KEY,
            attribution_receipt_key_id=KEY_ID,
        ),
        clock=lambda: AS_OF,
    )
    observations = []
    claim = SalesActivityCompletenessClaim(
        subject_ref="lead:lead-001",
        campaign_id=campaign.campaign_id,
        window_start=datetime(2026, 9, 1, 8, tzinfo=UTC),
        complete_through=AS_OF,
        covered_activity_types=list(SalesActivityType),
        activity_batch_digest=activity_batch_digest(observations),
        record_count=0,
    )
    heartbeat = AttributionProducerHeartbeat(
        heartbeat_id="sales-nba-completeness-001",
        producer="sales_hub",
        emitted_at=AS_OF,
        sequence=1,
        metadata={COMPLETENESS_DIGEST_METADATA_KEY: digest_model(claim)},
    )
    receipt = delivery.ingest_heartbeat(heartbeat, actor="operator")
    request = SalesIntelligencePreviewRequest(
        subject_ref="lead:lead-001",
        observations=observations,
        completeness_proof=SalesActivityCompletenessProof(
            claim=claim,
            heartbeat=heartbeat,
            receipt=receipt,
        ),
        as_of=AS_OF,
    )

    hub.store = store
    hub.journeys = journey_service
    hub.delivery = delivery
    client = TestClient(app)
    viewer = {"Authorization": "Bearer viewer-secret"}
    operator = {"Authorization": "Bearer operator-secret"}

    try:
        before_touchpoints = [
            item.model_dump(mode="json")
            for item in store.list_touchpoints(lead_id="lead-001", limit=100)
        ]
        before_heartbeats = [
            item.model_dump(mode="json")
            for item in store.list_attribution_heartbeat_receipts(producer="sales_hub", limit=100)
        ]
        before_tasks = store.list_recent_tasks(100)

        assert (
            client.post(
                "/api/v1/next-best-actions/sales-preview",
                headers=viewer,
                json=request.model_dump(mode="json"),
            ).status_code
            == 403
        )
        response = client.post(
            "/api/v1/next-best-actions/sales-preview",
            headers=operator,
            json=request.model_dump(mode="json"),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["sales_intelligence"]["completeness_verified"] is True
        assert body["lead_score"]["score_version"] == "phase-9b-score-v2"
        recommendation = body["recommendation"]
        assert recommendation["recommendation_version"] == "phase-9b-nba-v2"
        assert recommendation["recommended_action"] == "review_sales_follow_up"
        assert recommendation["priority"] == "high"
        assert recommendation["sla_minutes"] == 15
        assert recommendation["sla_scope"] == "internal_review_only"
        assert recommendation["execution_enabled"] is False
        assert recommendation["external_writes_enabled"] is False
        assert recommendation["customer_contact_enabled"] is False
        assert body["persisted"] is False
        assert body["execution_enabled"] is False
        assert body["customer_contact_enabled"] is False
        assert response.headers["cache-control"] == "no-store"

        # Existing NBA v1 remains unchanged and does not consume Sales SLA preview state.
        v1 = client.get(
            "/api/v1/next-best-actions/lead:lead-001",
            params={"as_of": AS_OF.isoformat()},
            headers=viewer,
        )
        assert v1.status_code == 200
        assert v1.json()["recommendation_version"] == "phase-9a-nba-v1"

        after_touchpoints = [
            item.model_dump(mode="json")
            for item in store.list_touchpoints(lead_id="lead-001", limit=100)
        ]
        after_heartbeats = [
            item.model_dump(mode="json")
            for item in store.list_attribution_heartbeat_receipts(producer="sales_hub", limit=100)
        ]
        assert after_touchpoints == before_touchpoints
        assert after_heartbeats == before_heartbeats
        assert store.list_recent_tasks(100) == before_tasks
    finally:
        authorizer.settings = previous_auth
        hub.store = previous_store
        hub.journeys = previous_journeys
        hub.delivery = previous_delivery
