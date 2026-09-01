from __future__ import annotations

from .delivery_observability import AttributionDeliveryService
from .journeys import JourneyService
from .lead_scoring import LeadScoringService
from .nba_review import NBAReviewService
from .nba_review_models import NBAReviewDisposition, NBAReviewRecord, NBAReviewSummary
from .nba_review_repository import NBAReviewRepository, repository_for_store
from .sales_intelligence import SalesIntelligenceService
from .sales_nba_review_models import SALES_NBA_REVIEW_VERSION, SalesNBAReviewCreate
from .sales_next_best_action import SalesAwareNextBestActionService
from .store import HubStore


class SalesNBAReviewService:
    """Version-bound reviewer telemetry for server-computed Phase 9B NBA v2."""

    def __init__(
        self,
        store: HubStore,
        journeys: JourneyService,
        delivery: AttributionDeliveryService,
        repository: NBAReviewRepository | None = None,
    ) -> None:
        self.store = store
        self.journeys = journeys
        self.delivery = delivery
        self.repository = repository or repository_for_store(store)
        self.sales = SalesIntelligenceService(store, journeys, delivery)
        self.scoring = LeadScoringService(journeys)
        self.nba = SalesAwareNextBestActionService(journeys)

    def record(
        self,
        request: SalesNBAReviewCreate,
        *,
        reviewer_role: str,
    ) -> NBAReviewRecord:
        if reviewer_role not in {"operator", "owner"}:
            raise PermissionError("NBA v2 shadow review requires operator or owner role")

        evaluation = request.evaluation
        sales = self.sales.preview(evaluation)
        score = self.scoring.score(
            evaluation.subject_ref,
            as_of=evaluation.as_of,
            sales_intelligence=sales,
        )
        recommendation = self.nba.recommend(
            evaluation.subject_ref,
            sales_intelligence=sales,
            lead_score=score,
        )
        if recommendation.recommendation_version != SALES_NBA_REVIEW_VERSION:
            raise ValueError("Sales NBA review requires phase-9b-nba-v2 recommendation")

        record = NBAReviewRecord(
            subject_ref=evaluation.subject_ref,
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
        return NBAReviewService(
            self.store,
            self.journeys,
            repository=self.repository,
        ).list(
            subject_ref=subject_ref,
            recommendation_version=SALES_NBA_REVIEW_VERSION,
            limit=limit,
        )

    def summary(self, *, subject_ref: str | None = None) -> NBAReviewSummary:
        return NBAReviewService(
            self.store,
            self.journeys,
            repository=self.repository,
        ).summary(
            subject_ref=subject_ref,
            recommendation_version=SALES_NBA_REVIEW_VERSION,
        )
