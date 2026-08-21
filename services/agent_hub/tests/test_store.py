import asyncio

import fakeredis

from npd_agent_hub.models import AgentName, AgentTask, ApprovalDecision, ExecutionStatus, ToolExecutionResult
from npd_agent_hub.orchestrator import AgentHub
from npd_agent_hub.store import MemoryHubStore, RedisHubStore


class StubExecutor:
    async def execute(self, *, task, action):
        return ToolExecutionResult(
            task_id=task.task_id,
            action_id=action.action_id,
            tool=action.tool,
            status=ExecutionStatus.SUCCEEDED,
            external_id="persisted-execution-1",
        )


class FailingExecutor:
    async def execute(self, *, task, action):
        return ToolExecutionResult(
            task_id=task.task_id,
            action_id=action.action_id,
            tool=action.tool,
            status=ExecutionStatus.FAILED,
            detail="simulated failure",
        )


def test_memory_store_restores_task_after_hub_recreation():
    store = MemoryHubStore()
    first_hub = AgentHub(store=store)
    report = first_hub.run(AgentTask(objective="Quản lý marketing và CRM"))

    restarted_hub = AgentHub(store=store)
    restored = restarted_hub.get(report.task_id)

    assert restored is not None
    assert restored.task_id == report.task_id
    assert restored.objective == report.objective
    assert restarted_hub.list_audit(report.task_id)[0].event_type.value == "task_created"


def test_redis_store_round_trip_and_recent_task_index():
    redis_client = fakeredis.FakeRedis(decode_responses=True)
    store = RedisHubStore(client=redis_client, namespace="test:agent-hub")
    first_hub = AgentHub(store=store)
    report = first_hub.run(AgentTask(objective="Theo dõi lead CRM"))

    restarted_hub = AgentHub(
        store=RedisHubStore(client=redis_client, namespace="test:agent-hub")
    )
    restored = restarted_hub.get(report.task_id)
    snapshot = restarted_hub.command_center()

    assert restored is not None
    assert restored.task_id == report.task_id
    assert snapshot.storage_backend == "redis"
    assert snapshot.tasks[0].task_id == report.task_id
    assert snapshot.recent_audit[0].event_type.value == "task_created"


def test_approval_execution_and_audit_are_persisted():
    store = MemoryHubStore()
    hub = AgentHub(store=store, executor=StubExecutor())
    report = hub.run(
        AgentTask(
            objective="Đăng nội dung đã duyệt",
            preferred_agents=[AgentName.SOCIAL_MEDIA],
        )
    )
    publish = next(
        action
        for agent_report in report.reports
        for action in agent_report.actions
        if action.tool == "social.publish"
    )

    hub.decide(
        report.task_id,
        publish.action_id,
        ApprovalDecision(approved=True, note="Owner approved"),
    )
    result = asyncio.run(hub.execute(report.task_id, publish.action_id))

    assert result.status.value == "succeeded"
    executions = hub.list_executions(report.task_id)
    assert executions[0].external_id == "persisted-execution-1"
    event_types = [event.event_type.value for event in hub.list_audit(report.task_id)]
    assert event_types[:4] == [
        "execution_succeeded",
        "execution_started",
        "approval_decided",
        "task_created",
    ]


def test_failed_write_returns_to_pending_approval_in_command_center():
    store = MemoryHubStore()
    hub = AgentHub(store=store, executor=FailingExecutor())
    report = hub.run(
        AgentTask(
            objective="Publish social content",
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
    asyncio.run(hub.execute(report.task_id, publish.action_id))
    snapshot = hub.command_center()

    assert publish.status.value == "execution_failed"
    assert snapshot.approvals_pending == 1
    assert snapshot.execution_failures == 1
    assert snapshot.tasks[0].approvals_pending == 1
