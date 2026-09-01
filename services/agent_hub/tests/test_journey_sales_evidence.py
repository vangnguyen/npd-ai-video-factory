from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from npd_agent_hub.attribution_models import TouchpointEvent, TouchpointType
from npd_agent_hub.journey_models import (
    JourneyEvidenceAuthority,
    JourneyStageEvidence,
    JourneyState,
)
from npd_agent_hub.journeys import JourneyService
from npd_agent_hub.store import MemoryHubStore


UTC = timezone.utc
CAMPAIGN_ID = "CMP-VGP-VINHTIEN-202609-01"


def touch(
    suffix: str,
    event_type: TouchpointType,
    hour: int,
    *,
    source: str,
    state: str | None = None,
    lead_id: str = "lead-001",
    opportunity_id: str | None = "opp-001",
) -> TouchpointEvent:
    metadata = {}
    if state is not None:
        metadata["journey_evidence"] = {
            "contract_version": "phase-9a-sales-v1",
            "state": state,
            "source_record_ref": f"sales-record-{suffix}",
            "external_writes_enabled": False,
        }
    return TouchpointEvent(
        event_id="tpt_" + suffix * 32,
        campaign_id=CAMPAIGN_ID,
        event_type=event_type,
        occurred_at=datetime(2026, 9, 1, hour, tzinfo=UTC),
        source_system=source,
        channel="sales",
        lead_id=lead_id,
        opportunity_id=opportunity_id,
        metadata=metadata,
    )


def test_sales_hub_and_espocrm_evidence_advances_only_declared_authoritative_states():
    store = MemoryHubStore()
    rows = [
        touch("1", TouchpointType.LEAD_CREATED, 8, source="EspoCRM", state=None),
        touch("2", TouchpointType.OPPORTUNITY_CREATED, 9, source="EspoCRM", state=None),
        touch("3", TouchpointType.OPPORTUNITY_STAGE_CHANGED, 10, source="NPD Sales Hub", state="appointment"),
        touch("4", TouchpointType.OPPORTUNITY_STAGE_CHANGED, 11, source="SaleHub", state="site_visit"),
        touch("5", TouchpointType.OPPORTUNITY_STAGE_CHANGED, 12, source="EspoCRM", state="lost"),
        touch("6", TouchpointType.OPPORTUNITY_STAGE_CHANGED, 13, source="Sales Hub", state="reengagement"),
    ]
    for row in rows:
        store.append_touchpoint(row)

    projection = JourneyService(store).project("lead:lead-001")

    assert [item.new_state for item in projection.transitions] == [
        JourneyState.LEAD,
        JourneyState.SQL,
        JourneyState.APPOINTMENT,
        JourneyState.SITE_VISIT,
        JourneyState.LOST,
        JourneyState.REENGAGEMENT,
    ]
    assert projection.current_state == JourneyState.REENGAGEMENT
    assert projection.untrusted_evidence_count == 0
    assert projection.transitions[4].skipped_states == [JourneyState.NEGOTIATION]
    assert all(
        item.authority_status == JourneyEvidenceAuthority.ACCEPTED
        for item in projection.evidence[2:]
    )
    assert projection.execution_enabled is False
    assert projection.external_writes_enabled is False


def test_customer_confirmation_requires_espocrm_and_can_follow_won():
    store = MemoryHubStore()
    store.append_touchpoint(
        touch("7", TouchpointType.LEAD_CREATED, 8, source="EspoCRM", state=None)
    )
    store.append_touchpoint(
        touch("8", TouchpointType.SALE_CLOSED, 10, source="EspoCRM", state=None)
    )
    store.append_touchpoint(
        touch("9", TouchpointType.SALE_CLOSED, 11, source="EspoCRM", state="customer")
    )

    projection = JourneyService(store).project("opportunity:opp-001")

    assert projection.current_state == JourneyState.CUSTOMER
    assert [item.new_state for item in projection.transitions][-2:] == [
        JourneyState.WON,
        JourneyState.CUSTOMER,
    ]
    assert projection.evidence[-1].authority_status == JourneyEvidenceAuthority.ACCEPTED


def test_untrusted_marketing_source_cannot_fake_appointment_or_fall_back_to_negotiation():
    store = MemoryHubStore()
    store.append_touchpoint(
        touch("a", TouchpointType.LEAD_CREATED, 8, source="EspoCRM", state=None)
    )
    store.append_touchpoint(
        touch("b", TouchpointType.OPPORTUNITY_STAGE_CHANGED, 9, source="GA4", state="appointment")
    )

    projection = JourneyService(store).project("lead:lead-001")

    assert projection.current_state == JourneyState.LEAD
    assert projection.transition_count == 1
    assert projection.suppressed_transition_count == 1
    assert projection.untrusted_evidence_count == 1
    assert projection.data_quality == "observed_with_untrusted_evidence"
    assert projection.evidence[-1].declared_state == JourneyState.APPOINTMENT
    assert projection.evidence[-1].authority_status == JourneyEvidenceAuthority.REJECTED_SOURCE


def test_invalid_contract_is_retained_but_cannot_change_state():
    store = MemoryHubStore()
    invalid = touch(
        "c",
        TouchpointType.OPPORTUNITY_STAGE_CHANGED,
        9,
        source="EspoCRM",
        state=None,
    )
    invalid = invalid.model_copy(
        update={
            "metadata": {
                "journey_evidence": {
                    "contract_version": "future-unsafe-version",
                    "state": "customer",
                    "source_record_ref": "record-c",
                }
            }
        }
    )
    store.append_touchpoint(invalid)

    projection = JourneyService(store).project("lead:lead-001")

    assert projection.current_state == JourneyState.ANONYMOUS
    assert projection.transition_count == 0
    assert projection.suppressed_transition_count == 1
    assert projection.untrusted_evidence_count == 1
    assert projection.evidence[0].authority_status == JourneyEvidenceAuthority.INVALID_CONTRACT


def test_won_or_customer_cannot_regress_to_lost():
    store = MemoryHubStore()
    store.append_touchpoint(
        touch("d", TouchpointType.SALE_CLOSED, 10, source="EspoCRM", state=None)
    )
    store.append_touchpoint(
        touch("e", TouchpointType.OPPORTUNITY_STAGE_CHANGED, 11, source="EspoCRM", state="lost")
    )

    projection = JourneyService(store).project("opportunity:opp-001")

    assert projection.current_state == JourneyState.WON
    assert projection.suppressed_transition_count == 1
    assert projection.evidence[-1].authority_status == JourneyEvidenceAuthority.ACCEPTED


def test_stage_contract_rejects_write_flags_and_raw_contact_reference():
    with pytest.raises(ValidationError, match="cannot enable external writes"):
        JourneyStageEvidence(
            state=JourneyState.APPOINTMENT,
            source_record_ref="appt-001",
            external_writes_enabled=True,
        )

    with pytest.raises(ValidationError, match="raw contact data"):
        JourneyStageEvidence(
            state=JourneyState.APPOINTMENT,
            source_record_ref="user@example.com",
        )
