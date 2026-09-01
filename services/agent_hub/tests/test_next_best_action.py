from __future__ import annotations

from datetime import datetime, timezone

from npd_agent_hub.attribution_models import TouchpointEvent, TouchpointType
from npd_agent_hub.journeys import JourneyService
from npd_agent_hub.next_best_action import NextBestActionService
from npd_agent_hub.next_best_action_models import (
    RecommendationChannel,
    RecommendationPriority,
    RecommendedAction,
)
from npd_agent_hub.store import MemoryHubStore


UTC = timezone.utc
CAMPAIGN_ID = "CMP-VGP-VINHTIEN-202609-01"


def touch(
    suffix: str,
    event_type: TouchpointType,
    hour: int,
    *,
    source: str,
    stage: str | None = None,
) -> TouchpointEvent:
    metadata = {}
    if stage is not None:
        metadata["journey_evidence"] = {
            "contract_version": "phase-9a-sales-v1",
            "state": stage,
            "source_record_ref": f"ref-{suffix}",
            "external_writes_enabled": False,
        }
    return TouchpointEvent(
        event_id="tpt_" + suffix * 32,
        campaign_id=CAMPAIGN_ID,
        event_type=event_type,
        occurred_at=datetime(2026, 9, 1, hour, tzinfo=UTC),
        source_system=source,
        channel="test",
        lead_id="lead-001",
        opportunity_id="opp-001",
        metadata=metadata,
    )


def nba_with(*rows: TouchpointEvent) -> NextBestActionService:
    store = MemoryHubStore()
    for row in rows:
        store.append_touchpoint(row)
    return NextBestActionService(JourneyService(store))


def test_appointment_recommendation_is_high_priority_internal_review_not_execution():
    service = nba_with(
        touch("1", TouchpointType.LEAD_CREATED, 8, source="EspoCRM"),
        touch("2", TouchpointType.OPPORTUNITY_CREATED, 9, source="EspoCRM"),
        touch(
            "3",
            TouchpointType.OPPORTUNITY_STAGE_CHANGED,
            10,
            source="NPD Sales Hub",
            stage="appointment",
        ),
    )
    as_of = datetime(2026, 9, 1, 12, tzinfo=UTC)

    result = service.recommend("lead:lead-001", as_of=as_of)

    assert result.recommended_action == RecommendedAction.REVIEW_APPOINTMENT_PREPARATION
    assert result.priority == RecommendationPriority.HIGH
    assert result.sla_minutes == 30
    assert result.sla_scope == "internal_review_only"
    assert result.channel == RecommendationChannel.SALES_TASK_REVIEW
    assert result.campaign_id == CAMPAIGN_ID
    assert result.project is None
    assert "project_context" in result.missing_context
    assert result.execution_enabled is False
    assert result.external_writes_enabled is False
    assert result.customer_contact_enabled is False
    assert result.contains_raw_pii is False
    assert "no customer-facing action is executed" in result.reason


def test_lost_state_recommends_internal_reason_review_not_customer_contact():
    service = nba_with(
        touch("4", TouchpointType.OPPORTUNITY_CREATED, 8, source="EspoCRM"),
        touch(
            "5",
            TouchpointType.OPPORTUNITY_STAGE_CHANGED,
            10,
            source="EspoCRM",
            stage="lost",
        ),
    )

    result = service.recommend(
        "opportunity:opp-001",
        as_of=datetime(2026, 9, 1, 11, tzinfo=UTC),
    )

    assert result.recommended_action == RecommendedAction.REVIEW_LOST_REASON
    assert result.priority == RecommendationPriority.MEDIUM
    assert result.channel == RecommendationChannel.INTERNAL_REVIEW
    assert result.customer_contact_enabled is False


def test_early_journey_follow_up_priority_is_score_bounded():
    low = nba_with(
        touch("6", TouchpointType.LEAD_CREATED, 8, source="EspoCRM")
    ).recommend(
        "lead:lead-001",
        as_of=datetime(2026, 9, 10, 8, tzinfo=UTC),
    )

    assert low.recommended_action == RecommendedAction.REVIEW_SALES_FOLLOW_UP
    assert low.priority == RecommendationPriority.LOW
    assert low.sla_minutes == 1440


def test_recommendation_is_deterministic_for_same_evidence_and_as_of():
    service = nba_with(
        touch("7", TouchpointType.LEAD_CREATED, 8, source="EspoCRM"),
        touch("8", TouchpointType.LANDING_VIEW, 9, source="GA4"),
    )
    as_of = datetime(2026, 9, 1, 12, tzinfo=UTC)

    first = service.recommend("lead:lead-001", as_of=as_of)
    second = service.recommend("lead:lead-001", as_of=as_of)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.recommendation_version == "phase-9a-nba-v1"
    assert first.confidence <= 0.70
