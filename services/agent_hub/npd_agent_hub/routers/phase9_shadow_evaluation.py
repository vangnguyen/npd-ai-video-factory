from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth import Principal, require_operator
from ..orchestrator import hub
from ..phase9_sales_shadow_evaluation import Phase9SalesShadowEvaluationService
from ..phase9_sales_shadow_evaluation_models import (
    Phase9SalesShadowEvaluationReport,
    Phase9SalesShadowEvaluationRequest,
)
from ..phase9_shadow_evaluation import Phase9ShadowEvaluationService
from ..phase9_shadow_evaluation_models import (
    Phase9ShadowEvaluationReport,
    Phase9ShadowEvaluationRequest,
)


phase9a_router = APIRouter(
    prefix="/api/v1/phase9/shadow-evaluation",
    tags=["phase9-shadow-evaluation"],
)


@phase9a_router.post("/preview", response_model=Phase9ShadowEvaluationReport)
def preview_phase9_shadow_evaluation(
    request: Phase9ShadowEvaluationRequest,
    _principal: Principal = Depends(require_operator),
) -> Phase9ShadowEvaluationReport:
    return Phase9ShadowEvaluationService(hub.store, hub.journeys).evaluate(request)


sales_router = APIRouter(
    prefix="/api/v1/phase9/sales-shadow-evaluation",
    tags=["phase9-sales-shadow-evaluation"],
)


@sales_router.post("/preview", response_model=Phase9SalesShadowEvaluationReport)
def preview_phase9_sales_shadow_evaluation(
    request: Phase9SalesShadowEvaluationRequest,
    _principal: Principal = Depends(require_operator),
) -> Phase9SalesShadowEvaluationReport:
    return Phase9SalesShadowEvaluationService(
        hub.store,
        hub.journeys,
        hub.delivery,
    ).evaluate(request)


router = APIRouter()
router.include_router(phase9a_router)
router.include_router(sales_router)
