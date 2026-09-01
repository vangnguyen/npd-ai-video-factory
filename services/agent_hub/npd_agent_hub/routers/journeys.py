from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..auth import Principal, require_viewer
from ..journey_models import JourneyProjection, JourneyTransition
from ..orchestrator import hub
from .lead_scoring import router as lead_scoring_router
from .nba_reviews import router as nba_reviews_router
from .next_best_action import router as next_best_action_router


journey_router = APIRouter(prefix="/api/v1/journeys", tags=["journeys"])


@journey_router.get("/{subject_ref}", response_model=JourneyProjection)
def get_journey_projection(
    subject_ref: str,
    _principal: Principal = Depends(require_viewer),
) -> JourneyProjection:
    try:
        return hub.journeys.project(subject_ref)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="journey subject not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@journey_router.get("/{subject_ref}/history", response_model=list[JourneyTransition])
def get_journey_history(
    subject_ref: str,
    _principal: Principal = Depends(require_viewer),
) -> list[JourneyTransition]:
    try:
        return hub.journeys.history(subject_ref)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="journey subject not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


router = APIRouter()
router.include_router(journey_router)
router.include_router(lead_scoring_router)
# Static review routes must be registered before /next-best-actions/{subject_ref}.
router.include_router(nba_reviews_router)
router.include_router(next_best_action_router)
