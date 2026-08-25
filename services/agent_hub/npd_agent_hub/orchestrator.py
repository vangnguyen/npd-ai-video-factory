from __future__ import annotations

from dataclasses import dataclass, field

from .agents import SPECIALIST_AGENTS, select_agents
from .answering import synthesize_business_answer
from .attribution import AttributionService
from .campaigns import CampaignService
from .delivery_observability import AttributionDeliveryService
from .espocrm_opportunities import EspoOpportunityReader
from .experiments import ExperimentService
from .models import (
    ActionStatus,
    AgentDescriptor,
    AgentName,
    AgentTask,
    ApprovalDecision,
    AuditEvent,
    AuditEventType,
    CommandCenterReport,
    CommandCenterSnapshot,
    ExecutionStatus,
    PlannedAction,
    TaskSummary,
    ToolExecutionResult,
)
from .provider_health import ProviderHealthService
from .store import HubStore, build_store
from .tools import AUTO_READ_TOOLS, ToolExecutor


@dataclass
class AgentHub:
    """Control plane for planning, approval, persistence and controlled tool execution."""

    reports: dict[str, CommandCenterReport] = field(default_factory=dict)
    tasks: dict[str, AgentTask] = field(default_factory=dict)
    executor: ToolExecutor = field(default_factory=ToolExecutor)
    store: HubStore = field(default_factory=build_store)
    campaigns: CampaignService = field(init=False)
    attribution: AttributionService = field(init=False)
    delivery: AttributionDeliveryService = field(init=False)
    provider_health: ProviderHealthService = field(init=False)
    experiments: ExperimentService = field(init=False)
    opportunity_reader: EspoOpportunityReader = field(init=False)

    def __post_init__(self) -> None:
        # Phase 6B is planning/draft/preview only. This switch deliberately
        # stays false even when the legacy n8n executor URL exists.
        self.campaigns = CampaignService(self.store, execution_enabled=False)
        self.attribution = AttributionService(self.store)
        marketing_sources = getattr(self.executor, "marketing_sources", None)
        self.delivery = AttributionDeliveryService(
            self.store,
            self.attribution,
            getattr(self.executor, "settings", None),
        )
        self.provider_health = ProviderHealthService(self.store, self.delivery)
        self.experiments = ExperimentService(
            self.store,
            source_status_provider=getattr(
                marketing_sources, "configuration_status", None
            ),
            source_reader=marketing_sources,
        )
        self.opportunity_reader = EspoOpportunityReader(
            getattr(self.executor, "settings", None),
            transport=getattr(self.executor, "transport", None),
        )

    def list_agents(self) -> list[AgentDescriptor]:
        commander = AgentDescriptor(
            name=AgentName.COMMANDER,
            role="Nhận mục tiêu, định tuyến agent chuyên môn, gom báo cáo và kiểm soát approval.",
            capabilities=[
                "task routing",
                "cross-agent coordination",
                "priority synthesis",
                "approval control",
                "controlled tool execution",
                "persistent audit trail",
            ],
        )
        return [commander, *[agent.descriptor for agent in SPECIALIST_AGENTS.values()]]

    def run(self, task: AgentTask) -> CommandCenterReport:
        selected = select_agents(task)
        reports = [SPECIALIST_AGENTS[name].plan(task) for name in selected]
        approvals = [
            planned_action
            for report in reports
            for planned_action in report.actions
            if planned_action.requires_approval
        ]

        priorities: list[str] = []
        for report in reports:
            for priority in report.priorities:
                if priority not in priorities:
                    priorities.append(priority)

        summary = (
            f"Commander đã chọn {len(selected)} agent cho mục tiêu này. "
            f"Có {len(approvals)} hành động cần phê duyệt trước khi thực thi. "
            f"Ưu tiên đầu tiên: {priorities[0] if priorities else 'xác nhận mục tiêu và dữ liệu đầu vào.'}"
        )
        command_report = CommandCenterReport(
            task_id=task.task_id,
            objective=task.objective,
            selected_agents=selected,
            executive_summary=summary,
            reports=reports,
            approvals_required=approvals,
        )
        self.tasks[task.task_id] = task
        self.reports[task.task_id] = command_report
        self.store.save_task(task)
        self.store.save_report(command_report)
        self.store.append_audit(
            AuditEvent(
                task_id=task.task_id,
                event_type=AuditEventType.TASK_CREATED,
                actor="commander",
                detail="Agent task created and routed.",
                metadata={"selected_agents": [name.value for name in selected]},
            )
        )
        return command_report

    def get(self, task_id: str) -> CommandCenterReport | None:
        report = self.reports.get(task_id)
        if report is not None:
            return report
        report = self.store.get_report(task_id)
        if report is not None:
            self.reports[task_id] = report
        return report

    def _get_task(self, task_id: str) -> AgentTask | None:
        task = self.tasks.get(task_id)
        if task is not None:
            return task
        task = self.store.get_task(task_id)
        if task is not None:
            self.tasks[task_id] = task
        return task

    def _get_action(self, task_id: str, action_id: str) -> PlannedAction:
        report = self.get(task_id)
        if report is None:
            raise KeyError(task_id)
        for agent_report in report.reports:
            for planned_action in agent_report.actions:
                if planned_action.action_id == action_id:
                    return planned_action
        raise LookupError(action_id)

    def decide(
        self,
        task_id: str,
        action_id: str,
        decision: ApprovalDecision,
    ) -> PlannedAction:
        report = self.get(task_id)
        if report is None:
            raise KeyError(task_id)
        target = self._get_action(task_id, action_id)
        if not target.requires_approval:
            raise ValueError("action does not require approval")
        if target.status not in {
            ActionStatus.PROPOSED,
            ActionStatus.APPROVED,
            ActionStatus.EXECUTION_FAILED,
        }:
            raise ValueError(f"action cannot be approved from status={target.status.value}")

        target.status = ActionStatus.APPROVED if decision.approved else ActionStatus.REJECTED
        report.approvals_required = [
            action
            for action in report.approvals_required
            if action.action_id != action_id
        ]
        self.store.save_report(report)
        self.store.append_audit(
            AuditEvent(
                task_id=task_id,
                action_id=action_id,
                event_type=AuditEventType.APPROVAL_DECIDED,
                actor="user",
                detail=decision.note,
                metadata={
                    "approved": decision.approved,
                    "tool": target.tool,
                    "resulting_status": target.status.value,
                },
            )
        )
        return target

    async def execute(self, task_id: str, action_id: str) -> ToolExecutionResult:
        task = self._get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        report = self.get(task_id)
        if report is None:
            raise KeyError(task_id)
        action = self._get_action(task_id, action_id)

        if action.status == ActionStatus.REJECTED:
            raise ValueError("rejected action cannot be executed")
        if action.status == ActionStatus.EXECUTED:
            raise ValueError("action has already been executed")
        if action.requires_approval and action.status != ActionStatus.APPROVED:
            if action.status == ActionStatus.EXECUTION_FAILED:
                raise ValueError("failed write action requires re-approval before retry")
            raise ValueError("action requires approval before execution")

        self.store.append_audit(
            AuditEvent(
                task_id=task_id,
                action_id=action_id,
                event_type=AuditEventType.EXECUTION_STARTED,
                actor="commander",
                detail="Approved action dispatched to tool executor.",
                metadata={"tool": action.tool},
            )
        )
        result = await self.executor.execute(task=task, action=action)
        action.status = (
            ActionStatus.EXECUTED
            if result.status == ExecutionStatus.SUCCEEDED
            else ActionStatus.EXECUTION_FAILED
        )

        if action.status == ActionStatus.EXECUTION_FAILED and action.requires_approval:
            if all(item.action_id != action.action_id for item in report.approvals_required):
                report.approvals_required.append(action)

        self.store.append_execution(result)
        self.store.save_report(report)
        self.store.append_audit(
            AuditEvent(
                task_id=task_id,
                action_id=action_id,
                event_type=(
                    AuditEventType.EXECUTION_SUCCEEDED
                    if result.status == ExecutionStatus.SUCCEEDED
                    else AuditEventType.EXECUTION_FAILED
                ),
                actor="tool_executor",
                detail=result.detail,
                metadata={
                    "tool": action.tool,
                    "external_id": result.external_id,
                    "resulting_status": action.status.value,
                    "requires_reapproval": bool(
                        action.requires_approval and result.status == ExecutionStatus.FAILED
                    ),
                },
            )
        )
        return result

    async def analyze(self, task_id: str) -> CommandCenterReport:
        """Run only allowlisted reads, then turn evidence into a business answer."""
        task = self._get_task(task_id)
        report = self.get(task_id)
        if task is None or report is None:
            raise KeyError(task_id)

        for agent_report in report.reports:
            for action in agent_report.actions:
                if (
                    action.tool in AUTO_READ_TOOLS
                    and not action.requires_approval
                    and action.status
                    in {
                        ActionStatus.PROPOSED,
                        ActionStatus.EXECUTED,
                        ActionStatus.EXECUTION_FAILED,
                    }
                ):
                    if action.status == ActionStatus.EXECUTED:
                        action.status = ActionStatus.PROPOSED
                    await self.execute(task_id, action.action_id)

        executions = self.list_executions(task_id, limit=1000)
        report.answer = synthesize_business_answer(task, report, executions)
        self.store.save_report(report)
        self.store.append_audit(
            AuditEvent(
                task_id=task_id,
                event_type=AuditEventType.ANSWER_GENERATED,
                actor="commander",
                detail="Business answer synthesized from allowlisted read-only evidence.",
                metadata={
                    "status": report.answer.status.value,
                    "item_count": len(report.answer.items),
                    "successful_read_tools": sorted(
                        {
                            item.tool
                            for item in executions
                            if item.tool in AUTO_READ_TOOLS
                            and item.status == ExecutionStatus.SUCCEEDED
                        }
                    ),
                },
            )
        )
        return report

    def list_executions(self, task_id: str, limit: int = 100) -> list[ToolExecutionResult]:
        if self.get(task_id) is None:
            raise KeyError(task_id)
        return self.store.list_executions(task_id, limit)

    def list_audit(self, task_id: str, limit: int = 100) -> list[AuditEvent]:
        if self.get(task_id) is None:
            raise KeyError(task_id)
        return self.store.list_audit(task_id, limit)

    def command_center(self, *, limit: int = 50, audit_limit: int = 50) -> CommandCenterSnapshot:
        summaries: list[TaskSummary] = []
        approvals_pending = 0
        execution_failures = 0

        for task_id, updated_at in self.store.list_recent_tasks(limit):
            report = self.get(task_id)
            if report is None:
                continue
            actions = [action for agent_report in report.reports for action in agent_report.actions]
            pending = len(report.approvals_required)
            failed = sum(action.status == ActionStatus.EXECUTION_FAILED for action in actions)
            summaries.append(
                TaskSummary(
                    task_id=task_id,
                    objective=report.objective,
                    selected_agents=report.selected_agents,
                    total_actions=len(actions),
                    approvals_pending=pending,
                    executed_actions=sum(action.status == ActionStatus.EXECUTED for action in actions),
                    failed_actions=failed,
                    updated_at=updated_at,
                )
            )
            approvals_pending += pending
            execution_failures += failed

        return CommandCenterSnapshot(
            storage_backend=self.store.backend_name,
            tasks=summaries,
            approvals_pending=approvals_pending,
            execution_failures=execution_failures,
            recent_audit=self.store.list_recent_audit(audit_limit),
        )

    def storage_health(self) -> bool:
        return self.store.health()


hub = AgentHub()
