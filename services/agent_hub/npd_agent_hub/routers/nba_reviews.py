from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import Principal, require_operator, require_viewer
from ..nba_review import NBAReviewService
from ..nba_review_models import NBAReviewCreate, NBAReviewRecord, NBAReviewSummary
from ..orchestrator import hub
from ..sales_nba_review import SalesNBAReviewService
from ..sales_nba_review_models import SalesNBAReviewCreate


NBA_V1_VERSION = "phase-9a-nba-v1"

router = APIRouter(
    prefix="/api/v1/next-best-actions/reviews",
    tags=["next-best-action-review"],
)


@router.get("/sales/summary", response_model=NBAReviewSummary)
def get_sales_nba_review_summary(
    subject_ref: str | None = Query(default=None),
    _principal: Principal = Depends(require_viewer),
) -> NBAReviewSummary:
    try:
        return SalesNBAReviewService(
            hub.store,
            hub.journeys,
            hub.delivery,
        ).summary(subject_ref=subject_ref)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/sales", response_model=list[NBAReviewRecord])
def list_sales_nba_reviews(
    subject_ref: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    _principal: Principal = Depends(require_viewer),
) -> list[NBAReviewRecord]:
    try:
        return SalesNBAReviewService(
            hub.store,
            hub.journeys,
            hub.delivery,
        ).list(subject_ref=subject_ref, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/sales", response_model=NBAReviewRecord, status_code=201)
def create_sales_nba_shadow_review(
    request: SalesNBAReviewCreate,
    principal: Principal = Depends(require_operator),
) -> NBAReviewRecord:
    try:
        return SalesNBAReviewService(
            hub.store,
            hub.journeys,
            hub.delivery,
        ).record(
            request,
            reviewer_role=principal.role.name.lower(),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="journey subject not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/summary", response_model=NBAReviewSummary)
def get_nba_review_summary(
    subject_ref: str | None = Query(default=None),
    _principal: Principal = Depends(require_viewer),
) -> NBAReviewSummary:
    try:
        return NBAReviewService(hub.store, hub.journeys).summary(
            subject_ref=subject_ref,
            recommendation_version=NBA_V1_VERSION,
        )
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
            recommendation_version=NBA_V1_VERSION,
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
