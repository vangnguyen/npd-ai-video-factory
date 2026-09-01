from __future__ import annotations

from datetime import datetime, timezone

from .attribution_models import TouchpointType
from .journey_models import JourneyEvidenceAuthority, JourneyState
from .journeys import JourneyService
from .lead_scoring_models import ExplainableLeadScore, LeadScoreFactor, ScoreFactorStatus
from .sales_intelligence_models import SalesIntelligenceSnapshot, SalesSLAStatus, SalesSLAWindow


STATE_POINTS: dict[JourneyState, float] = {
    JourneyState.ANONYMOUS: 0,
    JourneyState.LEAD: 10,
    JourneyState.ENGAGED: 20,
    JourneyState.MQL: 30,
    JourneyState.SQL: 40,
    JourneyState.APPOINTMENT: 50,
    JourneyState.SITE_VISIT: 58,
    JourneyState.NEGOTIATION: 65,
    JourneyState.WON: 70,
    JourneyState.CUSTOMER: 70,
    JourneyState.LOST: 5,
    JourneyState.REENGAGEMENT: 25,
}
ENGAGEMENT_TYPES = {TouchpointType.AD_CLICK, TouchpointType.LANDING_VIEW}
TRUSTED_AUTHORITY = {
    JourneyEvidenceAuthority.NOT_REQUIRED,
    JourneyEvidenceAuthority.ACCEPTED,
}
SLA_FACTOR_CAPACITY = {
    "first_response_sla": 6.0,
    "visit_booking_sla": 9.0,
}
SLA_LATE_POINTS = {
    "first_response_sla": 2.0,
    "visit_booking_sla": 3.0,
}


class LeadScoringService:
    """Deterministic, explainable journey-momentum score; not a conversion probability."""

    def __init__(self, journeys: JourneyService):
        self.journeys = journeys

    @staticmethod
    def _recency_points(age_hours: float) -> float:
        if age_hours <= 24:
            return 20
        if age_hours <= 72:
            return 16
        if age_hours <= 24 * 7:
            return 12
        if age_hours <= 24 * 30:
            return 6
        return 0

    @staticmethod
    def _engagement_points(count: int) -> float:
        if count >= 3:
            return 10
        if count == 2:
            return 7
        return 4

    @staticmethod
    def _sales_sla_factor(
        *,
        name: str,
        window: SalesSLAWindow,
        sales_intelligence: SalesIntelligenceSnapshot,
    ) -> LeadScoreFactor:
        max_points = SLA_FACTOR_CAPACITY[name]
        if not sales_intelligence.completeness_verified:
            return LeadScoreFactor(
                name=name,
                status=ScoreFactorStatus.MISSING,
                contribution=None,
                max_points=max_points,
                reason=(
                    "Sales SLA evidence is excluded because the Sales Hub activity batch is not bound to a verified signed completeness proof."
                ),
                evidence_refs=[],
            )

        evidence_refs = list(window.evidence_refs)
        if sales_intelligence.completeness_receipt_id:
            evidence_refs.append(sales_intelligence.completeness_receipt_id)
        evidence_refs = list(dict.fromkeys(evidence_refs))

        if window.status == SalesSLAStatus.MET:
            return LeadScoreFactor(
                name=name,
                status=ScoreFactorStatus.OBSERVED,
                contribution=max_points,
                max_points=max_points,
                reason=(
                    "The observed Sales Hub activity met the Campaign OS SLA and is bound to a verified signed activity batch."
                ),
                evidence_refs=evidence_refs,
            )
        if window.status == SalesSLAStatus.LATE:
            return LeadScoreFactor(
                name=name,
                status=ScoreFactorStatus.OBSERVED,
                contribution=SLA_LATE_POINTS[name],
                max_points=max_points,
                reason=(
                    "The observed Sales Hub activity occurred after the Campaign OS SLA and is bound to a verified signed activity batch."
                ),
                evidence_refs=evidence_refs,
            )
        if window.status == SalesSLAStatus.BREACHED:
            return LeadScoreFactor(
                name=name,
                status=ScoreFactorStatus.OBSERVED,
                contribution=0,
                max_points=max_points,
                reason=(
                    "The SLA deadline passed without qualifying activity and a verified signed Sales Hub completeness attestation covers that deadline."
                ),
                evidence_refs=evidence_refs,
            )

        return LeadScoreFactor(
            name=name,
            status=ScoreFactorStatus.MISSING,
            contribution=None,
            max_points=max_points,
            reason=(
                "The SLA state is pending, not evaluable, or overdue without completeness coverage; it is excluded from the score denominator rather than treated as a negative signal."
            ),
            evidence_refs=evidence_refs,
        )

    def score(
        self,
        subject_ref: str,
        *,
        as_of: datetime | None = None,
        sales_intelligence: SalesIntelligenceSnapshot | None = None,
    ) -> ExplainableLeadScore:
        projection = self.journeys.project(subject_ref)
        evaluation_time = as_of or datetime.now(timezone.utc)
        if evaluation_time.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        evaluation_time = evaluation_time.astimezone(timezone.utc)

        if sales_intelligence is not None:
            if sales_intelligence.subject_ref != subject_ref:
                raise ValueError("sales intelligence subject must match lead score subject")
            if sales_intelligence.as_of.astimezone(timezone.utc) != evaluation_time:
                raise ValueError("sales intelligence as_of must match lead score as_of")

        trusted_evidence = [
            item for item in projection.evidence if item.authority_status in TRUSTED_AUTHORITY
        ]
        if not trusted_evidence:
            raise ValueError("lead score requires at least one trusted journey evidence record")

        stage_refs = [
            transition.evidence_event_id for transition in projection.transitions[-1:]
        ]
        stage_factor = LeadScoreFactor(
            name="journey_state",
            status=ScoreFactorStatus.OBSERVED,
            contribution=STATE_POINTS[projection.current_state],
            max_points=70,
            reason=(
                f"Current observed journey state is {projection.current_state.value}; "
                "the contribution uses the fixed Phase 9A state table, not a learned probability."
            ),
            evidence_refs=stage_refs,
        )

        latest_trusted = max(trusted_evidence, key=lambda item: (item.occurred_at, item.event_id))
        latest = latest_trusted.occurred_at
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=timezone.utc)
        age_hours = max(
            0.0,
            (evaluation_time - latest.astimezone(timezone.utc)).total_seconds() / 3600,
        )
        recency_factor = LeadScoreFactor(
            name="recency",
            status=ScoreFactorStatus.OBSERVED,
            contribution=self._recency_points(age_hours),
            max_points=20,
            reason=f"Latest trusted journey evidence is {round(age_hours, 2)} hours old.",
            evidence_refs=[latest_trusted.event_id],
        )

        engagement_refs = [
            item.event_id
            for item in trusted_evidence
            if item.event_type in ENGAGEMENT_TYPES
        ]
        if engagement_refs:
            engagement_factor = LeadScoreFactor(
                name="engagement_frequency",
                status=ScoreFactorStatus.OBSERVED,
                contribution=self._engagement_points(len(engagement_refs)),
                max_points=10,
                reason=f"Observed {len(engagement_refs)} trusted ad-click/landing-view engagement events.",
                evidence_refs=engagement_refs,
            )
        else:
            engagement_factor = LeadScoreFactor(
                name="engagement_frequency",
                status=ScoreFactorStatus.MISSING,
                contribution=None,
                max_points=10,
                reason=(
                    "No trusted explicit engagement events are available; missing coverage is excluded "
                    "from the score denominator rather than treated as zero engagement."
                ),
                evidence_refs=[],
            )

        factors = [stage_factor, recency_factor, engagement_factor]
        if sales_intelligence is not None:
            factors.extend(
                [
                    self._sales_sla_factor(
                        name="first_response_sla",
                        window=sales_intelligence.first_response_sla,
                        sales_intelligence=sales_intelligence,
                    ),
                    self._sales_sla_factor(
                        name="visit_booking_sla",
                        window=sales_intelligence.visit_booking_sla,
                        sales_intelligence=sales_intelligence,
                    ),
                ]
            )

        observed = [item for item in factors if item.status == ScoreFactorStatus.OBSERVED]
        available_points = sum(item.max_points for item in observed)
        raw_points = sum(item.contribution or 0 for item in observed)
        normalized_score = round(raw_points / available_points * 100, 2)

        if sales_intelligence is None:
            # Preserve Phase 9A v1 behavior exactly for the existing GET API and NBA service.
            missing_inputs = [
                "source_quality",
                "project_fit",
                "budget_fit",
                "sales_sla",
            ]
        else:
            missing_inputs = [
                "source_quality",
                "project_fit",
                "budget_fit",
            ]
            sla_factors = {
                item.name: item
                for item in factors
                if item.name in SLA_FACTOR_CAPACITY
            }
            if not sales_intelligence.completeness_verified:
                missing_inputs.append("sales_sla_completeness")
            for name in ("first_response_sla", "visit_booking_sla"):
                if sla_factors[name].status == ScoreFactorStatus.MISSING:
                    missing_inputs.append(name)

        if engagement_factor.status == ScoreFactorStatus.MISSING:
            missing_inputs.append("engagement_frequency")

        distinct_sources = len({item.source_system for item in trusted_evidence})
        confidence = 0.45
        confidence += min(0.20, len(trusted_evidence) * 0.04)
        confidence += min(0.10, distinct_sources * 0.03)
        if engagement_factor.status == ScoreFactorStatus.OBSERVED:
            confidence += 0.05
        confidence = min(confidence, 0.80)
        if projection.untrusted_evidence_count:
            confidence = min(confidence, 0.65)
        confidence = round(confidence, 2)

        caveats = [
            "Score is a deterministic journey-momentum index, not a conversion probability.",
            "Missing inputs are excluded from the score denominator and are not converted into negative signals.",
            "Protected or sensitive traits are neither inferred nor used.",
        ]
        if projection.untrusted_evidence_count:
            caveats.append(
                "Untrusted or invalid journey evidence is retained for audit, excluded from score inputs, and caps confidence."
            )
        if any(
            item.authority_status == JourneyEvidenceAuthority.INVALID_CONTRACT
            for item in projection.evidence
        ):
            caveats.append("At least one journey evidence declaration failed the versioned contract.")
        if sales_intelligence is not None:
            caveats.append(
                "Sales SLA factors are included numerically only when the activity batch is bound to a verified signed Sales Hub completeness proof."
            )
            if not sales_intelligence.completeness_verified:
                caveats.append(
                    "Sales SLA factors are excluded because the supplied completeness proof is absent or invalid."
                )
            if any(
                item.name in SLA_FACTOR_CAPACITY
                and item.status == ScoreFactorStatus.MISSING
                for item in factors
            ):
                caveats.append(
                    "Pending, not-evaluable, or overdue-without-completeness SLA states remain missing data and do not reduce the score."
                )

        return ExplainableLeadScore(
            subject_ref=subject_ref,
            methodology=(
                "journey_momentum_v1"
                if sales_intelligence is None
                else "journey_momentum_with_sales_sla_v2"
            ),
            score_version=(
                "phase-9a-score-v1"
                if sales_intelligence is None
                else "phase-9b-score-v2"
            ),
            score=normalized_score,
            confidence=confidence,
            available_points=available_points,
            current_state=projection.current_state,
            as_of=evaluation_time,
            factors=factors,
            missing_inputs=missing_inputs,
            caveats=caveats,
        )
