from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import Principal, require_operator, require_viewer
from ..nba_review import NBAReviewService
from ..nba_review_models import NBAReviewCreate, NBAReviewRecord, NBAReviewSummary
from ..orchestrator import hub


router = APIRouter(
    prefix="/api/v1/next-best-actions/reviews",
    tags=["next-best-action-review"],
)


@router.get("/summary", response_model=NBAReviewSummary)
def get_nba_review_summary(
    subject_ref: str | None = Query(default=None),
    _principal: Principal = Depends(require_viewer),
) -> NBAReviewSummary:
    try:
        return NBAReviewService(hub.store, hub.journeys).summary(subject_ref=subject_ref)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("", response_model=list[NBAReviewRecord])
def list_nba_reviews(
    subject_ref: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    _principal: Principal = Depends(require_viewer),
) -> list[NBAReviewRecord]:
    try:
        return NBAReviewService(hub.store, hub.journeys).list(
            subject_ref=subject_ref,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("", response_model=NBAReviewRecord, status_code=201)
def create_nba_shadow_review(
    request: NBAReviewCreate,
    principal: Principal = Depends(require_operator),
) -> NBAReviewRecord:
    try:
        return NBAReviewService(hub.store, hub.journeys).record(
            request,
            reviewer_role=principal.role.name.lower(),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="journey subject not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
