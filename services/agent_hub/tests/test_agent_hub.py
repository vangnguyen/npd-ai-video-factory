from fastapi.testclient import TestClient

from npd_agent_hub.main import app
from npd_agent_hub.models import AgentName, AgentTask, ApprovalDecision
from npd_agent_hub.orchestrator import AgentHub


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


def test_http_surface():
    client = TestClient(app)

    assert client.get("/health").json() == {"status": "ok"}
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
