from __future__ import annotations

from .journey_models import JourneyEvidenceAuthority, JourneyState
from .journeys import JourneyService
from .lead_scoring_models import ExplainableLeadScore
from .next_best_action import NextBestActionService
from .next_best_action_models import (
    NextBestActionRecommendation,
    RecommendationChannel,
    RecommendationPriority,
    RecommendedAction,
)
from .sales_intelligence_models import SalesIntelligenceSnapshot, SalesSLAStatus


TRUSTED_AUTHORITY = {
    JourneyEvidenceAuthority.NOT_REQUIRED,
    JourneyEvidenceAuthority.ACCEPTED,
}
EARLY_SALES_STATES = {
    JourneyState.LEAD,
    JourneyState.ENGAGED,
    JourneyState.MQL,
    JourneyState.SQL,
}
PRIORITY_RANK = {
    RecommendationPriority.LOW: 0,
    RecommendationPriority.MEDIUM: 1,
    RecommendationPriority.HIGH: 2,
}


class SalesAwareNextBestActionService:
    """Recommendation-only NBA policy over Journey + signed SLA-aware Lead Score."""

    def __init__(self, journeys: JourneyService):
        self.journeys = journeys

    @staticmethod
    def _at_least(
        current: RecommendationPriority,
        target: RecommendationPriority,
    ) -> RecommendationPriority:
        return target if PRIORITY_RANK[target] > PRIORITY_RANK[current] else current

    def recommend(
        self,
        subject_ref: str,
        *,
        sales_intelligence: SalesIntelligenceSnapshot,
        lead_score: ExplainableLeadScore,
    ) -> NextBestActionRecommendation:
        if sales_intelligence.subject_ref != subject_ref or lead_score.subject_ref != subject_ref:
            raise ValueError("Sales Intelligence, Lead Score and NBA subjects must match")
        if sales_intelligence.as_of != lead_score.as_of:
            raise ValueError("Sales Intelligence and Lead Score as_of timestamps must match")
        if lead_score.score_version != "phase-9b-score-v2":
            raise ValueError("SLA-aware NBA requires Phase 9B Lead Score v2")

        projection = self.journeys.project(subject_ref)
        action, priority, sla_minutes, channel = NextBestActionService._rule(
            projection.current_state,
            lead_score.score,
        )

        sla_escalation = "none"
        if sales_intelligence.completeness_verified and projection.current_state in EARLY_SALES_STATES:
            statuses = {
                sales_intelligence.first_response_sla.status,
                sales_intelligence.visit_booking_sla.status,
            }
            if SalesSLAStatus.BREACHED in statuses:
                action = RecommendedAction.REVIEW_SALES_FOLLOW_UP
                priority = RecommendationPriority.HIGH
                sla_minutes = min(sla_minutes, 15)
                channel = RecommendationChannel.SALES_TASK_REVIEW
                sla_escalation = "verified_breach"
            elif SalesSLAStatus.LATE in statuses:
                action = RecommendedAction.REVIEW_SALES_FOLLOW_UP
                priority = self._at_least(priority, RecommendationPriority.MEDIUM)
                sla_minutes = min(sla_minutes, 60)
                channel = RecommendationChannel.SALES_TASK_REVIEW
                sla_escalation = "verified_late"

        trusted = [
            item for item in projection.evidence if item.authority_status in TRUSTED_AUTHORITY
        ]
        if not trusted:
            raise ValueError("SLA-aware NBA requires at least one trusted journey evidence record")
        latest_trusted = max(trusted, key=lambda item: (item.occurred_at, item.event_id))

        evidence_refs: list[str] = []
        for factor in lead_score.factors:
            for evidence_ref in factor.evidence_refs:
                if evidence_ref not in evidence_refs:
                    evidence_refs.append(evidence_ref)
        if latest_trusted.event_id not in evidence_refs:
            evidence_refs.append(latest_trusted.event_id)

        missing_context = list(lead_score.missing_inputs)
        project = sales_intelligence.project
        if project is None and "project_context" not in missing_context:
            missing_context.append("project_context")

        confidence = lead_score.confidence
        if project is None:
            confidence = min(confidence, 0.70)
        confidence = round(confidence, 2)

        if sla_escalation == "verified_breach":
            sla_reason = (
                "A signed Sales Hub completeness proof confirms at least one missed Sales SLA; "
                "the recommendation is escalated only for internal sales review."
            )
        elif sla_escalation == "verified_late":
            sla_reason = (
                "Signed Sales Hub activity proves at least one late Sales SLA; "
                "the recommendation is raised to at least medium internal-review priority."
            )
        elif sales_intelligence.completeness_verified:
            sla_reason = (
                "Verified signed Sales SLA context was included, with no separate breach/late escalation required."
            )
        else:
            sla_reason = (
                "Sales SLA completeness is absent or invalid, so SLA state does not escalate this recommendation."
            )

        reason = (
            f"Journey state is {projection.current_state.value}; signed-context Lead Score v2 is "
            f"{lead_score.score:.2f}/100. {sla_reason} No customer-facing action is executed."
        )

        return NextBestActionRecommendation(
            subject_ref=subject_ref,
            recommendation_version="phase-9b-nba-v2",
            recommended_action=action,
            reason=reason,
            priority=priority,
            sla_minutes=sla_minutes,
            channel=channel,
            campaign_id=sales_intelligence.campaign_id or latest_trusted.campaign_id,
            project=project,
            journey_state=projection.current_state,
            lead_score=lead_score.score,
            confidence=confidence,
            evidence_refs=evidence_refs,
            missing_context=missing_context,
            as_of=lead_score.as_of,
        )
