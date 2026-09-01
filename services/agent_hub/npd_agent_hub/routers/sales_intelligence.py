from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..auth import Principal, require_operator
from ..orchestrator import hub
from ..sales_intelligence import SalesIntelligenceService
from ..sales_intelligence_models import (
    SalesIntelligencePreviewRequest,
    SalesIntelligenceSnapshot,
)


router = APIRouter(prefix="/api/v1/sales-intelligence", tags=["sales-intelligence"])


@router.post("/preview", response_model=SalesIntelligenceSnapshot)
def preview_sales_intelligence(
    request: SalesIntelligencePreviewRequest,
    _principal: Principal = Depends(require_operator),
) -> SalesIntelligenceSnapshot:
    try:
        return SalesIntelligenceService(
            hub.store,
            hub.journeys,
            hub.delivery,
        ).preview(request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="sales-intelligence subject not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
