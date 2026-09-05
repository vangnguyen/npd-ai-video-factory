from __future__ import annotations

import asyncio
import importlib
from datetime import datetime, timedelta, timezone

import fakeredis
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from npd_agent_hub.auth import authorizer
from npd_agent_hub.config import HubSettings
from npd_agent_hub.models import AgentName, AgentTask, AnswerStatus, AuditEventType
from npd_agent_hub.nba_review import NBAReviewService
from npd_agent_hub.orchestrator import AgentHub
from npd_agent_hub.phase9_marketing_review import REVIEW_AGENTS, WORKFLOW_VERSION
from npd_agent_hub.sales_intelligence_models import SalesIntelligencePreviewRequest
from npd_agent_hub.store import MemoryHubStore, RedisHubStore
from test_sales_nba_review import AS_OF, fixture as signed_sales_fixture


class ForbiddenExternalExecutor:
    """Any accidental CRM/provider/tool dispatch must fail the pilot test."""

    def __init__(self):
        self.settings = HubSettings()
        self.calls = 0

    async def execute(self, **_kwargs):
        self.calls += 1
        raise AssertionError("Phase 9 review must not dispatch external tools")


def pilot_task(*cases: SalesIntelligencePreviewRequest) -> AgentTask:
    return AgentTask(
        objective="Rà soát evidence và việc chăm sóc khách để Marketing/Sales xem xét",
        context={"phase9_review": {"cases": [case.model_dump(mode="json") for case in cases]}},
    )


def prepared_hub():
    store, _journeys, delivery, case = signed_sales_fixture()
    executor = ForbiddenExternalExecutor()
    hub = AgentHub(store=store, executor=executor)
    hub.delivery = delivery
    return hub, case, executor


def analyze(hub: AgentHub, task: AgentTask):
    planned = hub.run(task)
    return asyncio.run(hub.analyze(planned.task_id))


def test_pilot_routes_existing_roles_and_returns_actual_phase9_evidence():
    hub, case, executor = prepared_hub()
    before_touchpoints = hub.store.list_touchpoints(limit=100)
    before_heartbeats = hub.store.list_attribution_heartbeat_receipts(producer="sales_hub", limit=100)
    before_reviews = NBAReviewService(hub.store, hub.journeys).summary()
    task = pilot_task(case)
    result = analyze(hub, task)

    assert result.selected_agents == list(REVIEW_AGENTS)
    assert [report.agent for report in result.reports] == list(REVIEW_AGENTS)
    assert result.reports[0].handoffs == [AgentName.SALES]
    assert result.reports[1].handoffs == [AgentName.MARKETING_LEADER]
    assert result.reports[2].handoffs == [AgentName.COMMANDER]
    assert result.approvals_required == []
    assert all(report.actions == [] for report in result.reports)
    answer = result.answer
    assert answer is not None
    assert answer.metrics["workflow_version"] == WORKFLOW_VERSION
    assert answer.metrics["evaluated_subjects"] == 1
    assert answer.metrics["verified_sla_subjects"] == 1
    assert answer.metrics["verified_breach_subjects"] == 1
    assert answer.metrics["high_priority_reviews"] == 1
    assert answer.metrics["execution_enabled"] is False
    assert answer.metrics["external_writes_enabled"] is False
    assert answer.metrics["customer_contact_enabled"] is False
    item = answer.items[0]
    assert item.entity_id == "lead:lead-001"
    assert item.priority == "high"
    assert item.details["recommendation_version"] == "phase-9b-nba-v2"
    assert item.details["first_response_sla"] == "breached"
    assert item.details["completeness_verified"] is True
    assert item.details["customer_contact_enabled"] is False
    assert item.reason
    assert any(ref.startswith("ahr_") for ref in answer.evidence)
    assert "LLM" in " ".join(answer.caveats)
    assert executor.calls == 0
    assert hub.list_executions(task.task_id) == []
    assert hub.store.list_touchpoints(limit=100) == before_touchpoints
    assert hub.store.list_attribution_heartbeat_receipts(producer="sales_hub", limit=100) == before_heartbeats
    assert NBAReviewService(hub.store, hub.journeys).summary() == before_reviews
    # The normal Commander task/report/audit persistence is intentional.
    assert hub.store.get_task(task.task_id) == task
    assert hub.store.get_report(task.task_id) == result
    assert [row.event_type for row in hub.list_audit(task.task_id)]
    assert any(row.event_type == AuditEventType.ANSWER_GENERATED for row in hub.list_audit(task.task_id))


def test_missing_completeness_is_not_converted_to_verified_breach_or_escalation():
    hub, case, executor = prepared_hub()
    unsigned = SalesIntelligencePreviewRequest(
        subject_ref=case.subject_ref, observations=[], as_of=case.as_of
    )
    result = analyze(hub, pilot_task(unsigned))
    answer = result.answer
    assert answer is not None
    assert answer.status == AnswerStatus.PARTIAL
    assert answer.metrics["verified_sla_subjects"] == 0
    assert answer.metrics["verified_breach_subjects"] == 0
    assert answer.metrics["high_priority_reviews"] == 0
    item = answer.items[0]
    assert item.details["first_response_sla"] == "overdue_missing_evidence"
    assert item.details["completeness_verified"] is False
    assert "sales_sla_completeness" in item.details["missing_inputs"]
    assert executor.calls == 0


def test_duplicate_cases_are_reviewed_once_and_failures_do_not_get_a_fake_score():
    hub, case, executor = prepared_hub()
    missing = SalesIntelligencePreviewRequest(
        subject_ref="lead:missing", observations=[], as_of=case.as_of
    )
    result = analyze(hub, pilot_task(missing, case, case))
    answer = result.answer
    assert answer is not None
    assert answer.status == AnswerStatus.PARTIAL
    assert answer.metrics["requested_cases"] == 3
    assert answer.metrics["unique_subjects"] == 2
    assert answer.metrics["duplicate_cases"] == 1
    assert answer.metrics["evaluated_subjects"] == 1
    assert answer.metrics["failed_subjects"] == 1
    assert len(answer.items) == 2
    assert answer.items[0].entity_id == case.subject_ref
    failed = answer.items[1]
    assert failed.entity_id == "lead:missing"
    assert failed.details["evaluation_status"] == "not_found"
    assert "lead_score" not in failed.details
    assert failed.priority == "normal"
    assert executor.calls == 0


def test_empty_evidence_store_fails_the_business_answer_without_crm_fallback():
    executor = ForbiddenExternalExecutor()
    hub = AgentHub(store=MemoryHubStore(), executor=executor)
    case = SalesIntelligencePreviewRequest(
        subject_ref="lead:missing", observations=[], as_of=AS_OF
    )
    result = analyze(hub, pilot_task(case))
    assert result.answer.status == AnswerStatus.FAILED
    assert result.answer.metrics["evaluated_subjects"] == 0
    assert result.answer.metrics["failed_subjects"] == 1
    assert result.answer.metrics["high_priority_reviews"] == 0
    assert executor.calls == 0


def test_invalid_signed_sales_evidence_fails_closed_without_error_detail_leak():
    hub, case, executor = prepared_hub()
    # Keep the shape valid but invalidate the signed receipt binding.
    raw = case.model_dump(mode="json")
    raw["completeness_proof"]["claim"]["record_count"] = 1
    task = AgentTask(objective="Rà soát evidence", context={"phase9_review": {"cases": [raw]}})
    result = analyze(hub, task)
    assert result.answer.status == AnswerStatus.FAILED
    assert result.answer.items[0].details["evaluation_status"] == "invalid_evidence"
    assert "lead_score" not in result.answer.items[0].details
    assert executor.calls == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"cases": []},
        {"cases": [{"subject_ref": "lead:user@example.com", "observations": [], "as_of": AS_OF.isoformat()}]},
        {"cases": [{"subject_ref": "lead:lead-001", "observations": [], "as_of": "2026-09-02T14:00:00"}]},
        {"cases": [{"subject_ref": "lead:lead-001", "observations": [], "as_of": AS_OF.isoformat()}] * 21},
    ],
)
def test_invalid_context_is_rejected_before_task_persistence(payload):
    with pytest.raises(ValidationError):
        AgentTask(objective="Rà soát evidence", context={"phase9_review": payload})


def test_conflicting_duplicate_and_mixed_as_of_are_rejected():
    _hub, case, _executor = prepared_hub()
    changed = case.model_copy(update={"as_of": case.as_of + timedelta(minutes=1)})
    with pytest.raises(ValidationError):
        pilot_task(case, changed)
    unsigned = SalesIntelligencePreviewRequest(
        subject_ref=case.subject_ref, observations=[], as_of=case.as_of
    )
    with pytest.raises(ValidationError):
        pilot_task(case, unsigned)


def test_repeat_analyze_recomputes_the_same_evidence_without_creating_review_votes():
    hub, case, executor = prepared_hub()
    task = pilot_task(case)
    first = analyze(hub, task).answer.model_dump(mode="json", exclude={"generated_at"})
    second = asyncio.run(hub.analyze(task.task_id)).answer.model_dump(mode="json", exclude={"generated_at"})
    assert first == second
    assert NBAReviewService(hub.store, hub.journeys).summary().total_reviews == 0
    assert len(hub.store.list_recent_tasks(100)) == 1
    assert executor.calls == 0


def test_redis_task_and_report_recover_without_changing_evidence_contract():
    source_store, _journeys, _delivery, signed_case = signed_sales_fixture()
    client = fakeredis.FakeRedis(decode_responses=True)
    store = RedisHubStore(client=client, namespace="phase9-marketing-pilot-test")
    for row in source_store.list_touchpoints(limit=100):
        store.append_touchpoint(row)
    unsigned = SalesIntelligencePreviewRequest(
        subject_ref=signed_case.subject_ref, observations=[], as_of=signed_case.as_of
    )
    task = pilot_task(unsigned)
    first_hub = AgentHub(store=store, executor=ForbiddenExternalExecutor())
    first = analyze(first_hub, task)
    recovered_hub = AgentHub(store=store, executor=ForbiddenExternalExecutor())
    assert recovered_hub.get(task.task_id) == first
    second = asyncio.run(recovered_hub.analyze(task.task_id))
    assert second.answer.metrics == first.answer.metrics
    assert second.answer.items == first.answer.items
    assert len(store.list_touchpoints(limit=100)) == 1


def test_other_agent_task_modes_preserve_existing_routing():
    hub = AgentHub(store=MemoryHubStore(), executor=ForbiddenExternalExecutor())
    task = AgentTask(
        objective="Chuẩn bị nội dung video", preferred_agents=[AgentName.CONTENT_TREND]
    )
    result = hub.run(task)
    assert AgentName.CONTENT_TREND in result.selected_agents
    assert any(report.actions for report in result.reports)
    assert "phase9_review" not in task.context


def test_existing_task_api_exposes_pilot_with_operator_rbac_and_viewer_read(monkeypatch):
    main_module = importlib.import_module("npd_agent_hub.main")
    hub, case, executor = prepared_hub()
    monkeypatch.setattr(main_module, "hub", hub)
    monkeypatch.setattr(
        authorizer,
        "settings",
        HubSettings(
            auth_mode="static_token", viewer_token="viewer-secret",
            operator_token="operator-secret", owner_token="owner-secret",
        ),
    )
    client = TestClient(main_module.app)
    viewer = {"Authorization": "Bearer viewer-secret"}
    operator = {"Authorization": "Bearer operator-secret"}
    payload = pilot_task(case).model_dump(mode="json")
    assert client.post("/api/v1/agent-tasks", json=payload).status_code == 401
    assert client.post("/api/v1/agent-tasks", json=payload, headers=viewer).status_code == 403
    created = client.post("/api/v1/agent-tasks", json=payload, headers=operator)
    assert created.status_code == 200
    body = created.json()
    assert body["selected_agents"] == [name.value for name in REVIEW_AGENTS]
    assert body["answer"]["metrics"]["verified_breach_subjects"] == 1
    assert body["approvals_required"] == []
    assert created.headers["cache-control"] == "no-store"
    task_id = body["task_id"]
    fetched = client.get(f"/api/v1/agent-tasks/{task_id}", headers=viewer)
    assert fetched.status_code == 200
    assert fetched.json()["answer"]["items"][0]["details"]["customer_contact_enabled"] is False
    assert client.post(f"/api/v1/agent-tasks/{task_id}/analyze", headers=viewer).status_code == 403
    assert client.post(f"/api/v1/agent-tasks/{task_id}/analyze", headers=operator).status_code == 200
    assert client.post(f"/api/v1/agent-tasks/{task_id}/actions/absent/execute", headers=operator).status_code == 404
    assert executor.calls == 0


def test_invalid_phase9_task_api_returns_422_and_does_not_save_task(monkeypatch):
    main_module = importlib.import_module("npd_agent_hub.main")
    hub = AgentHub(store=MemoryHubStore(), executor=ForbiddenExternalExecutor())
    monkeypatch.setattr(main_module, "hub", hub)
    monkeypatch.setattr(
        authorizer, "settings",
        HubSettings(auth_mode="static_token", operator_token="operator-secret", owner_token="owner-secret", viewer_token="viewer-secret"),
    )
    client = TestClient(main_module.app)
    response = client.post(
        "/api/v1/agent-tasks",
        headers={"Authorization": "Bearer operator-secret"},
        json={"objective": "Rà soát evidence", "context": {"phase9_review": {"cases": []}}},
    )
    assert response.status_code == 422
    assert hub.store.list_recent_tasks(100) == []
