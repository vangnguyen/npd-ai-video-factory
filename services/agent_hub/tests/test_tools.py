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
        return httpx.Response(
            200,
            json={
                "total": 2,
                "list": [
                    {"id": "1", "name": "Lead A"},
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
    assert seen == {
        "method": "GET",
        "path": "/api/v1/Lead",
        "api_key": "read-only-key",
    }


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
