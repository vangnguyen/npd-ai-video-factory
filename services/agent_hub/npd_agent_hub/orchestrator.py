from __future__ import annotations

from dataclasses import dataclass, field

from .agents import SPECIALIST_AGENTS, select_agents
from .models import (
    ActionStatus,
    AgentDescriptor,
    AgentName,
    AgentTask,
    ApprovalDecision,
    CommandCenterReport,
    ExecutionStatus,
    PlannedAction,
    ToolExecutionResult,
)
from .tools import ToolExecutor


@dataclass
class AgentHub:
    """Control plane for planning, approval and narrowly-scoped tool execution."""

    reports: dict[str, CommandCenterReport] = field(default_factory=dict)
    tasks: dict[str, AgentTask] = field(default_factory=dict)
    execution_history: dict[str, list[ToolExecutionResult]] = field(default_factory=dict)
    executor: ToolExecutor = field(default_factory=ToolExecutor)

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
        return command_report

    def get(self, task_id: str) -> CommandCenterReport | None:
        return self.reports.get(task_id)

    def _get_action(self, task_id: str, action_id: str) -> PlannedAction:
        report = self.reports.get(task_id)
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
        report = self.reports.get(task_id)
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
        return target

    async def execute(self, task_id: str, action_id: str) -> ToolExecutionResult:
        task = self.tasks.get(task_id)
        if task is None:
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

        result = await self.executor.execute(task=task, action=action)
        action.status = (
            ActionStatus.EXECUTED
            if result.status == ExecutionStatus.SUCCEEDED
            else ActionStatus.EXECUTION_FAILED
        )
        self.execution_history.setdefault(task_id, []).append(result)
        return result


hub = AgentHub()
