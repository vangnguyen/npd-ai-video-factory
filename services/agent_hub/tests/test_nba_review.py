from __future__ import annotations

from datetime import datetime, timezone

import fakeredis
import pytest
from pydantic import ValidationError

from npd_agent_hub.attribution_models import TouchpointEvent, TouchpointType
from npd_agent_hub.journeys import JourneyService
from npd_agent_hub.nba_review import NBAReviewService
from npd_agent_hub.nba_review_models import (
    NBAReviewCreate,
    NBAReviewDisposition,
    NBAReviewRecord,
)
from npd_agent_hub.nba_review_repository import repository_for_store
from npd_agent_hub.next_best_action_models import RecommendedAction
from npd_agent_hub.store import MemoryHubStore, RedisHubStore


UTC = timezone.utc
CAMPAIGN_ID = "CMP-VGP-VINHTIEN-202609-01"


def seed(store: MemoryHubStore | RedisHubStore) -> None:
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


def test_memory_shadow_reviews_persist_across_service_instances_and_summarize_false_positives():
    store = MemoryHubStore()
    seed(store)
    as_of = datetime(2026, 9, 1, 12, tzinfo=UTC)

    first_service = NBAReviewService(store, JourneyService(store))
    first = first_service.record(
        NBAReviewCreate(
            subject_ref="lead:lead-001",
            disposition=NBAReviewDisposition.RELEVANT,
            note="Recommendation matches the available sales evidence.",
            as_of=as_of,
        ),
        reviewer_role="operator",
    )
    second_service = NBAReviewService(store, JourneyService(store))
    second = second_service.record(
        NBAReviewCreate(
            subject_ref="lead:lead-001",
            disposition=NBAReviewDisposition.NOT_RELEVANT,
            note="Recommendation was too early for the available context.",
            as_of=as_of,
        ),
        reviewer_role="owner",
    )
    summary = second_service.summary(subject_ref="lead:lead-001")

    assert first.review_id != second.review_id
    assert len(second_service.list(subject_ref="lead:lead-001")) == 2
    assert summary.total_reviews == 2
    assert summary.relevant == 1
    assert summary.not_relevant == 1
    assert summary.false_positive_rate == 0.5
    assert second.false_positive is True
    assert second.recommendation_executed is False
    assert second.execution_enabled is False
    assert second.external_writes_enabled is False
    assert second.customer_contact_enabled is False
    assert store.list_recent_tasks(10) == []


def test_redis_repository_recovers_reviews_without_raw_subject_in_index_key():
    client = fakeredis.FakeRedis(decode_responses=True)
    store = RedisHubStore(client=client, namespace="phase9-test")
    record = NBAReviewRecord(
        subject_ref="lead:lead-001",
        recommendation_version="phase-9a-nba-v1",
        recommended_action=RecommendedAction.REVIEW_SALES_FOLLOW_UP,
        recommendation_as_of=datetime(2026, 9, 1, 12, tzinfo=UTC),
        journey_state="lead",
        lead_score=33.33,
        recommendation_confidence=0.55,
        evidence_refs=["tpt_" + "1" * 32],
        disposition=NBAReviewDisposition.NEEDS_MORE_CONTEXT,
        false_positive=False,
        note="Need verified project context before judging relevance.",
        reviewer_role="operator",
    )

    repository_for_store(store).save(record)
    recovered = repository_for_store(store).list(subject_ref="lead:lead-001")
    keys = [str(item) for item in client.scan_iter("phase9-test:phase9-os:nba-review:*")]

    assert recovered == [record]
    assert keys
    assert all("lead-001" not in key for key in keys)
    assert any(":subject:" in key for key in keys)


def test_shadow_review_rejects_viewer_role_and_raw_contact_note():
    store = MemoryHubStore()
    seed(store)
    service = NBAReviewService(store, JourneyService(store))
    request = NBAReviewCreate(
        subject_ref="lead:lead-001",
        disposition=NBAReviewDisposition.RELEVANT,
        as_of=datetime(2026, 9, 1, 12, tzinfo=UTC),
    )

    with pytest.raises(PermissionError, match="operator or owner"):
        service.record(request, reviewer_role="viewer")

    with pytest.raises(ValidationError, match="raw contact data"):
        NBAReviewCreate(
            subject_ref="lead:lead-001",
            disposition=NBAReviewDisposition.NEEDS_MORE_CONTEXT,
            note="Please call user@example.com before reviewing.",
        )
