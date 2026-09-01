from __future__ import annotations

from .journeys import JourneyService
from .nba_review_models import (
    NBAReviewCreate,
    NBAReviewDisposition,
    NBAReviewRecord,
    NBAReviewSummary,
)
from .nba_review_repository import NBAReviewRepository, repository_for_store
from .next_best_action import NextBestActionService
from .store import HubStore


class NBAReviewService:
    """Stores reviewer judgement about a recommendation without executing it."""

    def __init__(
        self,
        store: HubStore,
        journeys: JourneyService,
        repository: NBAReviewRepository | None = None,
    ) -> None:
        self.store = store
        self.journeys = journeys
        self.repository = repository or repository_for_store(store)
        self.nba = NextBestActionService(journeys)

    def record(
        self,
        request: NBAReviewCreate,
        *,
        reviewer_role: str,
    ) -> NBAReviewRecord:
        if reviewer_role not in {"operator", "owner"}:
            raise PermissionError("NBA shadow review requires operator or owner role")
        recommendation = self.nba.recommend(
            request.subject_ref,
            as_of=request.as_of,
        )
        record = NBAReviewRecord(
            subject_ref=request.subject_ref,
            recommendation_version=recommendation.recommendation_version,
            recommended_action=recommendation.recommended_action,
            recommendation_as_of=recommendation.as_of,
            journey_state=recommendation.journey_state,
            lead_score=recommendation.lead_score,
            recommendation_confidence=recommendation.confidence,
            evidence_refs=recommendation.evidence_refs,
            disposition=request.disposition,
            false_positive=request.disposition == NBAReviewDisposition.NOT_RELEVANT,
            note=request.note,
            reviewer_role=reviewer_role,
        )
        self.repository.save(record)
        return record

    def list(
        self,
        *,
        subject_ref: str | None = None,
        limit: int = 100,
    ) -> list[NBAReviewRecord]:
        if subject_ref is not None:
            JourneyService.parse_subject_ref(subject_ref)
        return self.repository.list(subject_ref=subject_ref, limit=limit)

    def summary(self, *, subject_ref: str | None = None) -> NBAReviewSummary:
        rows = self.list(subject_ref=subject_ref, limit=1000)
        relevant = sum(item.disposition == NBAReviewDisposition.RELEVANT for item in rows)
        not_relevant = sum(
            item.disposition == NBAReviewDisposition.NOT_RELEVANT for item in rows
        )
        needs_context = sum(
            item.disposition == NBAReviewDisposition.NEEDS_MORE_CONTEXT for item in rows
        )
        decided = relevant + not_relevant
        false_positive_rate = (
            round(not_relevant / decided, 4) if decided else None
        )
        return NBAReviewSummary(
            total_reviews=len(rows),
            relevant=relevant,
            not_relevant=not_relevant,
            needs_more_context=needs_context,
            false_positive_rate=false_positive_rate,
            latest_reviewed_at=max((item.reviewed_at for item in rows), default=None),
        )
