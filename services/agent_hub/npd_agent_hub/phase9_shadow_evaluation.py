from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

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


NBA_V1_VERSION = "phase-9a-nba-v1"


class Phase9ShadowEvaluationService:
    """Aggregate-only evaluation over Journey, Lead Score v1, NBA v1 and v1 review telemetry."""

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

    def _review_aggregate(self, subject_refs: list[str]) -> Phase9ReviewAggregate:
        rows = []
        for subject_ref in subject_refs:
            rows.extend(
                self.reviews.list(
                    subject_ref=subject_ref,
                    recommendation_version=NBA_V1_VERSION,
                    limit=1000,
                )
            )
        # A review_id is globally unique; de-duplicate defensively in case a future
        # subject alias causes the same immutable review to appear twice.
        unique = {row.review_id: row for row in rows}.values()
        relevant = sum(row.disposition == NBAReviewDisposition.RELEVANT for row in unique)
        not_relevant = sum(
            row.disposition == NBAReviewDisposition.NOT_RELEVANT for row in unique
        )
        needs_context = sum(
            row.disposition == NBAReviewDisposition.NEEDS_MORE_CONTEXT for row in unique
        )
        decided = relevant + not_relevant
        return Phase9ReviewAggregate(
            total_reviews=relevant + not_relevant + needs_context,
            relevant=relevant,
            not_relevant=not_relevant,
            needs_more_context=needs_context,
            false_positive_rate=(round(not_relevant / decided, 4) if decided else None),
        )

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
        untrusted_count = 0

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
                untrusted_count += 1
            for name in score.missing_inputs:
                missing_inputs[name] += 1

        evaluated_count = len(scores)
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
            subjects_with_untrusted_evidence=untrusted_count,
            review_aggregate=self._review_aggregate(unique_subjects),
            caveats=[
                "This is an aggregate Phase 9A shadow-evaluation preview, not a production decision or conversion forecast.",
                "The response intentionally contains no subject IDs or per-subject outcomes; failures are grouped only by bounded category.",
                "Lead Score remains a deterministic journey-momentum index and NBA remains recommendation-only with execution disabled.",
                "Review aggregates are explicitly limited to phase-9a-nba-v1 records and exclude Phase 9B NBA v2 telemetry.",
            ],
        )
