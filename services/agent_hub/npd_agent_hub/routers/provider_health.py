from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import Principal, require_operator, require_viewer
from ..orchestrator import hub
from ..provider_health_models import (
    ProviderAlertAcknowledgeRequest,
    ProviderAlertSeverity,
    ProviderAlertStatus,
    ProviderHealthAlert,
    ProviderHealthSchedulerStatus,
    ProviderHealthStatus,
)


router = APIRouter(prefix="/api/v1/provider-health")


@router.get("/status", response_model=ProviderHealthStatus)
def provider_health_status(
    _principal: Principal = Depends(require_viewer),
) -> ProviderHealthStatus:
    return hub.provider_health.status()


@router.get("/scheduler", response_model=ProviderHealthSchedulerStatus)
def provider_health_scheduler_status(
    _principal: Principal = Depends(require_viewer),
) -> ProviderHealthSchedulerStatus:
    return hub.provider_health_scheduler.status()


@router.post("/evaluate", response_model=ProviderHealthSchedulerStatus)
async def evaluate_provider_health_cached(
    _principal: Principal = Depends(require_operator),
) -> ProviderHealthSchedulerStatus:
    return await hub.provider_health_scheduler.run_once(force=True)


@router.post("/refresh", response_model=ProviderHealthStatus)
async def refresh_provider_health(
    principal: Principal = Depends(require_operator),
) -> ProviderHealthStatus:
    probe = await hub.executor.probe_provider_health()
    return hub.provider_health.refresh(
        configuration=probe["configuration"],
        probes=probe["probes"],
        actor=principal.subject,
    )


@router.get("/alerts", response_model=list[ProviderHealthAlert])
def list_provider_health_alerts(
    status: ProviderAlertStatus | None = Query(default=None),
    severity: ProviderAlertSeverity | None = Query(default=None),
    provider: str | None = Query(default=None, min_length=2, max_length=80),
    limit: int = Query(default=100, ge=1, le=1000),
    _principal: Principal = Depends(require_viewer),
) -> list[ProviderHealthAlert]:
    return hub.provider_health.list_alerts(
        status=status,
        severity=severity,
        provider=provider,
        limit=limit,
    )


@router.post(
    "/alerts/{alert_id}/acknowledge",
    response_model=ProviderHealthAlert,
)
def acknowledge_provider_health_alert(
    alert_id: str,
    request: ProviderAlertAcknowledgeRequest,
    principal: Principal = Depends(require_operator),
) -> ProviderHealthAlert:
    current = hub.store.get_provider_alert(alert_id)
    if current is None:
        raise HTTPException(status_code=404, detail="provider-health alert not found")
    if current.status != request.expected_status:
        raise HTTPException(status_code=409, detail="provider-health alert status changed")
    try:
        return hub.provider_health.acknowledge(alert_id, actor=principal.subject)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

