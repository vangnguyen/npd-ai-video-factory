import asyncio

from fastapi.testclient import TestClient

from npd_agent_hub.main import app
from npd_agent_hub.models import (
    AgentName,
    AgentTask,
    ApprovalDecision,
    ExecutionStatus,
    ToolExecutionResult,
)
from npd_agent_hub.orchestrator import AgentHub


class StubExecutor:
    def __init__(self):
        self.calls = []

    async def execute(self, *, task, action):
        self.calls.append((task.task_id, action.action_id, action.tool))
        return ToolExecutionResult(
            task_id=task.task_id,
            action_id=action.action_id,
            tool=action.tool,
            status=ExecutionStatus.SUCCEEDED,
            external_id="stub-1",
        )


class FailOnceExecutor:
    def __init__(self):
        self.calls = 0

    async def execute(self, *, task, action):
        self.calls += 1
        return ToolExecutionResult(
            task_id=task.task_id,
            action_id=action.action_id,
            tool=action.tool,
            status=ExecutionStatus.FAILED if self.calls == 1 else ExecutionStatus.SUCCEEDED,
            detail="simulated partial failure" if self.calls == 1 else None,
        )


def test_broad_objective_routes_to_all_specialists():
    hub = AgentHub()
    report = hub.run(AgentTask(objective="Quản lý công việc toàn bộ hệ thống marketing và sales"))

    assert report.selected_agents == [
        AgentName.MARKETING_LEADER,
        AgentName.CONTENT_TREND,
        AgentName.VIDEO_PRODUCER,
        AgentName.SOCIAL_MEDIA,
        AgentName.SALES,
        AgentName.CRM_MANAGER,
    ]
    assert report.approvals_required
    assert all(action.requires_approval for action in report.approvals_required)


def test_video_task_routes_to_video_and_social_domain():
    hub = AgentHub()
    report = hub.run(AgentTask(objective="Tạo video TikTok từ trend AI mới"))

    assert AgentName.VIDEO_PRODUCER in report.selected_agents
    assert AgentName.SOCIAL_MEDIA in report.selected_agents
    assert AgentName.CONTENT_TREND in report.selected_agents


def test_approval_changes_action_status():
    hub = AgentHub()
    report = hub.run(AgentTask(objective="Quản lý công việc toàn bộ hệ thống"))
    target = report.approvals_required[0]

    decided = hub.decide(
        report.task_id,
        target.action_id,
        decision=ApprovalDecision(approved=True),
    )

    assert decided.status.value == "approved"
    assert all(action.action_id != target.action_id for action in report.approvals_required)


def test_write_execution_is_blocked_until_commander_approval():
    executor = StubExecutor()
    hub = AgentHub(executor=executor)
    report = hub.run(
        AgentTask(
            objective="Đăng video lên TikTok",
            preferred_agents=[AgentName.SOCIAL_MEDIA],
        )
    )
    publish = next(
        action
        for agent_report in report.reports
        for action in agent_report.actions
        if action.tool == "social.publish"
    )

    try:
        asyncio.run(hub.execute(report.task_id, publish.action_id))
        assert False, "execution should have been blocked before approval"
    except ValueError as exc:
        assert "requires approval" in str(exc)
    assert executor.calls == []

    hub.decide(report.task_id, publish.action_id, ApprovalDecision(approved=True))
    result = asyncio.run(hub.execute(report.task_id, publish.action_id))

    assert result.status.value == "succeeded"
    assert publish.status.value == "executed"
    assert executor.calls == [(report.task_id, publish.action_id, "social.publish")]


def test_failed_write_requires_reapproval_before_retry():
    executor = FailOnceExecutor()
    hub = AgentHub(executor=executor)
    report = hub.run(
        AgentTask(
            objective="Đăng video đã duyệt",
            preferred_agents=[AgentName.SOCIAL_MEDIA],
        )
    )
    publish = next(
        action
        for agent_report in report.reports
        for action in agent_report.actions
        if action.tool == "social.publish"
    )

    hub.decide(report.task_id, publish.action_id, ApprovalDecision(approved=True))
    first = asyncio.run(hub.execute(report.task_id, publish.action_id))
    assert first.status.value == "failed"
    assert publish.status.value == "execution_failed"

    try:
        asyncio.run(hub.execute(report.task_id, publish.action_id))
        assert False, "failed write should require re-approval"
    except ValueError as exc:
        assert "re-approval" in str(exc)
    assert executor.calls == 1

    hub.decide(report.task_id, publish.action_id, ApprovalDecision(approved=True))
    second = asyncio.run(hub.execute(report.task_id, publish.action_id))
    assert second.status.value == "succeeded"
    assert publish.status.value == "executed"
    assert executor.calls == 2


def test_http_surface():
    client = TestClient(app)

    assert client.get("/health").json() == {"status": "ok"}
    ready = client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"

    agents = client.get("/api/v1/agents")
    assert agents.status_code == 200
    assert len(agents.json()) == 7

    created = client.post(
        "/api/v1/agent-tasks",
        json={"objective": "Theo dõi CRM và lead sales"},
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["task_id"].startswith("agt_")
    assert "sales" in payload["selected_agents"]
    assert "crm_manager" in payload["selected_agents"]

    audit = client.get(f"/api/v1/agent-tasks/{payload['task_id']}/audit")
    assert audit.status_code == 200
    assert audit.json()[0]["event_type"] == "task_created"

    command_center = client.get("/api/v1/command-center")
    assert command_center.status_code == 200
    command_payload = command_center.json()
    assert command_payload["storage_backend"] == "memory"
    assert any(item["task_id"] == payload["task_id"] for item in command_payload["tasks"])
