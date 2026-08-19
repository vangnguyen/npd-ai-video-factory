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
    PlannedAction,
)


@dataclass
class AgentHub:
    """In-process control plane for planning, approval and future connector execution.

    This MVP deliberately stops at approval. Tool adapters (n8n, EspoCRM,
    analytics, social publishers and the video API) can consume approved actions
    without giving the planning layer unrestricted write access.
    """

    reports: dict[str, CommandCenterReport] = field(default_factory=dict)

    def list_agents(self) -> list[AgentDescriptor]:
        commander = AgentDescriptor(
            name=AgentName.COMMANDER,
            role="Nhận mục tiêu, định tuyến agent chuyên môn, gom báo cáo và kiểm soát approval.",
            capabilities=[
                "task routing",
                "cross-agent coordination",
                "priority synthesis",
                "approval control",
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

        priorities = []
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
        self.reports[task.task_id] = command_report
        return command_report

    def get(self, task_id: str) -> CommandCenterReport | None:
        return self.reports.get(task_id)

    def decide(
        self,
        task_id: str,
        action_id: str,
        decision: ApprovalDecision,
    ) -> PlannedAction:
        report = self.reports.get(task_id)
        if report is None:
            raise KeyError(task_id)

        target: PlannedAction | None = None
        for agent_report in report.reports:
            for planned_action in agent_report.actions:
                if planned_action.action_id == action_id:
                    target = planned_action
                    break
            if target is not None:
                break

        if target is None:
            raise LookupError(action_id)
        if not target.requires_approval:
            raise ValueError("action does not require approval")

        target.status = ActionStatus.APPROVED if decision.approved else ActionStatus.REJECTED
        report.approvals_required = [
            action
            for action in report.approvals_required
            if action.status == ActionStatus.PROPOSED
        ]
        return target


hub = AgentHub()
