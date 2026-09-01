from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json

import pytest
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
from npd_agent_hub.orchestrator import hub
from npd_agent_hub.phase9_sales_shadow_evaluation import Phase9SalesShadowEvaluationService
from npd_agent_hub.phase9_sales_shadow_evaluation_models import Phase9SalesShadowEvaluationRequest
from npd_agent_hub.sales_completeness import (
    COMPLETENESS_DIGEST_METADATA_KEY,
    activity_batch_digest,
    digest_model,
)
from npd_agent_hub.sales_intelligence_models import (
    SalesActivityCompletenessClaim,
    SalesActivityCompletenessProof,
    SalesActivityObservation,
    SalesActivityType,
    SalesIntelligencePreviewRequest,
)
from npd_agent_hub.store import MemoryHubStore


UTC = timezone.utc
AS_OF = datetime(2026, 9, 2, 14, tzinfo=UTC)
SIGNING_KEY = "z" * 48
KEY_ID = "sales-shadow-test-v1"


def build_store():
    store = MemoryHubStore()
    campaign = CampaignService(store).create(
        CampaignCreate(
            name="Vịnh Tiên Sales Shadow",
            project="Vinhomes Green Paradise – Vịnh Tiên",
            project_code="VGP",
            objective="Đánh giá aggregate SLA-aware score và NBA ở chế độ shadow",
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
    for index, lead_id in enumerate(("lead-001", "lead-002", "lead-003"), start=1):
        store.append_touchpoint(
            TouchpointEvent(
                event_id="tpt_" + str(index) * 32,
                campaign_id=campaign.campaign_id,
                event_type=TouchpointType.LEAD_CREATED,
                occurred_at=datetime(2026, 9, 1, 8, tzinfo=UTC),
                source_system="EspoCRM",
                channel="crm",
                lead_id=lead_id,
            )
        )
    return store, campaign


def delivery_service(store: MemoryHubStore) -> AttributionDeliveryService:
    return AttributionDeliveryService(
        store,
        AttributionService(store),
        HubSettings(
            attribution_receipt_signing_key=SIGNING_KEY,
            attribution_receipt_key_id=KEY_ID,
        ),
        clock=lambda: AS_OF,
    )


def activity(
    activity_id: str,
    activity_type: SalesActivityType,
    occurred_at: datetime,
    campaign_id: str,
    lead_id: str,
) -> SalesActivityObservation:
    return SalesActivityObservation(
        activity_id=activity_id,
        activity_type=activity_type,
        occurred_at=occurred_at,
        source_system="Sales Hub",
        source_record_ref=f"record-{activity_id}",
        campaign_id=campaign_id,
        lead_id=lead_id,
    )


def signed_case(
    delivery: AttributionDeliveryService,
    *,
    campaign_id: str,
    lead_id: str,
    observations: list[SalesActivityObservation],
    sequence: int,
) -> SalesIntelligencePreviewRequest:
    subject_ref = f"lead:{lead_id}"
    claim = SalesActivityCompletenessClaim(
        subject_ref=subject_ref,
        campaign_id=campaign_id,
        window_start=datetime(2026, 9, 1, 8, tzinfo=UTC),
        complete_through=AS_OF,
        covered_activity_types=list(SalesActivityType),
        activity_batch_digest=activity_batch_digest(observations),
        record_count=len(observations),
    )
    heartbeat = AttributionProducerHeartbeat(
        heartbeat_id=f"sales-shadow-{sequence:03d}",
        producer="sales_hub",
        emitted_at=AS_OF,
        sequence=sequence,
        metadata={COMPLETENESS_DIGEST_METADATA_KEY: digest_model(claim)},
    )
    receipt = delivery.ingest_heartbeat(heartbeat, actor="operator")
    return SalesIntelligencePreviewRequest(
        subject_ref=subject_ref,
        observations=observations,
        completeness_proof=SalesActivityCompletenessProof(
            claim=claim,
            heartbeat=heartbeat,
            receipt=receipt,
        ),
        as_of=AS_OF,
    )


def build_request(store: MemoryHubStore, campaign_id: str, delivery: AttributionDeliveryService):
    breach = signed_case(
        delivery,
        campaign_id=campaign_id,
        lead_id="lead-001",
        observations=[],
        sequence=1,
    )
    met_rows = [
        activity(
            "act-response-002",
            SalesActivityType.FIRST_RESPONSE,
            datetime(2026, 9, 1, 8, 10, tzinfo=UTC),
            campaign_id,
            "lead-002",
        ),
        activity(
            "act-appointment-002",
            SalesActivityType.APPOINTMENT_BOOKED,
            datetime(2026, 9, 2, 4, tzinfo=UTC),
            campaign_id,
            "lead-002",
        ),
    ]
    met = signed_case(
        delivery,
        campaign_id=campaign_id,
        lead_id="lead-002",
        observations=met_rows,
        sequence=2,
    )
    unsigned = SalesIntelligencePreviewRequest(
        subject_ref="lead:lead-003",
        observations=[],
        as_of=AS_OF,
    )
    missing = SalesIntelligencePreviewRequest(
        subject_ref="lead:missing",
        observations=[],
        as_of=AS_OF,
    )
    return Phase9SalesShadowEvaluationRequest(
        cases=[breach, met, unsigned, missing, met],
    )


def test_sales_shadow_evaluation_is_deterministic_aggregate_only_and_non_mutating():
    store, campaign = build_store()
    delivery = delivery_service(store)
    journeys = JourneyService(store)
    request = build_request(store, campaign.campaign_id, delivery)
    service = Phase9SalesShadowEvaluationService(store, journeys, delivery)

    before_touchpoints = [item.model_dump(mode="json") for item in store.list_touchpoints(limit=100)]
    before_heartbeats = [
        item.model_dump(mode="json")
        for item in store.list_attribution_heartbeat_receipts(producer="sales_hub", limit=100)
    ]
    before_tasks = store.list_recent_tasks(100)

    first = service.evaluate(request)
    second = service.evaluate(request)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.requested_case_count == 5
    assert first.unique_subject_count == 4
    assert first.duplicate_case_count == 1
    assert first.evaluated_subject_count == 3
    assert first.failed_subject_count == 1
    assert first.failure_counts == {"not_found": 1}
    assert first.journey_state_counts == {"lead": 3}
    assert first.first_response_sla_status_counts == {
        "breached": 1,
        "met": 1,
        "overdue_missing_evidence": 1,
    }
    assert first.visit_booking_sla_status_counts == {
        "breached": 1,
        "met": 1,
        "overdue_missing_evidence": 1,
    }
    assert first.completeness_verified_count == 2
    assert first.source_complete_count == 2
    assert first.verified_breach_subject_count == 1
    assert first.verified_late_subject_count == 0
    assert first.score_band_counts == {"low_0_49": 3}
    assert first.average_lead_score == 30.9
    assert first.average_recommendation_confidence == 0.52
    assert first.recommendation_action_counts == {"review_sales_follow_up": 3}
    assert first.recommendation_priority_counts == {"high": 1, "low": 2}
    assert first.missing_input_counts == {
        "budget_fit": 3,
        "engagement_frequency": 3,
        "first_response_sla": 1,
        "project_fit": 3,
        "sales_sla_completeness": 1,
        "source_quality": 3,
        "visit_booking_sla": 1,
    }
    assert first.subjects_with_untrusted_journey_evidence == 0
    assert first.cases_with_untrusted_sales_activity == 0
    assert first.aggregate_only is True
    assert first.contains_subject_ids is False
    assert first.persisted is False
    assert first.execution_enabled is False
    assert first.external_writes_enabled is False
    assert first.customer_contact_enabled is False
    assert first.contains_raw_pii is False
    assert any("review telemetry is not yet connected" in caveat for caveat in first.caveats)

    serialized = json.dumps(first.model_dump(mode="json"), ensure_ascii=False)
    for value in ("lead-001", "lead-002", "lead-003", "lead:missing"):
        assert value not in serialized

    after_touchpoints = [item.model_dump(mode="json") for item in store.list_touchpoints(limit=100)]
    after_heartbeats = [
        item.model_dump(mode="json")
        for item in store.list_attribution_heartbeat_receipts(producer="sales_hub", limit=100)
    ]
    assert after_touchpoints == before_touchpoints
    assert after_heartbeats == before_heartbeats
    assert store.list_recent_tasks(100) == before_tasks


def test_sales_shadow_request_rejects_conflicting_duplicates_and_mixed_as_of():
    store, campaign = build_store()
    delivery = delivery_service(store)
    base = signed_case(
        delivery,
        campaign_id=campaign.campaign_id,
        lead_id="lead-001",
        observations=[],
        sequence=1,
    )
    conflicting = base.model_copy(
        update={
            "observations": [
                activity(
                    "act-conflict",
                    SalesActivityType.FIRST_RESPONSE,
                    datetime(2026, 9, 1, 8, 5, tzinfo=UTC),
                    campaign.campaign_id,
                    "lead-001",
                )
            ]
        }
    )
    with pytest.raises(ValidationError, match="byte-identical"):
        Phase9SalesShadowEvaluationRequest(cases=[base, conflicting])

    mixed_time = base.model_copy(update={"as_of": AS_OF + timedelta(minutes=1)})
    with pytest.raises(ValidationError, match="same as_of"):
        Phase9SalesShadowEvaluationRequest(cases=[base, mixed_time.model_copy(update={"subject_ref": "lead:lead-002"})])


def test_sales_shadow_api_is_operator_only_aggregate_and_preserves_phase9a_endpoint():
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
    store, campaign = build_store()
    delivery = delivery_service(store)
    journeys = JourneyService(store)
    request = build_request(store, campaign.campaign_id, delivery)
    hub.store = store
    hub.journeys = journeys
    hub.delivery = delivery
    client = TestClient(app)
    viewer = {"Authorization": "Bearer viewer-secret"}
    operator = {"Authorization": "Bearer operator-secret"}

    try:
        assert (
            client.post(
                "/api/v1/phase9/sales-shadow-evaluation/preview",
                headers=viewer,
                json=request.model_dump(mode="json"),
            ).status_code
            == 403
        )
        response = client.post(
            "/api/v1/phase9/sales-shadow-evaluation/preview",
            headers=operator,
            json=request.model_dump(mode="json"),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["evaluation_version"] == "phase-9b-sales-shadow-eval-v1"
        assert body["evaluated_subject_count"] == 3
        assert body["verified_breach_subject_count"] == 1
        assert body["contains_subject_ids"] is False
        assert body["persisted"] is False
        assert body["execution_enabled"] is False
        assert body["customer_contact_enabled"] is False
        assert response.headers["cache-control"] == "no-store"
        serialized = json.dumps(body, ensure_ascii=False)
        assert "lead-001" not in serialized
        assert "lead-002" not in serialized

        # Existing Phase 9A endpoint remains independently available.
        old = client.post(
            "/api/v1/phase9/shadow-evaluation/preview",
            headers=operator,
            json={
                "subject_refs": ["lead:lead-001"],
                "as_of": AS_OF.isoformat(),
            },
        )
        assert old.status_code == 200
        assert old.json()["evaluation_version"] == "phase-9a-shadow-eval-v1"
    finally:
        authorizer.settings = previous_auth
        hub.store = previous_store
        hub.journeys = previous_journeys
        hub.delivery = previous_delivery


def test_sales_shadow_openapi_adds_only_preview_and_no_execution_route():
    paths = app.openapi()["paths"]
    assert paths["/api/v1/phase9/shadow-evaluation/preview"].keys() >= {"post"}
    sales_paths = {
        path: set(operations)
        for path, operations in paths.items()
        if path.startswith("/api/v1/phase9/sales-shadow-evaluation")
    }
    assert sales_paths == {
        "/api/v1/phase9/sales-shadow-evaluation/preview": {"post"},
    }
    forbidden = ("execute", "accept", "send", "contact")
    assert not any(any(word in path for word in forbidden) for path in sales_paths)
