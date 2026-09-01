from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import Principal, require_operator, require_viewer
from ..lead_scoring import LeadScoringService
from ..next_best_action import NextBestActionService
from ..next_best_action_models import (
    NextBestActionPreviewRequest,
    NextBestActionRecommendation,
)
from ..orchestrator import hub
from ..sales_intelligence import SalesIntelligenceService
from ..sales_intelligence_models import SalesIntelligencePreviewRequest
from ..sales_next_best_action import SalesAwareNextBestActionService
from ..sla_nba_models import SalesAwareNextBestActionPreview


router = APIRouter(prefix="/api/v1/next-best-actions", tags=["next-best-action"])


@router.post("/sales-preview", response_model=SalesAwareNextBestActionPreview)
def preview_sales_aware_next_best_action(
    request: SalesIntelligencePreviewRequest,
    _principal: Principal = Depends(require_operator),
) -> SalesAwareNextBestActionPreview:
    try:
        sales = SalesIntelligenceService(
            hub.store,
            hub.journeys,
            hub.delivery,
        ).preview(request)
        score = LeadScoringService(hub.journeys).score(
            request.subject_ref,
            as_of=request.as_of,
            sales_intelligence=sales,
        )
        recommendation = SalesAwareNextBestActionService(hub.journeys).recommend(
            request.subject_ref,
            sales_intelligence=sales,
            lead_score=score,
        )
        return SalesAwareNextBestActionPreview(
            sales_intelligence=sales,
            lead_score=score,
            recommendation=recommendation,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="journey subject not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{subject_ref}", response_model=NextBestActionRecommendation)
def get_next_best_action(
    subject_ref: str,
    as_of: datetime | None = Query(default=None),
    _principal: Principal = Depends(require_viewer),
) -> NextBestActionRecommendation:
    try:
        return NextBestActionService(hub.journeys).recommend(subject_ref, as_of=as_of)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="journey subject not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/preview", response_model=NextBestActionRecommendation)
def preview_next_best_action(
    request: NextBestActionPreviewRequest,
    _principal: Principal = Depends(require_viewer),
) -> NextBestActionRecommendation:
    try:
        return NextBestActionService(hub.journeys).recommend(
            request.subject_ref,
            as_of=request.as_of,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="journey subject not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
