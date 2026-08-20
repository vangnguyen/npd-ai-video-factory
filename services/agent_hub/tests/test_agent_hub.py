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


class CrmReadExecutor:
    def __init__(self):
        self.calls = []

    async def execute(self, *, task, action):
        self.calls.append(action.tool)
        return ToolExecutionResult(
            task_id=task.task_id,
            action_id=action.action_id,
            tool=action.tool,
            status=ExecutionStatus.SUCCEEDED,
            data={
                "total": 1,
                "list": [
                    {
                        "id": "lead-1",
                        "name": "Lead cần chăm sóc",
                        "status": "New",
                        "assignedUserId": "user-1",
                        "assignedUserName": "Sale A",
                        "modifiedAt": "2026-08-01 00:00:00",
                        "cMucDoQuanTam": "Am",
                        "hasPhone": True,
                        "hasEmail": False,
                    }
                ],
            },
        )


class AnalyticsReadExecutor:
    def __init__(self):
        self.calls = []

    async def execute(self, *, task, action):
        self.calls.append(action.tool)
        return ToolExecutionResult(
            task_id=task.task_id,
            action_id=action.action_id,
            tool=action.tool,
            status=ExecutionStatus.SUCCEEDED,
            data={
                "data_source": "EspoCRM Lead read-only",
                "period_days": 30,
                "records_analyzed": 3,
                "reported_total": 3,
                "coverage_complete": True,
                "recent_leads": 1,
                "converted_leads": 1,
                "conversion_rate_pct": 33.3,
                "assigned_leads": 3,
                "contactable_leads": 2,
                "stale_active_leads": 1,
                "by_source": [
                    {"name": "Website", "count": 3, "share_pct": 100.0}
                ],
            },
        )


def test_marketing_source_status_exposes_configuration_only():
    with TestClient(app) as client:
        response = client.get("/api/v1/integrations/marketing/status")

    assert response.status_code == 200
    assert set(response.json()) == {"crm", "meta_ads", "ga4", "social"}
    assert set(response.json().values()) <= {"configured", "not_configured", "incomplete"}


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


def test_crm_follow_up_question_routes_to_crm_and_sales_without_marketing():
    hub = AgentHub()
    report = hub.run(
        AgentTask(objective="Kiểm tra CRM và tìm các lead chưa được chăm sóc")
    )

    assert report.selected_agents == [AgentName.CRM_MANAGER, AgentName.SALES]


def test_marketing_source_report_routes_only_to_marketing_leader():
    hub = AgentHub()
    report = hub.run(
        AgentTask(objective="Báo cáo hiệu quả marketing theo nguồn trong 30 ngày")
    )

    assert report.selected_agents == [AgentName.MARKETING_LEADER]


def test_campaign_comparison_suggestion_routes_only_to_marketing_leader():
    hub = AgentHub()
    report = hub.run(
        AgentTask(
            objective=(
                "So sánh các chiến dịch Meta Ads của Bat Dong San 1 và Bat Dong San 4 "
                "trong 30 ngày theo số tiền đã chi, impressions, clicks, CTR, CPC, CPL "
                "và lead Meta."
            )
        )
    )

    assert report.selected_agents == [AgentName.MARKETING_LEADER]


def test_analyze_auto_executes_analytics_read_without_budget_write():
    executor = AnalyticsReadExecutor()
    hub = AgentHub(executor=executor)
    report = hub.run(
        AgentTask(objective="Báo cáo hiệu quả marketing theo nguồn trong 30 ngày")
    )

    analyzed = asyncio.run(hub.analyze(report.task_id))

    assert executor.calls == ["analytics.read"]
    assert analyzed.answer is not None
    assert analyzed.answer.status.value == "partial"
    assert analyzed.answer.metrics["Tỷ lệ Converted (%)"] == 33.3
    budget_write = next(
        action
        for agent_report in analyzed.reports
        for action in agent_report.actions
        if action.tool == "ads.budget.update"
    )
    assert budget_write.status.value == "proposed"
    assert budget_write in analyzed.approvals_required


def test_analyze_auto_executes_only_crm_reads_and_returns_evidence_based_answer():
    executor = CrmReadExecutor()
    hub = AgentHub(executor=executor)
    report = hub.run(
        AgentTask(objective="Kiểm tra CRM và tìm các lead chưa được chăm sóc")
    )

    analyzed = asyncio.run(hub.analyze(report.task_id))

    assert set(executor.calls) == {"crm.audit.read", "crm.leads.read"}
    assert analyzed.answer is not None
    assert analyzed.answer.status.value == "completed"
    assert analyzed.answer.metrics["Cần chăm sóc"] == 1
    assert analyzed.answer.items[0].entity_id == "lead-1"
    writes = [
        action
        for agent_report in analyzed.reports
        for action in agent_report.actions
        if action.requires_approval
    ]
    assert writes
    assert all(action.status.value == "proposed" for action in writes)
    assert len(analyzed.approvals_required) == len(writes)
    assert hub.list_audit(report.task_id)[0].event_type.value == "answer_generated"

    refreshed = asyncio.run(hub.analyze(report.task_id))
    assert len(executor.calls) == 4
    assert refreshed.answer.metrics["Cần chăm sóc"] == 1


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
    assert any(item["event_type"] == "task_created" for item in audit.json())
    assert audit.json()[0]["event_type"] == "answer_generated"

    command_center = client.get("/api/v1/command-center")
    assert command_center.status_code == 200
    command_payload = command_center.json()
    assert command_payload["storage_backend"] == "memory"
    assert any(item["task_id"] == payload["task_id"] for item in command_payload["tasks"])
