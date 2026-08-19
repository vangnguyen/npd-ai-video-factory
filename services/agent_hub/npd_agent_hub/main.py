from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query

from .models import (
    AgentDescriptor,
    AgentTask,
    ApprovalDecision,
    AuditEvent,
    CommandCenterReport,
    CommandCenterSnapshot,
    PlannedAction,
    ToolExecutionResult,
)
from .orchestrator import hub


app = FastAPI(
    title="NPD Agent Hub",
    version="0.3.0",
    description="Multi-agent management control plane for marketing, content, video, social, sales and CRM.",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    try:
        if not hub.storage_health():
            raise RuntimeError("storage ping failed")
    except Exception as exc:
        raise HTTPException(status_code=503, detail="agent hub storage unavailable") from exc
    return {"status": "ready", "storage": hub.store.backend_name}


@app.get("/api/v1/agents", response_model=list[AgentDescriptor])
def list_agents() -> list[AgentDescriptor]:
    return hub.list_agents()


@app.post("/api/v1/agent-tasks", response_model=CommandCenterReport)
def create_agent_task(task: AgentTask) -> CommandCenterReport:
    return hub.run(task)


@app.get("/api/v1/agent-tasks/{task_id}", response_model=CommandCenterReport)
def get_agent_task(task_id: str) -> CommandCenterReport:
    report = hub.get(task_id)
    if report is None:
        raise HTTPException(status_code=404, detail="agent task not found")
    return report


@app.post(
    "/api/v1/agent-tasks/{task_id}/actions/{action_id}/decision",
    response_model=PlannedAction,
)
def decide_action(task_id: str, action_id: str, decision: ApprovalDecision) -> PlannedAction:
    try:
        return hub.decide(task_id, action_id, decision)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="agent task not found") from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="planned action not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post(
    "/api/v1/agent-tasks/{task_id}/actions/{action_id}/execute",
    response_model=ToolExecutionResult,
)
async def execute_action(task_id: str, action_id: str) -> ToolExecutionResult:
    try:
        return await hub.execute(task_id, action_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="agent task not found") from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="planned action not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get(
    "/api/v1/agent-tasks/{task_id}/executions",
    response_model=list[ToolExecutionResult],
)
def list_task_executions(
    task_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[ToolExecutionResult]:
    try:
        return hub.list_executions(task_id, limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="agent task not found") from exc


@app.get(
    "/api/v1/agent-tasks/{task_id}/audit",
    response_model=list[AuditEvent],
)
def list_task_audit(
    task_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[AuditEvent]:
    try:
        return hub.list_audit(task_id, limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="agent task not found") from exc


@app.get("/api/v1/command-center", response_model=CommandCenterSnapshot)
def command_center(
    limit: int = Query(default=50, ge=1, le=200),
    audit_limit: int = Query(default=50, ge=1, le=1000),
) -> CommandCenterSnapshot:
    return hub.command_center(limit=limit, audit_limit=audit_limit)
