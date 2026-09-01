from __future__ import annotations

from datetime import datetime, timezone

import pytest

from npd_agent_hub.attribution_models import TouchpointEvent, TouchpointType
from npd_agent_hub.journey_models import JourneyState
from npd_agent_hub.journeys import JourneyService
from npd_agent_hub.store import MemoryHubStore


UTC = timezone.utc
CAMPAIGN_ID = "CMP-VGP-VINHTIEN-202609-01"


def event(
    *,
    event_id: str,
    event_type: TouchpointType,
    hour: int,
    lead_id: str = "lead-001",
    opportunity_id: str | None = None,
    source_system: str = "test-source",
) -> TouchpointEvent:
    return TouchpointEvent(
        event_id=event_id,
        campaign_id=CAMPAIGN_ID,
        event_type=event_type,
        occurred_at=datetime(2026, 9, 1, hour, tzinfo=UTC),
        source_system=source_system,
        channel="test-channel",
        lead_id=lead_id,
        opportunity_id=opportunity_id,
        ingested_at=datetime(2026, 9, 2, hour, tzinfo=UTC),
    )


def test_journey_replay_is_deterministic_and_explainable():
    store = MemoryHubStore()
    rows = [
        event(event_id="tpt_" + "4" * 32, event_type=TouchpointType.SALE_CLOSED, hour=14, opportunity_id="opp-001"),
        event(event_id="tpt_" + "1" * 32, event_type=TouchpointType.LEAD_CREATED, hour=9),
        event(event_id="tpt_" + "3" * 32, event_type=TouchpointType.OPPORTUNITY_CREATED, hour=12, opportunity_id="opp-001"),
        event(event_id="tpt_" + "2" * 32, event_type=TouchpointType.LANDING_VIEW, hour=10),
    ]
    for row in rows:
        store.append_touchpoint(row)

    projection = JourneyService(store).project("lead:lead-001")

    assert projection.current_state == JourneyState.WON
    assert [item.new_state for item in projection.transitions] == [
        JourneyState.LEAD,
        JourneyState.ENGAGED,
        JourneyState.SQL,
        JourneyState.WON,
    ]
    assert [item.evidence_event_id for item in projection.transitions] == [
        "tpt_" + "1" * 32,
        "tpt_" + "2" * 32,
        "tpt_" + "3" * 32,
        "tpt_" + "4" * 32,
    ]
    assert JourneyState.MQL in projection.transitions[2].skipped_states
    assert JourneyState.NEGOTIATION in projection.transitions[3].skipped_states
    assert projection.execution_enabled is False
    assert projection.external_writes_enabled is False
    assert projection.contains_raw_pii is False
    assert projection.shadow_mode is True


def test_prelead_engagement_is_retained_as_evidence_without_inventing_a_lead_transition():
    store = MemoryHubStore()
    store.append_touchpoint(
        event(event_id="tpt_" + "a" * 32, event_type=TouchpointType.AD_CLICK, hour=8)
    )
    store.append_touchpoint(
        event(event_id="tpt_" + "b" * 32, event_type=TouchpointType.LEAD_CREATED, hour=9)
    )

    projection = JourneyService(store).project("lead:lead-001")

    assert projection.evidence_count == 2
    assert projection.transition_count == 1
    assert projection.current_state == JourneyState.LEAD
    assert projection.transitions[0].new_state == JourneyState.LEAD


def test_repeated_or_late_lower_state_evidence_never_regresses_the_projection():
    store = MemoryHubStore()
    store.append_touchpoint(
        event(event_id="tpt_" + "c" * 32, event_type=TouchpointType.OPPORTUNITY_CREATED, hour=10, opportunity_id="opp-001")
    )
    store.append_touchpoint(
        event(event_id="tpt_" + "d" * 32, event_type=TouchpointType.LEAD_CREATED, hour=11, opportunity_id="opp-001")
    )

    projection = JourneyService(store).project("opportunity:opp-001")

    assert projection.current_state == JourneyState.SQL
    assert projection.transition_count == 1
    assert projection.suppressed_transition_count == 1
    assert projection.transitions[0].previous_state == JourneyState.ANONYMOUS
    assert projection.transitions[0].new_state == JourneyState.SQL


def test_subject_reference_is_pseudonymous_and_fail_closed():
    service = JourneyService(MemoryHubStore())

    with pytest.raises(ValueError, match="lead:<id>"):
        service.project("customer:abc")
    with pytest.raises(ValueError, match="raw contact data"):
        service.project("lead:user@example.com")
    with pytest.raises(KeyError):
        service.project("lead:missing")
