from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi.testclient import TestClient
from pydantic import ValidationError

from npd_agent_hub.attribution import AttributionService
from npd_agent_hub.attribution_models import TouchpointEvent, TouchpointType
from npd_agent_hub.auth import authorizer
from npd_agent_hub.campaign_models import CampaignBudget, CampaignCreate, KPITarget
from npd_agent_hub.campaigns import CampaignService
from npd_agent_hub.config import HubSettings
from npd_agent_hub.delivery_models import AttributionProducerHeartbeat
from npd_agent_hub.delivery_observability import AttributionDeliveryService
from npd_agent_hub.journeys import JourneyService
from npd_agent_hub.main import app
from npd_agent_hub.nba_review import NBAReviewService
from npd_agent_hub.nba_review_models import NBAReviewCreate, NBAReviewDisposition
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
    SalesIntelligencePreviewRequest,
)
from npd_agent_hub.sales_nba_review import SalesNBAReviewService
from npd_agent_hub.sales_nba_review_models import SalesNBAReviewCreate
from npd_agent_hub.store import MemoryHubStore


UTC = timezone.utc
AS_OF = datetime(2026, 9, 2, 14, tzinfo=UTC)
SIGNING_KEY = "r" * 48
KEY_ID = "sales-review-v2-test"


def fixture():
    store = MemoryHubStore()
    campaign = CampaignService(store).create(
        CampaignCreate(
            name="Vịnh Tiên NBA v2 Review",
            project="Vinhomes Green Paradise – Vịnh Tiên",
            project_code="VGP",
            objective="Đo false positive của NBA v2 ở chế độ shadow",
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
            event_id="tpt_" + "d" * 32,
            campaign_id=campaign.campaign_id,
            event_type=TouchpointType.LEAD_CREATED,
            occurred_at=datetime(2026, 9, 1, 8, tzinfo=UTC),
            source_system="EspoCRM",
            channel="crm",
            lead_id="lead-001",
        )
    )
    journeys = JourneyService(store)
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
        heartbeat_id="sales-review-v2-heartbeat-001",
        producer="sales_hub",
        emitted_at=AS_OF,
        sequence=1,
        metadata={COMPLETENESS_DIGEST_METADATA_KEY: digest_model(claim)},
    )
    receipt = delivery.ingest_heartbeat(heartbeat, actor="operator")
    evaluation = SalesIntelligencePreviewRequest(
        subject_ref="lead:lead-001",
        observations=observations,
        completeness_proof=SalesActivityCompletenessProof(
            claim=claim,
            heartbeat=heartbeat,
            receipt=receipt,
        ),
        as_of=AS_OF,
    )
    return store, journeys, delivery, evaluation


def test_sales_nba_review_recomputes_v2_and_keeps_v1_telemetry_separate():
    store, journeys, delivery, evaluation = fixture()
    sales_reviews = SalesNBAReviewService(store, journeys, delivery)

    v2 = sales_reviews.record(
        SalesNBAReviewCreate(
            evaluation=evaluation,
            disposition=NBAReviewDisposition.NOT_RELEVANT,
            note="SLA escalation is too aggressive for the verified context.",
        ),
        reviewer_role="operator",
    )
    v1 = NBAReviewService(store, journeys).record(
        NBAReviewCreate(
            subject_ref="lead:lead-001",
            disposition=NBAReviewDisposition.RELEVANT,
            note="Phase 9A recommendation is reasonable for the journey-only context.",
            as_of=AS_OF,
        ),
        reviewer_role="owner",
    )

    assert v2.recommendation_version == "phase-9b-nba-v2"
    assert v2.false_positive is True
    assert v2.recommendation_executed is False
    assert v2.execution_enabled is False
    assert v2.external_writes_enabled is False
    assert v2.customer_contact_enabled is False
    assert any(ref.startswith("ahr_") for ref in v2.evidence_refs)

    v2_rows = sales_reviews.list(subject_ref="lead:lead-001")
    assert [item.review_id for item in v2_rows] == [v2.review_id]
    assert sales_reviews.summary(subject_ref="lead:lead-001").false_positive_rate == 1.0

    v1_rows = NBAReviewService(store, journeys).list(
        subject_ref="lead:lead-001",
        recommendation_version="phase-9a-nba-v1",
    )
    assert [item.review_id for item in v1_rows] == [v1.review_id]
    assert store.list_recent_tasks(10) == []


def test_sales_nba_review_rejects_viewer_role_and_raw_contact_note():
    store, journeys, delivery, evaluation = fixture()
    service = SalesNBAReviewService(store, journeys, delivery)
    request = SalesNBAReviewCreate(
        evaluation=evaluation,
        disposition=NBAReviewDisposition.RELEVANT,
    )
    try:
        service.record(request, reviewer_role="viewer")
        assert False, "viewer must not record NBA v2 review"
    except PermissionError as exc:
        assert "operator or owner" in str(exc)

    try:
        SalesNBAReviewCreate(
            evaluation=evaluation,
            disposition=NBAReviewDisposition.NEEDS_MORE_CONTEXT,
            note="Call +84 912 345 678 before judging the recommendation.",
        )
        assert False, "raw contact note must be rejected"
    except ValidationError as exc:
        assert "raw contact data" in str(exc)


def test_sales_nba_review_api_is_operator_only_and_existing_v1_routes_exclude_v2():
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
    store, journeys, delivery, evaluation = fixture()
    hub.store = store
    hub.journeys = journeys
    hub.delivery = delivery
    client = TestClient(app)
    viewer = {"Authorization": "Bearer viewer-secret"}
    operator = {"Authorization": "Bearer operator-secret"}
    payload = {
        "evaluation": evaluation.model_dump(mode="json"),
        "disposition": "not_relevant",
        "note": "SLA-aware priority should be lower for this shadow case.",
    }

    try:
        before_touchpoints = [item.model_dump(mode="json") for item in store.list_touchpoints(limit=100)]
        before_heartbeats = [
            item.model_dump(mode="json")
            for item in store.list_attribution_heartbeat_receipts(producer="sales_hub", limit=100)
        ]
        before_tasks = store.list_recent_tasks(100)

        assert (
            client.post(
                "/api/v1/next-best-actions/reviews/sales",
                headers=viewer,
                json=payload,
            ).status_code
            == 403
        )
        created = client.post(
            "/api/v1/next-best-actions/reviews/sales",
            headers=operator,
            json=payload,
        )
        assert created.status_code == 201
        body = created.json()
        assert body["recommendation_version"] == "phase-9b-nba-v2"
        assert body["false_positive"] is True
        assert body["recommendation_executed"] is False
        assert body["customer_contact_enabled"] is False

        sales_list = client.get(
            "/api/v1/next-best-actions/reviews/sales",
            headers=viewer,
        )
        assert sales_list.status_code == 200
        assert len(sales_list.json()) == 1
        assert sales_list.json()[0]["recommendation_version"] == "phase-9b-nba-v2"

        sales_summary = client.get(
            "/api/v1/next-best-actions/reviews/sales/summary",
            headers=viewer,
        )
        assert sales_summary.status_code == 200
        assert sales_summary.json()["total_reviews"] == 1
        assert sales_summary.json()["false_positive_rate"] == 1.0

        # Existing v1 review routes stay version-bound and do not expose the v2 record.
        v1_list = client.get(
            "/api/v1/next-best-actions/reviews",
            headers=viewer,
        )
        assert v1_list.status_code == 200
        assert v1_list.json() == []
        v1_summary = client.get(
            "/api/v1/next-best-actions/reviews/summary",
            headers=viewer,
        )
        assert v1_summary.status_code == 200
        assert v1_summary.json()["total_reviews"] == 0

        after_touchpoints = [item.model_dump(mode="json") for item in store.list_touchpoints(limit=100)]
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
