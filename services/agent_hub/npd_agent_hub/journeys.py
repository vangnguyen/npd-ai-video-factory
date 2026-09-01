from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import ValidationError

from .attribution_models import TouchpointEvent, TouchpointType, assert_pseudonymous_reference
from .journey_models import (
    JourneyEvidence,
    JourneyEvidenceAuthority,
    JourneyProjection,
    JourneyStageEvidence,
    JourneyState,
    JourneyTransition,
)
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
SALES_EVIDENCE_EVENT_TYPES = {
    TouchpointType.OPPORTUNITY_STAGE_CHANGED,
    TouchpointType.SALE_CLOSED,
}
ESPOCRM_SOURCES = {"espocrm", "espo crm"}
SALES_HUB_SOURCES = {"sales hub", "salehub", "npd sales hub"}
SOURCE_POLICY: dict[JourneyState, set[str]] = {
    JourneyState.MQL: ESPOCRM_SOURCES | SALES_HUB_SOURCES,
    JourneyState.APPOINTMENT: ESPOCRM_SOURCES | SALES_HUB_SOURCES,
    JourneyState.SITE_VISIT: ESPOCRM_SOURCES | SALES_HUB_SOURCES,
    JourneyState.LOST: ESPOCRM_SOURCES,
    JourneyState.CUSTOMER: ESPOCRM_SOURCES,
    JourneyState.REENGAGEMENT: ESPOCRM_SOURCES | SALES_HUB_SOURCES,
}


@dataclass(frozen=True)
class ParsedSubjectRef:
    kind: str
    identifier: str


@dataclass(frozen=True)
class EvidenceAssessment:
    stage: JourneyStageEvidence | None
    authority_status: JourneyEvidenceAuthority
    detail: str | None = None


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
        kwargs = (
            {"lead_id": parsed.identifier}
            if parsed.kind == "lead"
            else {"opportunity_id": parsed.identifier}
        )
        rows = self.store.list_touchpoints(limit=5000, **kwargs)
        return sorted(rows, key=lambda item: (item.occurred_at, item.event_id))

    @staticmethod
    def _normalize_source(value: str) -> str:
        normalized = re.sub(r"[_-]+", " ", value.strip().lower())
        return re.sub(r"\s+", " ", normalized)

    @classmethod
    def _assess_stage_evidence(cls, event: TouchpointEvent) -> EvidenceAssessment:
        raw = event.metadata.get("journey_evidence")
        if raw is None:
            return EvidenceAssessment(None, JourneyEvidenceAuthority.NOT_REQUIRED)
        if event.event_type not in SALES_EVIDENCE_EVENT_TYPES:
            return EvidenceAssessment(
                None,
                JourneyEvidenceAuthority.INVALID_CONTRACT,
                "journey_evidence is allowed only on opportunity stage or sale-close events",
            )
        if not isinstance(raw, dict):
            return EvidenceAssessment(
                None,
                JourneyEvidenceAuthority.INVALID_CONTRACT,
                "journey_evidence must be an object",
            )
        try:
            stage = JourneyStageEvidence.model_validate(raw)
        except ValidationError:
            return EvidenceAssessment(
                None,
                JourneyEvidenceAuthority.INVALID_CONTRACT,
                "journey_evidence failed the Phase 9A versioned contract",
            )
        source = cls._normalize_source(event.source_system)
        if source not in SOURCE_POLICY[stage.state]:
            return EvidenceAssessment(
                stage,
                JourneyEvidenceAuthority.REJECTED_SOURCE,
                f"{stage.state.value} requires an authoritative Sales Hub/EspoCRM source",
            )
        return EvidenceAssessment(
            stage,
            JourneyEvidenceAuthority.ACCEPTED,
            "versioned journey evidence accepted from an authoritative source",
        )

    @staticmethod
    def _target_for_event(
        event: TouchpointEvent,
        current_state: JourneyState,
        assessment: EvidenceAssessment,
    ) -> tuple[JourneyState, str, float] | None:
        if assessment.authority_status in {
            JourneyEvidenceAuthority.REJECTED_SOURCE,
            JourneyEvidenceAuthority.INVALID_CONTRACT,
        }:
            return None
        if assessment.stage is not None:
            return (
                assessment.stage.state,
                "Authoritative versioned sales evidence declared the next journey state.",
                1.0,
            )
        direct = DIRECT_TARGETS.get(event.event_type)
        if direct is not None:
            return direct
        if (
            event.event_type in ENGAGEMENT_TYPES
            and current_state in STATE_RANK
            and STATE_RANK[current_state] >= STATE_RANK[JourneyState.LEAD]
        ):
            return (
                JourneyState.ENGAGED,
                "Observed engagement occurred after lead evidence and therefore advances the subject to engaged.",
                0.8,
            )
        return None

    @staticmethod
    def _skipped_linear_states(
        previous: JourneyState,
        target: JourneyState,
    ) -> list[JourneyState]:
        previous_rank = STATE_RANK.get(previous)
        target_rank = STATE_RANK.get(target)
        if previous_rank is None or target_rank is None or target_rank <= previous_rank + 1:
            return []
        return STATE_SEQUENCE[previous_rank + 1 : target_rank]

    @staticmethod
    def _transition_allowed(previous: JourneyState, target: JourneyState) -> bool:
        if target == JourneyState.REENGAGEMENT:
            return previous in {JourneyState.LOST, JourneyState.CUSTOMER}
        if target == JourneyState.LOST:
            return previous not in {
                JourneyState.LOST,
                JourneyState.WON,
                JourneyState.CUSTOMER,
                JourneyState.REENGAGEMENT,
            }
        if previous in {JourneyState.LOST, JourneyState.REENGAGEMENT}:
            return False
        previous_rank = STATE_RANK.get(previous)
        target_rank = STATE_RANK.get(target)
        return (
            previous_rank is not None
            and target_rank is not None
            and target_rank > previous_rank
        )

    @staticmethod
    def _skipped_states(previous: JourneyState, target: JourneyState) -> list[JourneyState]:
        if target == JourneyState.LOST:
            previous_rank = STATE_RANK.get(previous)
            if previous_rank is None:
                return []
            negotiation_rank = STATE_RANK[JourneyState.NEGOTIATION]
            if previous_rank >= negotiation_rank:
                return []
            return STATE_SEQUENCE[previous_rank + 1 : negotiation_rank + 1]
        if target == JourneyState.REENGAGEMENT:
            return []
        return JourneyService._skipped_linear_states(previous, target)

    def project(self, subject_ref: str) -> JourneyProjection:
        events = self._events(subject_ref)
        if not events:
            raise KeyError(subject_ref)

        assessments = {
            event.event_id: self._assess_stage_evidence(event) for event in events
        }
        evidence = [
            JourneyEvidence(
                event_id=event.event_id,
                event_type=event.event_type,
                occurred_at=event.occurred_at,
                observed_at=event.ingested_at,
                source_system=event.source_system,
                channel=event.channel,
                campaign_id=event.campaign_id,
                declared_state=(
                    assessments[event.event_id].stage.state
                    if assessments[event.event_id].stage is not None
                    else None
                ),
                authority_status=assessments[event.event_id].authority_status,
                authority_detail=assessments[event.event_id].detail,
            )
            for event in events
        ]

        current = JourneyState.ANONYMOUS
        transitions: list[JourneyTransition] = []
        suppressed = 0
        for event in events:
            assessment = assessments[event.event_id]
            target_info = self._target_for_event(event, current, assessment)
            if target_info is None:
                if assessment.authority_status in {
                    JourneyEvidenceAuthority.REJECTED_SOURCE,
                    JourneyEvidenceAuthority.INVALID_CONTRACT,
                }:
                    suppressed += 1
                continue
            target, reason, confidence = target_info
            if not self._transition_allowed(current, target):
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
        skipped_states = {
            state for transition in transitions for state in transition.skipped_states
        }
        missing_signals = [
            state
            for state in STATE_SEQUENCE[1:]
            if state in skipped_states and state not in observed_states
        ]
        untrusted = sum(
            item.authority_status
            in {
                JourneyEvidenceAuthority.REJECTED_SOURCE,
                JourneyEvidenceAuthority.INVALID_CONTRACT,
            }
            for item in evidence
        )
        if untrusted:
            data_quality = "observed_with_untrusted_evidence"
        else:
            data_quality = "observed" if transitions else "evidence_only"

        return JourneyProjection(
            subject_ref=subject_ref,
            current_state=current,
            evidence_count=len(evidence),
            transition_count=len(transitions),
            suppressed_transition_count=suppressed,
            untrusted_evidence_count=untrusted,
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
