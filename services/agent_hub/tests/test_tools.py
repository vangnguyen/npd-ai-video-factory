import asyncio
import json

import httpx

from npd_agent_hub.config import HubSettings
from npd_agent_hub.models import ActionStatus, AgentName, AgentTask, PlannedAction
from npd_agent_hub.tools import ToolExecutor


def run(coro):
    return asyncio.run(coro)


def test_video_job_adapter_uses_existing_api_contract_and_idempotency():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["idempotency"] = request.headers.get("Idempotency-Key")
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            202,
            json={
                "job_id": "vid_1234567890123_abcdefghij",
                "status": "queued",
                "stage": "queued",
                "progress": 0,
                "status_url": "/api/v1/video-jobs/vid_1234567890123_abcdefghij",
            },
        )

    video_job = {
        "topic": "Video test Agent Hub",
        "project": "agent-hub-test",
        "video": {"duration_seconds": 30, "aspect": "9:16", "language": "vi", "template": "real-estate-short-v1"},
        "content": {
            "objective": "awareness",
            "audience": "Khách hàng thử nghiệm",
            "tone": "Rõ ràng",
            "cta": "Xem thêm",
        },
        "media": {
            "source": "local",
            "project_asset_folder": "agent-hub-test",
            "minimum_clips": 5,
            "allow_stock": False,
            "allow_ai_generation": False,
        },
    }
    task = AgentTask(objective="Tạo video test", context={"video_job": video_job})
    action = PlannedAction(
        agent=AgentName.VIDEO_PRODUCER,
        title="Tạo video job",
        description="test",
        tool="video.jobs.create",
    )
    executor = ToolExecutor(
        HubSettings(video_api_url="https://video.local"),
        transport=httpx.MockTransport(handler),
    )

    result = run(executor.execute(task=task, action=action))

    assert result.status.value == "succeeded"
    assert result.external_id == "vid_1234567890123_abcdefghij"
    assert seen["path"] == "/api/v1/video-jobs"
    assert seen["idempotency"] == f"agent-{task.task_id}-{action.action_id}"
    assert seen["body"] == video_job


def test_espocrm_lead_read_is_get_only_and_uses_api_key():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["api_key"] = request.headers.get("X-Api-Key")
        seen["select"] = request.url.params.get("select")
        return httpx.Response(
            200,
            json={
                "total": 2,
                "list": [
                    {
                        "id": "1",
                        "name": "Lead A",
                        "emailAddress": "private@example.com",
                        "phoneNumber": "0900000000",
                    },
                    {"id": "2", "name": "Lead B"},
                ],
            },
        )

    task = AgentTask(objective="Kiểm tra lead", context={"crm_max_size": 20})
    action = PlannedAction(
        agent=AgentName.SALES,
        title="Đọc lead",
        description="test",
        tool="crm.leads.read",
    )
    executor = ToolExecutor(
        HubSettings(espocrm_url="https://crm.local", espocrm_api_key="read-only-key"),
        transport=httpx.MockTransport(handler),
    )

    result = run(executor.execute(task=task, action=action))

    assert result.status.value == "succeeded"
    assert result.data["total"] == 2
    assert result.data["list"][0]["hasEmail"] is True
    assert result.data["list"][0]["hasPhone"] is True
    assert "emailAddress" not in result.data["list"][0]
    assert "phoneNumber" not in result.data["list"][0]
    assert seen["method"] == "GET"
    assert seen["path"] == "/api/v1/Lead"
    assert seen["api_key"] == "read-only-key"
    assert "modifiedAt" in seen["select"]


def test_analytics_read_returns_only_aggregated_crm_funnel_metrics():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(
            200,
            json={
                "total": 3,
                "list": [
                    {
                        "id": "1",
                        "name": "Private lead 1",
                        "status": "Converted",
                        "source": "Facebook",
                        "cDuAnQuanTam": "Project A",
                        "cMucDoQuanTam": "Nong",
                        "assignedUserId": "sale-1",
                        "createdAt": "2026-08-18 00:00:00",
                        "modifiedAt": "2026-08-19 00:00:00",
                        "emailAddress": "private@example.com",
                    },
                    {
                        "id": "2",
                        "name": "Private lead 2",
                        "status": "In Process",
                        "source": "Facebook",
                        "cDuAnQuanTam": "Project A",
                        "cMucDoQuanTam": "Am",
                        "assignedUserId": "sale-1",
                        "createdAt": "2026-07-01 00:00:00",
                        "modifiedAt": "2026-07-02 00:00:00",
                        "phoneNumber": "0900000000",
                    },
                    {
                        "id": "3",
                        "name": "Private lead 3",
                        "status": "New",
                        "source": "Website",
                        "cDuAnQuanTam": "Project B",
                        "createdAt": "2026-08-19 00:00:00",
                        "modifiedAt": "2026-08-19 00:00:00",
                    },
                ],
            },
        )

    task = AgentTask(
        objective="Báo cáo hiệu quả marketing 30 ngày",
        context={"analytics_days": 30},
    )
    action = PlannedAction(
        agent=AgentName.MARKETING_LEADER,
        title="Đọc funnel",
        description="test",
        tool="analytics.read",
    )
    executor = ToolExecutor(
        HubSettings(espocrm_url="https://crm.local", espocrm_api_key="read-only-key"),
        transport=httpx.MockTransport(handler),
    )

    result = run(executor.execute(task=task, action=action))

    assert result.status.value == "succeeded"
    assert result.data["records_analyzed"] == 3
    assert result.data["converted_leads"] == 1
    assert result.data["conversion_rate_pct"] == 33.3
    assert result.data["by_source"][0] == {
        "name": "Facebook",
        "count": 2,
        "share_pct": 66.7,
    }
    serialized = json.dumps(result.data)
    assert "Private lead" not in serialized
    assert "private@example.com" not in serialized
    assert "0900000000" not in serialized


def test_analytics_read_keeps_external_evidence_when_crm_is_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "crm.local":
            return httpx.Response(503, json={"error": "unavailable"})
        if request.url.host == "insights.internal.test":
            return httpx.Response(
                200,
                json={"metrics": {"reach": 1000, "views": 1500, "engagements": 100}},
            )
        raise AssertionError(f"unexpected request: {request.url}")

    task = AgentTask(objective="Báo cáo hiệu quả marketing 7 ngày")
    action = PlannedAction(
        agent=AgentName.MARKETING_LEADER,
        title="Đọc funnel",
        description="test",
        tool="analytics.read",
    )
    executor = ToolExecutor(
        HubSettings(
            espocrm_url="https://crm.local",
            espocrm_api_key="read-only-key",
            social_insights_url="https://insights.internal.test/read",
        ),
        transport=httpx.MockTransport(handler),
    )

    result = run(executor.execute(task=task, action=action))

    assert result.status.value == "succeeded"
    assert result.data["source_status"]["crm"] == "failed"
    assert result.data["source_status"]["social"] == "available"
    assert result.data["external_sources"]["social"]["metrics"]["reach"] == 1000


def test_n8n_write_requires_approved_action_and_uses_fixed_webhook():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url), json.loads(request.content.decode("utf-8"))))
        return httpx.Response(200, json={"execution_id": "n8n-42", "accepted": True})

    task = AgentTask(objective="Đăng nội dung đã duyệt")
    action = PlannedAction(
        agent=AgentName.SOCIAL_MEDIA,
        title="Publish",
        description="test",
        tool="social.publish",
        requires_approval=True,
    )
    executor = ToolExecutor(
        HubSettings(n8n_executor_webhook_url="https://n8n.local/webhook/agent-executor"),
        transport=httpx.MockTransport(handler),
    )

    blocked = run(executor.execute(task=task, action=action))
    assert blocked.status.value == "failed"
    assert calls == []

    action.status = ActionStatus.APPROVED
    executed = run(executor.execute(task=task, action=action))

    assert executed.status.value == "succeeded"
    assert executed.external_id == "n8n-42"
    assert len(calls) == 1
    assert calls[0][0] == "POST"
    assert calls[0][1] == "https://n8n.local/webhook/agent-executor"
    assert calls[0][2]["action"]["tool"] == "social.publish"
