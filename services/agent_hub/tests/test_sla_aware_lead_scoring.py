from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
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
from npd_agent_hub.lead_scoring_models import ScoreFactorStatus
from npd_agent_hub.main import app
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
from npd_agent_hub.store import MemoryHubStore


UTC = timezone.utc
CAMPAIGN_ID = "CMP-VGP-VINHTIEN-202609-01"
AS_OF = datetime(2026, 9, 1, 12, tzinfo=UTC)
SIGNING_KEY = "q" * 48
KEY_ID = "sales-score-test-v1"


def scorer() -> LeadScoringService:
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
    store.append_touchpoint(
        TouchpointEvent(
            event_id="tpt_" + "2" * 32,
            campaign_id=CAMPAIGN_ID,
            event_type=TouchpointType.LANDING_VIEW,
            occurred_at=datetime(2026, 9, 1, 9, tzinfo=UTC),
            source_system="GA4",
            channel="web",
            lead_id="lead-001",
        )
    )
    return LeadScoringService(JourneyService(store))


def sales_snapshot(
    first_status: SalesSLAStatus,
    visit_status: SalesSLAStatus,
    *,
    verified: bool,
) -> SalesIntelligenceSnapshot:
    receipt_id = "ahr_" + "a" * 24 if verified else None
    watermark = AS_OF if verified else None
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
        completeness_complete_through=watermark,
        completeness_detail=("verified" if verified else "unverified"),
        source_complete=verified,
    )


def test_sla_met_factors_are_observed_and_extend_denominator_only_in_v2():
    service = scorer()
    baseline = service.score("lead:lead-001", as_of=AS_OF)
    enhanced = service.score(
        "lead:lead-001",
        as_of=AS_OF,
        sales_intelligence=sales_snapshot(
            SalesSLAStatus.MET,
            SalesSLAStatus.MET,
            verified=True,
        ),
    )

    assert baseline.score == 44.0
    assert baseline.available_points == 100
    assert baseline.score_version == "phase-9a-score-v1"
    assert [item.name for item in baseline.factors] == [
        "journey_state",
        "recency",
        "engagement_frequency",
    ]

    assert enhanced.score_version == "phase-9b-score-v2"
    assert enhanced.methodology == "journey_momentum_with_sales_sla_v2"
    assert enhanced.available_points == 115
    assert enhanced.score == 51.3
    assert [item.name for item in enhanced.factors] == [
        "journey_state",
        "recency",
        "engagement_frequency",
        "first_response_sla",
        "visit_booking_sla",
    ]
    first = next(item for item in enhanced.factors if item.name == "first_response_sla")
    visit = next(item for item in enhanced.factors if item.name == "visit_booking_sla")
    assert first.status == ScoreFactorStatus.OBSERVED and first.contribution == 6
    assert visit.status == ScoreFactorStatus.OBSERVED and visit.contribution == 9
    assert "sales_sla" not in enhanced.missing_inputs


def test_verified_breach_is_zero_point_observed_factor_and_can_lower_score():
    result = scorer().score(
        "lead:lead-001",
        as_of=AS_OF,
        sales_intelligence=sales_snapshot(
            SalesSLAStatus.BREACHED,
            SalesSLAStatus.BREACHED,
            verified=True,
        ),
    )

    assert result.available_points == 115
    assert result.score == 38.26
    sla_factors = [item for item in result.factors if item.name.endswith("_sla")]
    assert all(item.status == ScoreFactorStatus.OBSERVED for item in sla_factors)
    assert [item.contribution for item in sla_factors] == [0, 0]
    assert all(any(ref.startswith("ahr_") for ref in item.evidence_refs) for item in sla_factors)


def test_unsigned_or_unverified_sales_activity_cannot_change_base_score():
    service = scorer()
    baseline = service.score("lead:lead-001", as_of=AS_OF)
    result = service.score(
        "lead:lead-001",
        as_of=AS_OF,
        sales_intelligence=sales_snapshot(
            SalesSLAStatus.MET,
            SalesSLAStatus.LATE,
            verified=False,
        ),
    )

    assert result.score_version == "phase-9b-score-v2"
    assert result.score == baseline.score
    assert result.available_points == baseline.available_points
    sla_factors = [item for item in result.factors if item.name.endswith("_sla")]
    assert all(item.status == ScoreFactorStatus.MISSING for item in sla_factors)
    assert "sales_sla_completeness" in result.missing_inputs
    assert "first_response_sla" in result.missing_inputs
    assert "visit_booking_sla" in result.missing_inputs


def test_overdue_without_coverage_remains_missing_and_never_becomes_negative():
    result = scorer().score(
        "lead:lead-001",
        as_of=AS_OF,
        sales_intelligence=sales_snapshot(
            SalesSLAStatus.OVERDUE_MISSING_EVIDENCE,
            SalesSLAStatus.PENDING,
            verified=True,
        ),
    )

    assert result.score == 44.0
    assert result.available_points == 100
    sla_factors = [item for item in result.factors if item.name.endswith("_sla")]
    assert all(item.status == ScoreFactorStatus.MISSING for item in sla_factors)
    assert all(item.contribution is None for item in sla_factors)


def test_sales_snapshot_subject_and_as_of_must_match_score_request():
    service = scorer()
    good = sales_snapshot(SalesSLAStatus.MET, SalesSLAStatus.MET, verified=True)
    with pytest.raises(ValueError, match="subject must match"):
        service.score(
            "lead:lead-001",
            as_of=AS_OF,
            sales_intelligence=good.model_copy(update={"subject_ref": "lead:other"}),
        )
    with pytest.raises(ValueError, match="as_of must match"):
        service.score(
            "lead:lead-001",
            as_of=AS_OF,
            sales_intelligence=good.model_copy(update={"as_of": AS_OF + timedelta(minutes=1)}),
        )


def build_api_fixture():
    store = MemoryHubStore()
    campaign = CampaignService(store).create(
        CampaignCreate(
            name="Vịnh Tiên SLA Score",
            project="Vinhomes Green Paradise – Vịnh Tiên",
            project_code="VGP",
            objective="Preview SLA-aware lead score",
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
            occurred_at=datetime(2026, 9, 1, 8, tzinfo=UTC),
            source_system="EspoCRM",
            channel="crm",
            lead_id="lead-001",
        )
    )
    return store, campaign


def test_sales_preview_api_uses_real_signed_completeness_and_does_not_mutate_inputs():
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
    journeys = JourneyService(store)
    delivery_settings = HubSettings(
        attribution_receipt_signing_key=SIGNING_KEY,
        attribution_receipt_key_id=KEY_ID,
    )
    delivery = AttributionDeliveryService(
        store,
        AttributionService(store),
        delivery_settings,
        clock=lambda: datetime(2026, 9, 2, 14, tzinfo=UTC),
    )
    api_as_of = datetime(2026, 9, 2, 14, tzinfo=UTC)
    observations = []
    claim = SalesActivityCompletenessClaim(
        subject_ref="lead:lead-001",
        campaign_id=campaign.campaign_id,
        window_start=datetime(2026, 9, 1, 8, tzinfo=UTC),
        complete_through=api_as_of,
        covered_activity_types=list(SalesActivityType),
        activity_batch_digest=activity_batch_digest(observations),
        record_count=0,
    )
    heartbeat = AttributionProducerHeartbeat(
        heartbeat_id="sales-score-completeness-001",
        producer="sales_hub",
        emitted_at=api_as_of,
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
        as_of=api_as_of,
    )

    hub.store = store
    hub.journeys = journeys
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
                "/api/v1/lead-scores/sales-preview",
                headers=viewer,
                json=request.model_dump(mode="json"),
            ).status_code
            == 403
        )
        response = client.post(
            "/api/v1/lead-scores/sales-preview",
            headers=operator,
            json=request.model_dump(mode="json"),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["sales_intelligence"]["completeness_verified"] is True
        assert body["sales_intelligence"]["source_complete"] is True
        assert body["lead_score"]["score_version"] == "phase-9b-score-v2"
        factors = {item["name"]: item for item in body["lead_score"]["factors"]}
        assert factors["first_response_sla"]["status"] == "observed"
        assert factors["first_response_sla"]["contribution"] == 0
        assert factors["visit_booking_sla"]["status"] == "observed"
        assert factors["visit_booking_sla"]["contribution"] == 0
        assert body["persisted"] is False
        assert body["execution_enabled"] is False
        assert body["external_writes_enabled"] is False
        assert body["customer_contact_enabled"] is False
        assert response.headers["cache-control"] == "no-store"

        # Existing GET remains Phase 9A v1 and is not affected by the preview.
        v1 = client.get(
            "/api/v1/lead-scores/lead:lead-001",
            params={"as_of": api_as_of.isoformat()},
            headers=viewer,
        )
        assert v1.status_code == 200
        assert v1.json()["score_version"] == "phase-9a-score-v1"
        assert [item["name"] for item in v1.json()["factors"]] == [
            "journey_state",
            "recency",
            "engagement_frequency",
        ]

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
