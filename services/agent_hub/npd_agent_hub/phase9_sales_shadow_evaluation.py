from __future__ import annotations

from collections import Counter
from datetime import timezone

from .delivery_observability import AttributionDeliveryService
from .journeys import JourneyService
from .lead_scoring import LeadScoringService
from .nba_review_models import NBAReviewDisposition
from .phase9_sales_shadow_evaluation_models import (
    Phase9SalesShadowEvaluationReport,
    Phase9SalesShadowEvaluationRequest,
)
from .phase9_shadow_evaluation_models import Phase9ReviewAggregate
from .sales_intelligence import SalesIntelligenceService
from .sales_intelligence_models import SalesSLAStatus
from .sales_nba_review import SalesNBAReviewService
from .sales_next_best_action import SalesAwareNextBestActionService
from .store import HubStore


class Phase9SalesShadowEvaluationService:
    """Aggregate-only Phase 9B evaluation over signed Sales SLA, score v2, NBA v2 and v2 review telemetry."""

    def __init__(
        self,
        store: HubStore,
        journeys: JourneyService,
        delivery: AttributionDeliveryService,
    ) -> None:
        self.store = store
        self.journeys = journeys
        self.delivery = delivery
        self.sales = SalesIntelligenceService(store, journeys, delivery)
        self.scoring = LeadScoringService(journeys)
        self.nba = SalesAwareNextBestActionService(journeys)
        self.reviews = SalesNBAReviewService(store, journeys, delivery)

    @staticmethod
    def _score_band(score: float) -> str:
        if score >= 70:
            return "high_70_100"
        if score >= 50:
            return "medium_50_69"
        return "low_0_49"

    @staticmethod
    def _failure_reason(exc: Exception) -> str:
        if isinstance(exc, KeyError):
            return "not_found"
        if isinstance(exc, ValueError) and "trusted journey evidence" in str(exc):
            return "no_trusted_evidence"
        if isinstance(exc, ValueError) and (
            "Sales Intelligence" in str(exc)
            or "sales intelligence" in str(exc)
            or "Sales Hub" in str(exc)
            or "completeness" in str(exc)
        ):
            return "invalid_sales_evidence"
        return "evaluation_error"

    def _review_aggregate(self, subject_refs: list[str]) -> tuple[int, Phase9ReviewAggregate]:
        rows = []
        reviewed_subject_count = 0
        for subject_ref in subject_refs:
            subject_rows = self.reviews.list(subject_ref=subject_ref, limit=1000)
            if subject_rows:
                reviewed_subject_count += 1
                rows.extend(subject_rows)
        unique = {row.review_id: row for row in rows}.values()
        relevant = sum(row.disposition == NBAReviewDisposition.RELEVANT for row in unique)
        not_relevant = sum(
            row.disposition == NBAReviewDisposition.NOT_RELEVANT for row in unique
        )
        needs_context = sum(
            row.disposition == NBAReviewDisposition.NEEDS_MORE_CONTEXT for row in unique
        )
        decided = relevant + not_relevant
        return reviewed_subject_count, Phase9ReviewAggregate(
            total_reviews=relevant + not_relevant + needs_context,
            relevant=relevant,
            not_relevant=not_relevant,
            needs_more_context=needs_context,
            false_positive_rate=(round(not_relevant / decided, 4) if decided else None),
        )

    def evaluate(
        self,
        request: Phase9SalesShadowEvaluationRequest,
    ) -> Phase9SalesShadowEvaluationReport:
        as_of = request.cases[0].as_of.astimezone(timezone.utc)
        unique_cases = list({case.subject_ref: case for case in request.cases}.values())

        failures: Counter[str] = Counter()
        states: Counter = Counter()
        first_response_statuses: Counter = Counter()
        visit_booking_statuses: Counter = Counter()
        score_bands: Counter[str] = Counter()
        actions: Counter = Counter()
        priorities: Counter = Counter()
        missing_inputs: Counter[str] = Counter()
        scores: list[float] = []
        confidences: list[float] = []
        completeness_verified_count = 0
        source_complete_count = 0
        verified_breach_subject_count = 0
        verified_late_subject_count = 0
        untrusted_journey_count = 0
        untrusted_sales_count = 0
        evaluated_subject_refs: list[str] = []

        for case in unique_cases:
            try:
                projection = self.journeys.project(case.subject_ref)
                sales = self.sales.preview(case)
                score = self.scoring.score(
                    case.subject_ref,
                    as_of=case.as_of,
                    sales_intelligence=sales,
                )
                recommendation = self.nba.recommend(
                    case.subject_ref,
                    sales_intelligence=sales,
                    lead_score=score,
                )
            except (KeyError, ValueError) as exc:
                failures[self._failure_reason(exc)] += 1
                continue

            evaluated_subject_refs.append(case.subject_ref)
            states[projection.current_state] += 1
            first_response_statuses[sales.first_response_sla.status] += 1
            visit_booking_statuses[sales.visit_booking_sla.status] += 1
            score_bands[self._score_band(score.score)] += 1
            actions[recommendation.recommended_action] += 1
            priorities[recommendation.priority] += 1
            scores.append(score.score)
            confidences.append(recommendation.confidence)

            if sales.completeness_verified:
                completeness_verified_count += 1
            if sales.source_complete:
                source_complete_count += 1

            statuses = {
                sales.first_response_sla.status,
                sales.visit_booking_sla.status,
            }
            if sales.completeness_verified and SalesSLAStatus.BREACHED in statuses:
                verified_breach_subject_count += 1
            elif sales.completeness_verified and SalesSLAStatus.LATE in statuses:
                verified_late_subject_count += 1

            if projection.untrusted_evidence_count:
                untrusted_journey_count += 1
            if sales.untrusted_activity_count or sales.duplicate_activity_count:
                untrusted_sales_count += 1
            for name in score.missing_inputs:
                missing_inputs[name] += 1

        evaluated_count = len(scores)
        reviewed_subject_count, review_aggregate = self._review_aggregate(evaluated_subject_refs)
        caveats = [
            "This is an aggregate Phase 9B shadow-evaluation preview, not a production decision or conversion forecast.",
            "The response intentionally contains no subject IDs or per-subject outcomes; failures are grouped only by bounded category.",
            "Only verified signed Sales Hub completeness can produce a confirmed SLA breach or direct SLA escalation in NBA v2.",
            "Overdue missing evidence without completeness remains missing data and is excluded from negative scoring/escalation.",
            "NBA v2 remains recommendation-only; internal review priority and timing do not execute customer contact.",
            "Review aggregates are explicitly limited to phase-9b-nba-v2 records and exclude Phase 9A NBA v1 telemetry.",
        ]

        return Phase9SalesShadowEvaluationReport(
            as_of=as_of,
            requested_case_count=len(request.cases),
            unique_subject_count=len(unique_cases),
            duplicate_case_count=len(request.cases) - len(unique_cases),
            evaluated_subject_count=evaluated_count,
            failed_subject_count=sum(failures.values()),
            failure_counts=dict(sorted(failures.items())),
            journey_state_counts=dict(states),
            first_response_sla_status_counts=dict(first_response_statuses),
            visit_booking_sla_status_counts=dict(visit_booking_statuses),
            completeness_verified_count=completeness_verified_count,
            source_complete_count=source_complete_count,
            verified_breach_subject_count=verified_breach_subject_count,
            verified_late_subject_count=verified_late_subject_count,
            score_band_counts=dict(sorted(score_bands.items())),
            average_lead_score=(
                round(sum(scores) / evaluated_count, 2) if evaluated_count else None
            ),
            average_recommendation_confidence=(
                round(sum(confidences) / evaluated_count, 2)
                if evaluated_count
                else None
            ),
            recommendation_action_counts=dict(actions),
            recommendation_priority_counts=dict(priorities),
            missing_input_counts=dict(sorted(missing_inputs.items())),
            subjects_with_untrusted_journey_evidence=untrusted_journey_count,
            cases_with_untrusted_sales_activity=untrusted_sales_count,
            reviewed_subject_count=reviewed_subject_count,
            review_aggregate=review_aggregate,
            caveats=caveats,
        )
