from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import Principal, require_viewer
from ..next_best_action import NextBestActionService
from ..next_best_action_models import (
    NextBestActionPreviewRequest,
    NextBestActionRecommendation,
)
from ..orchestrator import hub


router = APIRouter(prefix="/api/v1/next-best-actions", tags=["next-best-action"])


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
