from __future__ import annotations

from datetime import datetime, timezone
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


class AuditEventType(str, Enum):
    TASK_CREATED = "task_created"
    APPROVAL_DECIDED = "approval_decided"
    EXECUTION_STARTED = "execution_started"
    EXECUTION_SUCCEEDED = "execution_succeeded"
    EXECUTION_FAILED = "execution_failed"


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
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AuditEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: f"aud_{uuid4().hex[:16]}")
    task_id: str
    action_id: str | None = None
    event_type: AuditEventType
    actor: str = Field(min_length=1, max_length=100)
    detail: str | None = Field(default=None, max_length=1000)
    metadata: dict[str, object] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TaskSummary(BaseModel):
    task_id: str
    objective: str
    selected_agents: list[AgentName]
    total_actions: int
    approvals_pending: int
    executed_actions: int
    failed_actions: int
    updated_at: datetime


class CommandCenterSnapshot(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    storage_backend: str
    tasks: list[TaskSummary]
    approvals_pending: int
    execution_failures: int
    recent_audit: list[AuditEvent]
