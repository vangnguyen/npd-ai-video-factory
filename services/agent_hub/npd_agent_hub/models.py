from __future__ import annotations

from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class AgentName(str, Enum):
    COMMANDER = "commander"
    MARKETING_LEADER = "marketing_leader"
    CONTENT_TREND = "content_trend"
    VIDEO_PRODUCER = "video_producer"
    SOCIAL_MEDIA = "social_media"
    SALES = "sales"
    CRM_MANAGER = "crm_manager"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ActionStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    EXECUTION_FAILED = "execution_failed"


class ExecutionStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class AgentTask(BaseModel):
    task_id: str = Field(default_factory=lambda: f"agt_{uuid4().hex[:16]}")
    objective: str = Field(min_length=3, max_length=4000)
    context: dict[str, object] = Field(default_factory=dict)
    constraints: list[str] = Field(default_factory=list)
    preferred_agents: list[AgentName] = Field(default_factory=list)


class PlannedAction(BaseModel):
    action_id: str = Field(default_factory=lambda: f"act_{uuid4().hex[:12]}")
    agent: AgentName
    title: str
    description: str
    tool: str
    payload: dict[str, object] = Field(default_factory=dict)
    risk: RiskLevel = RiskLevel.LOW
    requires_approval: bool = False
    approval_reason: str | None = None
    status: ActionStatus = ActionStatus.PROPOSED


class AgentReport(BaseModel):
    agent: AgentName
    summary: str
    priorities: list[str] = Field(default_factory=list)
    actions: list[PlannedAction] = Field(default_factory=list)
    metrics_to_watch: list[str] = Field(default_factory=list)
    handoffs: list[AgentName] = Field(default_factory=list)


class CommandCenterReport(BaseModel):
    task_id: str
    objective: str
    selected_agents: list[AgentName]
    executive_summary: str
    reports: list[AgentReport]
    approvals_required: list[PlannedAction] = Field(default_factory=list)


class ApprovalDecision(BaseModel):
    approved: bool
    note: str | None = None


class AgentDescriptor(BaseModel):
    name: AgentName
    role: str
    capabilities: list[str]


class ToolExecutionResult(BaseModel):
    task_id: str
    action_id: str
    tool: str
    status: ExecutionStatus
    detail: str | None = None
    external_id: str | None = None
    data: dict[str, object] = Field(default_factory=dict)
