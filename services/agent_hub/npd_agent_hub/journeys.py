from __future__ import annotations

from dataclasses import dataclass

from .attribution_models import TouchpointEvent, TouchpointType, assert_pseudonymous_reference
from .journey_models import JourneyEvidence, JourneyProjection, JourneyState, JourneyTransition
from .store import HubStore


STATE_SEQUENCE = [
    JourneyState.ANONYMOUS,
    JourneyState.LEAD,
    JourneyState.ENGAGED,
    JourneyState.MQL,
    JourneyState.SQL,
    JourneyState.APPOINTMENT,
    JourneyState.SITE_VISIT,
    JourneyState.NEGOTIATION,
    JourneyState.WON,
    JourneyState.CUSTOMER,
]
STATE_RANK = {state: index for index, state in enumerate(STATE_SEQUENCE)}


DIRECT_TARGETS: dict[TouchpointType, tuple[JourneyState, str, float]] = {
    TouchpointType.FORM_SUBMIT: (
        JourneyState.LEAD,
        "Form submission is direct evidence that the subject entered the lead journey.",
        0.95,
    ),
    TouchpointType.LEAD_CREATED: (
        JourneyState.LEAD,
        "CRM lead creation is authoritative evidence that the subject became a lead.",
        1.0,
    ),
    TouchpointType.OPPORTUNITY_CREATED: (
        JourneyState.SQL,
        "Opportunity creation is direct evidence that the subject reached the qualified sales journey.",
        1.0,
    ),
    TouchpointType.OPPORTUNITY_STAGE_CHANGED: (
        JourneyState.NEGOTIATION,
        "Opportunity stage evidence advances the subject into the negotiation journey without inferring skipped sales activities.",
        0.95,
    ),
    TouchpointType.SALE_CLOSED: (
        JourneyState.WON,
        "Closed-sale evidence advances the subject to won; customer state still requires separate authoritative evidence.",
        1.0,
    ),
}

ENGAGEMENT_TYPES = {TouchpointType.AD_CLICK, TouchpointType.LANDING_VIEW}


@dataclass(frozen=True)
class ParsedSubjectRef:
    kind: str
    identifier: str


class JourneyService:
    """Phase 9A read-only journey projection over the immutable attribution ledger."""

    def __init__(self, store: HubStore):
        self.store = store

    @staticmethod
    def parse_subject_ref(subject_ref: str) -> ParsedSubjectRef:
        if not isinstance(subject_ref, str) or len(subject_ref) > 120:
            raise ValueError("subject_ref must be a bounded pseudonymous reference")
        kind, separator, identifier = subject_ref.partition(":")
        if separator != ":" or kind not in {"lead", "opportunity"} or not identifier:
            raise ValueError("subject_ref must use lead:<id> or opportunity:<id>")
        if len(identifier) > 100:
            raise ValueError("subject_ref identifier is too long")
        assert_pseudonymous_reference(identifier)
        return ParsedSubjectRef(kind=kind, identifier=identifier)

    def _events(self, subject_ref: str) -> list[TouchpointEvent]:
        parsed = self.parse_subject_ref(subject_ref)
        kwargs = {"lead_id": parsed.identifier} if parsed.kind == "lead" else {"opportunity_id": parsed.identifier}
        rows = self.store.list_touchpoints(limit=5000, **kwargs)
        return sorted(rows, key=lambda item: (item.occurred_at, item.event_id))

    @staticmethod
    def _target_for_event(
        event: TouchpointEvent,
        current_state: JourneyState,
    ) -> tuple[JourneyState, str, float] | None:
        direct = DIRECT_TARGETS.get(event.event_type)
        if direct is not None:
            return direct
        if event.event_type in ENGAGEMENT_TYPES and STATE_RANK[current_state] >= STATE_RANK[JourneyState.LEAD]:
            return (
                JourneyState.ENGAGED,
                "Observed engagement occurred after lead evidence and therefore advances the subject to engaged.",
                0.8,
            )
        return None

    @staticmethod
    def _skipped_states(previous: JourneyState, target: JourneyState) -> list[JourneyState]:
        previous_rank = STATE_RANK.get(previous)
        target_rank = STATE_RANK.get(target)
        if previous_rank is None or target_rank is None or target_rank <= previous_rank + 1:
            return []
        return STATE_SEQUENCE[previous_rank + 1 : target_rank]

    def project(self, subject_ref: str) -> JourneyProjection:
        events = self._events(subject_ref)
        if not events:
            raise KeyError(subject_ref)

        evidence = [
            JourneyEvidence(
                event_id=event.event_id,
                event_type=event.event_type,
                occurred_at=event.occurred_at,
                observed_at=event.ingested_at,
                source_system=event.source_system,
                channel=event.channel,
                campaign_id=event.campaign_id,
            )
            for event in events
        ]

        current = JourneyState.ANONYMOUS
        transitions: list[JourneyTransition] = []
        suppressed = 0
        for event in events:
            target_info = self._target_for_event(event, current)
            if target_info is None:
                continue
            target, reason, confidence = target_info
            current_rank = STATE_RANK.get(current)
            target_rank = STATE_RANK.get(target)
            if current_rank is None or target_rank is None or target_rank <= current_rank:
                suppressed += 1
                continue
            transitions.append(
                JourneyTransition(
                    previous_state=current,
                    new_state=target,
                    occurred_at=event.occurred_at,
                    observed_at=event.ingested_at,
                    evidence_event_id=event.event_id,
                    reason=reason,
                    confidence=confidence,
                    skipped_states=self._skipped_states(current, target),
                )
            )
            current = target

        observed_states = {transition.new_state for transition in transitions}
        missing_signals = [
            state
            for state in STATE_SEQUENCE[1 : STATE_RANK[current] + 1]
            if state not in observed_states and state != current
        ]
        data_quality = "observed" if transitions else "evidence_only"

        return JourneyProjection(
            subject_ref=subject_ref,
            current_state=current,
            evidence_count=len(evidence),
            transition_count=len(transitions),
            suppressed_transition_count=suppressed,
            evidence=evidence,
            transitions=transitions,
            campaign_ids=sorted({event.campaign_id for event in events}),
            source_systems=sorted({event.source_system for event in events}),
            latest_event_at=max(event.occurred_at for event in events),
            missing_signals=missing_signals,
            data_quality=data_quality,
        )

    def history(self, subject_ref: str) -> list[JourneyTransition]:
        return self.project(subject_ref).transitions
