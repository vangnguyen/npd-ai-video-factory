from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest
from pydantic import ValidationError

from npd_agent_hub.attribution_models import TouchpointEvent, TouchpointType
from npd_agent_hub.journeys import JourneyService
from npd_agent_hub.nba_review import NBAReviewService
from npd_agent_hub.nba_review_models import NBAReviewCreate, NBAReviewDisposition
from npd_agent_hub.phase9_shadow_evaluation import Phase9ShadowEvaluationService
from npd_agent_hub.phase9_shadow_evaluation_models import Phase9ShadowEvaluationRequest
from npd_agent_hub.store import MemoryHubStore


UTC = timezone.utc
CAMPAIGN_ID = "CMP-VGP-VINHTIEN-202609-01"


def event(
    suffix: str,
    event_type: TouchpointType,
    hour: int,
    *,
    lead_id: str,
    source: str,
    stage: str | None = None,
) -> TouchpointEvent:
    metadata = {}
    if stage is not None:
        metadata["journey_evidence"] = {
            "contract_version": "phase-9a-sales-v1",
            "state": stage,
            "source_record_ref": f"stage-ref-{suffix}",
            "external_writes_enabled": False,
        }
    return TouchpointEvent(
        event_id="tpt_" + suffix * 32,
        campaign_id=CAMPAIGN_ID,
        event_type=event_type,
        occurred_at=datetime(2026, 9, 1, hour, tzinfo=UTC),
        source_system=source,
        channel="test",
        lead_id=lead_id,
        metadata=metadata,
    )


def build_store() -> MemoryHubStore:
    store = MemoryHubStore()
    rows = [
        event("1", TouchpointType.LEAD_CREATED, 8, lead_id="lead-001", source="EspoCRM"),
        event("2", TouchpointType.LANDING_VIEW, 9, lead_id="lead-001", source="GA4"),
        event("3", TouchpointType.LEAD_CREATED, 8, lead_id="lead-002", source="EspoCRM"),
        event("4", TouchpointType.LEAD_CREATED, 8, lead_id="lead-003", source="EspoCRM"),
        event(
            "5",
            TouchpointType.OPPORTUNITY_STAGE_CHANGED,
            11,
            lead_id="lead-003",
            source="GA4",
            stage="appointment",
        ),
    ]
    for row in rows:
        store.append_touchpoint(row)
    return store


def test_shadow_evaluation_is_deterministic_aggregate_only_and_non_mutating():
    store = build_store()
    journeys = JourneyService(store)
    reviews = NBAReviewService(store, journeys)
    as_of = datetime(2026, 9, 1, 12, tzinfo=UTC)
    reviews.record(
        NBAReviewCreate(
            subject_ref="lead:lead-001",
            disposition=NBAReviewDisposition.RELEVANT,
            as_of=as_of,
        ),
        reviewer_role="operator",
    )
    reviews.record(
        NBAReviewCreate(
            subject_ref="lead:lead-002",
            disposition=NBAReviewDisposition.NOT_RELEVANT,
            as_of=as_of,
        ),
        reviewer_role="owner",
    )
    request = Phase9ShadowEvaluationRequest(
        subject_refs=[
            "lead:lead-001",
            "lead:lead-002",
            "lead:lead-003",
            "lead:missing",
            "lead:lead-001",
        ],
        as_of=as_of,
    )
    service = Phase9ShadowEvaluationService(store, journeys)
    before_touchpoints = store.list_touchpoints(limit=100)
    before_reviews = reviews.summary()

    first = service.evaluate(request)
    second = service.evaluate(request)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.requested_subject_count == 5
    assert first.unique_subject_count == 4
    assert first.duplicate_subject_count == 1
    assert first.evaluated_subject_count == 3
    assert first.failed_subject_count == 1
    assert first.failure_counts == {"not_found": 1}
    assert first.journey_state_counts == {"engaged": 1, "lead": 2}
    assert first.score_band_counts == {"low_0_49": 3}
    assert first.recommendation_action_counts == {"review_sales_follow_up": 3}
    assert first.recommendation_priority_counts == {"low": 3}
    assert first.average_lead_score == 36.89
    assert first.average_recommendation_confidence == 0.56
    assert first.subjects_with_untrusted_evidence == 1
    assert first.missing_input_counts == {
        "budget_fit": 3,
        "engagement_frequency": 2,
        "project_fit": 3,
        "sales_sla": 3,
        "source_quality": 3,
    }
    assert first.review_aggregate.total_reviews == 2
    assert first.review_aggregate.relevant == 1
    assert first.review_aggregate.not_relevant == 1
    assert first.review_aggregate.false_positive_rate == 0.5
    assert first.aggregate_only is True
    assert first.contains_subject_ids is False
    assert first.persisted is False
    assert first.execution_enabled is False
    assert first.external_writes_enabled is False
    assert first.customer_contact_enabled is False
    assert first.contains_raw_pii is False

    serialized = json.dumps(first.model_dump(mode="json"), ensure_ascii=False)
    assert "lead-001" not in serialized
    assert "lead-002" not in serialized
    assert "lead-003" not in serialized
    assert "lead:missing" not in serialized
    assert store.list_touchpoints(limit=100) == before_touchpoints
    assert reviews.summary() == before_reviews
    assert store.list_recent_tasks(10) == []


def test_shadow_evaluation_request_rejects_raw_contact_and_naive_time():
    with pytest.raises(ValidationError, match="raw contact data"):
        Phase9ShadowEvaluationRequest(
            subject_refs=["lead:user@example.com"],
            as_of=datetime(2026, 9, 1, 12, tzinfo=UTC),
        )

    with pytest.raises(ValidationError, match="timezone-aware"):
        Phase9ShadowEvaluationRequest(
            subject_refs=["lead:lead-001"],
            as_of=datetime(2026, 9, 1, 12),
        )


def test_all_failed_subjects_still_return_aggregate_failure_categories_only():
    store = MemoryHubStore()
    service = Phase9ShadowEvaluationService(store, JourneyService(store))
    result = service.evaluate(
        Phase9ShadowEvaluationRequest(
            subject_refs=["lead:missing-1", "opportunity:missing-2"],
            as_of=datetime(2026, 9, 1, 12, tzinfo=UTC),
        )
    )

    assert result.evaluated_subject_count == 0
    assert result.failed_subject_count == 2
    assert result.failure_counts == {"not_found": 2}
    assert result.journey_state_counts == {}
    assert result.score_band_counts == {}
    assert result.average_lead_score is None
    assert result.average_recommendation_confidence is None
    serialized = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
    assert "missing-1" not in serialized
    assert "missing-2" not in serialized
