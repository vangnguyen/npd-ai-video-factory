from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from ..auth import Principal, require_viewer
from .auth import BoundaryAuthError
from .client import IntegrationDisabled
from .models import (
    PersistedVideoFactoryEvent,
    VideoFactoryAuditRecord,
    VideoFactoryIntegrationStatus,
    WebhookAcceptedResponse,
)
from .receiver import VideoFactoryBoundary, WebhookBoundaryError


router = APIRouter(tags=["Video Factory boundary"])
disabled_boundary = VideoFactoryBoundary.disabled()


def boundary_from(request: Request) -> VideoFactoryBoundary:
    return getattr(request.app.state, "video_factory_boundary", disabled_boundary)


@router.get(
    "/api/v1/integrations/video-factory/status",
    response_model=VideoFactoryIntegrationStatus,
)
def video_factory_status(
    request: Request,
    _principal: Principal = Depends(require_viewer),
) -> VideoFactoryIntegrationStatus:
    return boundary_from(request).status()


@router.get(
    "/api/v1/integrations/video-factory/events",
    response_model=list[PersistedVideoFactoryEvent],
)
def list_video_factory_events(
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    _principal: Principal = Depends(require_viewer),
) -> list[PersistedVideoFactoryEvent]:
    try:
        return boundary_from(request).list_events(limit=limit)
    except IntegrationDisabled as exc:
        raise _disabled_http_error() from exc


@router.get(
    "/api/v1/integrations/video-factory/audit",
    response_model=list[VideoFactoryAuditRecord],
)
def list_video_factory_audit(
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    _principal: Principal = Depends(require_viewer),
) -> list[VideoFactoryAuditRecord]:
    try:
        return boundary_from(request).list_audit(limit=limit)
    except IntegrationDisabled as exc:
        raise _disabled_http_error() from exc


@router.post(
    "/agent-hub/events/v1",
    response_model=WebhookAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def receive_video_factory_event(
    request: Request,
    response: Response,
) -> WebhookAcceptedResponse:
    try:
        receiver = boundary_from(request).require_receiver()
    except IntegrationDisabled as exc:
        raise _disabled_http_error() from exc
    try:
        result = receiver.receive(body=await request.body(), headers=request.headers)
    except BoundaryAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": exc.code, "message": str(exc)}},
        ) from exc
    except WebhookBoundaryError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"error": {"code": exc.code, "message": str(exc)}},
        ) from exc
    response.headers["X-Idempotent-Replay"] = str(
        result.status == "idempotent_replay"
    ).lower()
    return result


def _disabled_http_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "error": {
                "code": "VIDEO_FACTORY_INTEGRATION_DISABLED",
                "message": "Video Factory integration is disabled",
            }
        },
    )
