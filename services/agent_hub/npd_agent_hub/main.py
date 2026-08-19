from __future__ import annotations

from fastapi import FastAPI, HTTPException

from .models import AgentDescriptor, AgentTask, ApprovalDecision, CommandCenterReport, PlannedAction
from .orchestrator import hub


app = FastAPI(
    title="NPD Agent Hub",
    version="0.1.0",
    description="Multi-agent management control plane for marketing, content, video, social, sales and CRM.",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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
