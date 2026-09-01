from __future__ import annotations

from collections import Counter
from datetime import timezone

from .journeys import JourneyService
from .lead_scoring import LeadScoringService
from .nba_review import NBAReviewService
from .nba_review_models import NBAReviewDisposition
from .next_best_action import NextBestActionService
from .phase9_shadow_evaluation_models import (
    Phase9ReviewAggregate,
    Phase9ShadowEvaluationReport,
    Phase9ShadowEvaluationRequest,
)
from .store import HubStore


class Phase9ShadowEvaluationService:
    """Aggregate-only evaluation over Journey, Lead Score, NBA and shadow reviews."""

    def __init__(self, store: HubStore, journeys: JourneyService):
        self.store = store
        self.journeys = journeys
        self.scoring = LeadScoringService(journeys)
        self.nba = NextBestActionService(journeys)
        self.reviews = NBAReviewService(store, journeys)

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
        return "evaluation_error"

    def evaluate(
        self,
        request: Phase9ShadowEvaluationRequest,
    ) -> Phase9ShadowEvaluationReport:
        as_of = request.as_of.astimezone(timezone.utc)
        unique_subjects = list(dict.fromkeys(request.subject_refs))

        failures: Counter[str] = Counter()
        states: Counter = Counter()
        score_bands: Counter[str] = Counter()
        actions: Counter = Counter()
        priorities: Counter = Counter()
        missing_inputs: Counter[str] = Counter()
        scores: list[float] = []
        confidences: list[float] = []
        subjects_with_untrusted_evidence = 0

        for subject_ref in unique_subjects:
            try:
                projection = self.journeys.project(subject_ref)
                score = self.scoring.score(subject_ref, as_of=as_of)
                recommendation = self.nba.recommend(subject_ref, as_of=as_of)
            except (KeyError, ValueError) as exc:
                failures[self._failure_reason(exc)] += 1
                continue

            states[projection.current_state] += 1
            score_bands[self._score_band(score.score)] += 1
            actions[recommendation.recommended_action] += 1
            priorities[recommendation.priority] += 1
            scores.append(score.score)
            confidences.append(recommendation.confidence)
            if projection.untrusted_evidence_count:
                subjects_with_untrusted_evidence += 1
            for name in score.missing_inputs:
                missing_inputs[name] += 1

        review_rows = []
        for subject_ref in unique_subjects:
            review_rows.extend(
                self.reviews.list(subject_ref=subject_ref, limit=1000)
            )
        relevant = sum(
            row.disposition == NBAReviewDisposition.RELEVANT for row in review_rows
        )
        not_relevant = sum(
            row.disposition == NBAReviewDisposition.NOT_RELEVANT for row in review_rows
        )
        needs_context = sum(
            row.disposition == NBAReviewDisposition.NEEDS_MORE_CONTEXT
            for row in review_rows
        )
        decided = relevant + not_relevant
        false_positive_rate = (
            round(not_relevant / decided, 4) if decided else None
        )

        evaluated_count = len(scores)
        caveats = [
            "This is an aggregate shadow-evaluation preview, not a production decision or conversion forecast.",
            "The response intentionally contains no subject IDs; failures are grouped only by bounded reason category.",
            "Lead Score and NBA retain their existing missing-data, confidence and recommendation-only boundaries.",
            "Review false-positive rate excludes needs_more_context from its denominator.",
        ]

        return Phase9ShadowEvaluationReport(
            as_of=as_of,
            requested_subject_count=len(request.subject_refs),
            unique_subject_count=len(unique_subjects),
            duplicate_subject_count=len(request.subject_refs) - len(unique_subjects),
            evaluated_subject_count=evaluated_count,
            failed_subject_count=sum(failures.values()),
            failure_counts=dict(sorted(failures.items())),
            journey_state_counts=dict(states),
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
            subjects_with_untrusted_evidence=subjects_with_untrusted_evidence,
            review_aggregate=Phase9ReviewAggregate(
                total_reviews=len(review_rows),
                relevant=relevant,
                not_relevant=not_relevant,
                needs_more_context=needs_context,
                false_positive_rate=false_positive_rate,
            ),
            caveats=caveats,
        )
