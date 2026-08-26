from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import Principal, require_operator, require_viewer
from ..delivery_models import (
    AttributionDeadLetter,
    AttributionDeliveryEnvelope,
    AttributionDeliveryFailure,
    AttributionDeliveryReceipt,
    AttributionDeliveryStatus,
    AttributionHeartbeatReceipt,
    AttributionHeartbeatReceiptVerificationRequest,
    AttributionProducerHeartbeat,
    AttributionReceiptVerification,
    AttributionReceiptVerificationRequest,
    DeliveryOutcome,
)
from ..delivery_observability import DeliveryIntegrityConflict, DeliveryNotConfigured
from ..orchestrator import hub


router = APIRouter(prefix="/api/v1/attribution/deliveries")


@router.get("/status", response_model=AttributionDeliveryStatus)
def attribution_delivery_status(
    _principal: Principal = Depends(require_viewer),
) -> AttributionDeliveryStatus:
    return hub.delivery.status()


@router.get("/receipts", response_model=list[AttributionDeliveryReceipt])
def list_attribution_delivery_receipts(
    producer: str | None = Query(default=None),
    outcome: DeliveryOutcome | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    _principal: Principal = Depends(require_viewer),
) -> list[AttributionDeliveryReceipt]:
    return hub.delivery.list_receipts(
        producer=producer, outcome=outcome, limit=limit
    )


@router.get("/dead-letters", response_model=list[AttributionDeadLetter])
def list_attribution_dead_letters(
    producer: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    _principal: Principal = Depends(require_viewer),
) -> list[AttributionDeadLetter]:
    return hub.delivery.list_dead_letters(producer=producer, limit=limit)


@router.post("/receipts/verify", response_model=AttributionReceiptVerification)
def verify_attribution_delivery_receipt(
    request: AttributionReceiptVerificationRequest,
    _principal: Principal = Depends(require_viewer),
) -> AttributionReceiptVerification:
    try:
        return hub.delivery.verify(request.receipt)
    except DeliveryNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/failures", response_model=AttributionDeliveryReceipt)
def record_attribution_delivery_failure(
    request: AttributionDeliveryFailure,
    principal: Principal = Depends(require_operator),
) -> AttributionDeliveryReceipt:
    try:
        return hub.delivery.record_failure(request, actor=principal.subject)
    except DeliveryNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DeliveryIntegrityConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("", response_model=AttributionDeliveryReceipt)
def ingest_attribution_delivery(
    request: AttributionDeliveryEnvelope,
    principal: Principal = Depends(require_operator),
) -> AttributionDeliveryReceipt:
    try:
        return hub.delivery.ingest(request, actor=principal.subject)
    except DeliveryNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DeliveryIntegrityConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/heartbeats", response_model=list[AttributionHeartbeatReceipt])
def list_attribution_heartbeats(
    producer: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    _principal: Principal = Depends(require_viewer),
) -> list[AttributionHeartbeatReceipt]:
    return hub.delivery.list_heartbeats(producer=producer, limit=limit)


@router.post("/heartbeats", response_model=AttributionHeartbeatReceipt)
async def ingest_attribution_heartbeat(
    request: AttributionProducerHeartbeat,
    principal: Principal = Depends(require_operator),
) -> AttributionHeartbeatReceipt:
    try:
        receipt = hub.delivery.ingest_heartbeat(request, actor=principal.subject)
        await hub.provider_health_scheduler.run_once(force=True)
        return receipt
    except DeliveryNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DeliveryIntegrityConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/heartbeats/verify", response_model=AttributionReceiptVerification)
def verify_attribution_heartbeat_receipt(
    request: AttributionHeartbeatReceiptVerificationRequest,
    _principal: Principal = Depends(require_viewer),
) -> AttributionReceiptVerification:
    try:
        return hub.delivery.verify_heartbeat(request.receipt)
    except DeliveryNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
