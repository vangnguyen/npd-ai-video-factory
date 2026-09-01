from __future__ import annotations

from datetime import datetime

from .journey_models import JourneyEvidenceAuthority, JourneyState
from .journeys import JourneyService
from .lead_scoring import LeadScoringService
from .next_best_action_models import (
    NextBestActionRecommendation,
    RecommendationChannel,
    RecommendationPriority,
    RecommendedAction,
)


TRUSTED_AUTHORITY = {
    JourneyEvidenceAuthority.NOT_REQUIRED,
    JourneyEvidenceAuthority.ACCEPTED,
}


class NextBestActionService:
    """Deterministic recommendation-only policy over journey + explainable score."""

    def __init__(self, journeys: JourneyService):
        self.journeys = journeys
        self.scoring = LeadScoringService(journeys)

    @staticmethod
    def _rule(
        state: JourneyState,
        score: float,
    ) -> tuple[RecommendedAction, RecommendationPriority, int, RecommendationChannel]:
        if state == JourneyState.ANONYMOUS:
            return (
                RecommendedAction.COLLECT_MORE_EVIDENCE,
                RecommendationPriority.LOW,
                1440,
                RecommendationChannel.INTERNAL_REVIEW,
            )
        if state in {
            JourneyState.LEAD,
            JourneyState.ENGAGED,
            JourneyState.MQL,
            JourneyState.SQL,
        }:
            if score >= 70:
                priority, sla = RecommendationPriority.HIGH, 30
            elif score >= 50:
                priority, sla = RecommendationPriority.MEDIUM, 120
            else:
                priority, sla = RecommendationPriority.LOW, 1440
            return (
                RecommendedAction.REVIEW_SALES_FOLLOW_UP,
                priority,
                sla,
                RecommendationChannel.SALES_TASK_REVIEW,
            )
        if state == JourneyState.APPOINTMENT:
            return (
                RecommendedAction.REVIEW_APPOINTMENT_PREPARATION,
                RecommendationPriority.HIGH,
                30,
                RecommendationChannel.SALES_TASK_REVIEW,
            )
        if state == JourneyState.SITE_VISIT:
            return (
                RecommendedAction.REVIEW_POST_VISIT_FOLLOW_UP,
                RecommendationPriority.HIGH,
                30,
                RecommendationChannel.SALES_TASK_REVIEW,
            )
        if state == JourneyState.NEGOTIATION:
            return (
                RecommendedAction.REVIEW_NEGOTIATION_NEXT_STEP,
                RecommendationPriority.HIGH,
                30,
                RecommendationChannel.SALES_TASK_REVIEW,
            )
        if state == JourneyState.WON:
            return (
                RecommendedAction.REVIEW_CUSTOMER_HANDOFF,
                RecommendationPriority.MEDIUM,
                240,
                RecommendationChannel.SALES_TASK_REVIEW,
            )
        if state == JourneyState.CUSTOMER:
            return (
                RecommendedAction.REVIEW_CUSTOMER_CARE,
                RecommendationPriority.LOW,
                1440,
                RecommendationChannel.SALES_TASK_REVIEW,
            )
        if state == JourneyState.LOST:
            return (
                RecommendedAction.REVIEW_LOST_REASON,
                RecommendationPriority.MEDIUM,
                1440,
                RecommendationChannel.INTERNAL_REVIEW,
            )
        if state == JourneyState.REENGAGEMENT:
            return (
                RecommendedAction.REVIEW_REENGAGEMENT,
                RecommendationPriority.MEDIUM if score < 70 else RecommendationPriority.HIGH,
                240 if score < 70 else 60,
                RecommendationChannel.SALES_TASK_REVIEW,
            )
        raise ValueError(f"unsupported journey state: {state.value}")

    def recommend(
        self,
        subject_ref: str,
        *,
        as_of: datetime | None = None,
    ) -> NextBestActionRecommendation:
        projection = self.journeys.project(subject_ref)
        score = self.scoring.score(subject_ref, as_of=as_of)
        action, priority, sla_minutes, channel = self._rule(
            projection.current_state,
            score.score,
        )

        trusted = [
            item for item in projection.evidence if item.authority_status in TRUSTED_AUTHORITY
        ]
        latest_trusted = max(trusted, key=lambda item: (item.occurred_at, item.event_id))
        campaign_id = latest_trusted.campaign_id
        evidence_refs: list[str] = []
        for factor in score.factors:
            for evidence_ref in factor.evidence_refs:
                if evidence_ref not in evidence_refs:
                    evidence_refs.append(evidence_ref)
        if latest_trusted.event_id not in evidence_refs:
            evidence_refs.append(latest_trusted.event_id)

        missing_context = list(score.missing_inputs)
        if "project_context" not in missing_context:
            missing_context.append("project_context")

        confidence = score.confidence
        if "project_context" in missing_context:
            confidence = min(confidence, 0.70)
        confidence = round(confidence, 2)

        reason = (
            f"Journey state is {projection.current_state.value} and the deterministic "
            f"journey-momentum score is {score.score:.2f}/100. Review the recommended "
            "internal sales step using the cited evidence; no customer-facing action is executed."
        )

        return NextBestActionRecommendation(
            subject_ref=subject_ref,
            recommended_action=action,
            reason=reason,
            priority=priority,
            sla_minutes=sla_minutes,
            channel=channel,
            campaign_id=campaign_id,
            project=None,
            journey_state=projection.current_state,
            lead_score=score.score,
            confidence=confidence,
            evidence_refs=evidence_refs,
            missing_context=missing_context,
            as_of=score.as_of,
        )
