from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Query, Request

from .auth import Principal, authorizer, require_operator, require_owner, require_viewer
from .dashboard import command_center_html
from .espocrm_mapping import EspoMappingReader, EspoMappingRecommendation
from .espocrm_schema import (
    EspoEntitySchema,
    EspoSchemaError,
    EspoSchemaNotConfigured,
    EspoSchemaReader,
)
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
    version="0.5.0",
    description="Multi-agent management control plane for marketing, content, video, social, sales and CRM.",
)
schema_reader = EspoSchemaReader()
mapping_reader = EspoMappingReader(schema_reader)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    try:
        if not hub.storage_health():
            raise RuntimeError("storage ping failed")
        auth_errors = authorizer.configuration_errors()
        if auth_errors:
            raise RuntimeError("; ".join(auth_errors))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="agent hub dependency/configuration unavailable") from exc
    return {
        "status": "ready",
        "storage": hub.store.backend_name,
        "auth": authorizer.settings.auth_mode,
    }


@app.get("/command-center")
def command_center_page():
    return command_center_html()


@app.get("/api/v1/whoami")
def whoami(principal: Principal = Depends(require_viewer)) -> dict[str, str]:
    return {"role": principal.role.name.lower(), "subject": principal.subject}


@app.get("/api/v1/agents", response_model=list[AgentDescriptor])
def list_agents(_principal: Principal = Depends(require_viewer)) -> list[AgentDescriptor]:
    return hub.list_agents()


@app.post("/api/v1/agent-tasks", response_model=CommandCenterReport)
def create_agent_task(
    task: AgentTask,
    _principal: Principal = Depends(require_operator),
) -> CommandCenterReport:
    return hub.run(task)


@app.get("/api/v1/agent-tasks/{task_id}", response_model=CommandCenterReport)
def get_agent_task(
    task_id: str,
    _principal: Principal = Depends(require_viewer),
) -> CommandCenterReport:
    report = hub.get(task_id)
    if report is None:
        raise HTTPException(status_code=404, detail="agent task not found")
    return report


@app.post(
    "/api/v1/agent-tasks/{task_id}/actions/{action_id}/decision",
    response_model=PlannedAction,
)
def decide_action(
    task_id: str,
    action_id: str,
    decision: ApprovalDecision,
    _principal: Principal = Depends(require_owner),
) -> PlannedAction:
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
async def execute_action(
    task_id: str,
    action_id: str,
    _principal: Principal = Depends(require_operator),
) -> ToolExecutionResult:
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
    _principal: Principal = Depends(require_viewer),
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
    _principal: Principal = Depends(require_viewer),
) -> list[AuditEvent]:
    try:
        return hub.list_audit(task_id, limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="agent task not found") from exc


@app.get("/api/v1/command-center", response_model=CommandCenterSnapshot)
def command_center(
    limit: int = Query(default=50, ge=1, le=200),
    audit_limit: int = Query(default=50, ge=1, le=1000),
    _principal: Principal = Depends(require_viewer),
) -> CommandCenterSnapshot:
    return hub.command_center(limit=limit, audit_limit=audit_limit)


@app.get(
    "/api/v1/integrations/espocrm/schema/{entity_type}",
    response_model=EspoEntitySchema,
)
async def espocrm_schema(
    entity_type: str,
    _principal: Principal = Depends(require_viewer),
) -> EspoEntitySchema:
    try:
        return await schema_reader.read_entity(entity_type)
    except EspoSchemaNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except EspoSchemaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/api/v1/integrations/espocrm/mapping/{entity_type}",
    response_model=EspoMappingRecommendation,
)
async def espocrm_mapping(
    entity_type: str,
    _principal: Principal = Depends(require_viewer),
) -> EspoMappingRecommendation:
    try:
        return await mapping_reader.recommend(entity_type)
    except EspoSchemaNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except EspoSchemaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
