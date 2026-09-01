from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth import Principal, require_operator
from ..orchestrator import hub
from ..phase9_shadow_evaluation import Phase9ShadowEvaluationService
from ..phase9_shadow_evaluation_models import (
    Phase9ShadowEvaluationReport,
    Phase9ShadowEvaluationRequest,
)


router = APIRouter(
    prefix="/api/v1/phase9/shadow-evaluation",
    tags=["phase9-shadow-evaluation"],
)


@router.post("/preview", response_model=Phase9ShadowEvaluationReport)
def preview_phase9_shadow_evaluation(
    request: Phase9ShadowEvaluationRequest,
    _principal: Principal = Depends(require_operator),
) -> Phase9ShadowEvaluationReport:
    return Phase9ShadowEvaluationService(hub.store, hub.journeys).evaluate(request)
