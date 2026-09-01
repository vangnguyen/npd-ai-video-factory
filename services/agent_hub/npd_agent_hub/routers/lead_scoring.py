from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import Principal, require_operator, require_viewer
from ..lead_scoring import LeadScoringService
from ..lead_scoring_models import ExplainableLeadScore
from ..orchestrator import hub
from ..sales_intelligence import SalesIntelligenceService
from ..sales_intelligence_models import SalesIntelligencePreviewRequest
from ..sla_scoring_models import SalesAwareLeadScorePreview


router = APIRouter(prefix="/api/v1/lead-scores", tags=["lead-scoring"])


@router.post("/sales-preview", response_model=SalesAwareLeadScorePreview)
def preview_sales_aware_lead_score(
    request: SalesIntelligencePreviewRequest,
    _principal: Principal = Depends(require_operator),
) -> SalesAwareLeadScorePreview:
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
        return SalesAwareLeadScorePreview(
            sales_intelligence=sales,
            lead_score=score,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="lead score subject not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{subject_ref}", response_model=ExplainableLeadScore)
def get_explainable_lead_score(
    subject_ref: str,
    as_of: datetime | None = Query(default=None),
    _principal: Principal = Depends(require_viewer),
) -> ExplainableLeadScore:
    try:
        return LeadScoringService(hub.journeys).score(subject_ref, as_of=as_of)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="journey subject not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
