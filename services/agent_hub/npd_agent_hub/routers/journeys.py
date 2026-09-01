from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..auth import Principal, require_viewer
from ..journey_models import JourneyProjection, JourneyTransition
from ..orchestrator import hub


router = APIRouter(prefix="/api/v1/journeys", tags=["journeys"])


@router.get("/{subject_ref}", response_model=JourneyProjection)
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


@router.get("/{subject_ref}/history", response_model=list[JourneyTransition])
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
