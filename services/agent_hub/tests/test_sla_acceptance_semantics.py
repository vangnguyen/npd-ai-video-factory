"""RCA12A: truthful missing-clock output is not overdue business coverage."""
from __future__ import annotations

import asyncio
from datetime import timedelta, timezone
import hashlib
import importlib
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from npd_agent_hub.attribution_models import TouchpointEvent
from npd_agent_hub.auth import authorizer
from npd_agent_hub.campaign_models import SalesHandoff
from npd_agent_hub.config import HubSettings
from npd_agent_hub.journeys import JourneyService
from npd_agent_hub.models import AgentTask, AnswerStatus, AuditEvent, AuditEventType
from npd_agent_hub.orchestrator import AgentHub
from npd_agent_hub.sales_intelligence import SalesIntelligenceService
from npd_agent_hub.sales_intelligence_models import SalesIntelligencePreviewRequest, SalesSLAStatus
from npd_agent_hub.sales_sla_contract import (
    SalesSLAStatus as SharedStatus, report_sla_fields, validate_first_response_sla,
)
from test_phase9_marketing_review import ForbiddenExternalExecutor, pilot_task
from test_sales_intelligence import BASE, activity, build_store
from npd_agent_hub.sales_intelligence_models import SalesActivityType

FIXTURE = Path(__file__).with_name("fixtures") / "sla_uat_75f186d4.json"


def production_shaped_store():
    fixture = json.loads(FIXTURE.read_bytes())
    store, campaign = build_store(with_lead_start=False)
    campaign = campaign.model_copy(update={
        "campaign_id": fixture["campaign_id"],
        "sales_handoff": SalesHandoff(**fixture["sales_handoff"]),
    })
    store.save_campaign(campaign)
    for event in fixture["touchpoints"]:
        store.append_touchpoint(TouchpointEvent.model_validate(event))
    case = SalesIntelligencePreviewRequest.model_validate(fixture["input_case"])
    return store, case


def assess(snapshot):
    fields = {**report_sla_fields(snapshot), "completeness_verified": snapshot.completeness_verified}
    return fields, validate_first_response_sla(fields, report_as_of=snapshot.as_of.isoformat())


def test_exact_retained_sla_inputs_reproduce_not_evaluable_without_inventing_clock():
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == "e3fd8e010b5ec4b8951ece83a1dfe39ad2b147f9d0ee4d54ef75e1f54957dc3c"
    store, case = production_shaped_store()
    snapshot = SalesIntelligenceService(store).preview(case)
    assert SalesSLAStatus is SharedStatus
    assert snapshot.first_response_sla.status == SalesSLAStatus.NOT_EVALUABLE
    assert snapshot.first_response_sla.target_minutes == 15
    assert snapshot.lead_start_at is None
    assert snapshot.first_response_sla.deadline_at is None
    assert "lead_start" in snapshot.missing_inputs
    fields, result = assess(snapshot)
    assert result["truthful"] is True
    assert result["classification"] == "SLA_CLOCK_UNAVAILABLE"
    assert result["overdue_missing_evidence_covered"] is False
    fields["first_response_sla"] = "overdue_missing_evidence"
    assert validate_first_response_sla(fields, report_as_of=case.as_of.isoformat())["truthful"] is False


@pytest.mark.parametrize("minutes,observed_minutes,expected", [
    (60, 10, "met"), (60, 30, "late"),
    (14, None, "pending"), (15, None, "pending"), (16, None, "overdue_missing_evidence"),
])
def test_evaluable_response_matrix_uses_campaign_clock_and_exact_deadline(minutes, observed_minutes, expected):
    store, campaign = build_store()
    observations = [] if observed_minutes is None else [activity(
        "act-response", SalesActivityType.FIRST_RESPONSE,
        BASE + timedelta(minutes=observed_minutes), campaign.campaign_id,
    )]
    request = SalesIntelligencePreviewRequest(subject_ref="lead:lead-001", observations=observations,
                                            as_of=BASE + timedelta(minutes=minutes))
    snapshot = SalesIntelligenceService(store).preview(request)
    assert snapshot.first_response_sla.status.value == expected
    assert snapshot.first_response_sla.deadline_at == BASE + timedelta(minutes=15)
    _, result = assess(snapshot)
    assert result["truthful"] is True
    assert result["overdue_missing_evidence_covered"] == (expected == "overdue_missing_evidence")
    assert snapshot.completeness_verified is False


def test_missing_policy_is_genuinely_not_evaluable(monkeypatch):
    store, _ = build_store()
    monkeypatch.setattr(store, "get_campaign", lambda _: None)
    snapshot = SalesIntelligenceService(store).preview(SalesIntelligencePreviewRequest(
        subject_ref="lead:lead-001", as_of=BASE + timedelta(days=1)))
    assert snapshot.first_response_sla.status.value == "not_evaluable"
    assert snapshot.first_response_sla.target_minutes is None
    _, result = assess(snapshot)
    assert result["truthful"] is True
    assert result["classification"] == "SLA_POLICY_UNAVAILABLE"
    assert result["overdue_missing_evidence_covered"] is False


@pytest.mark.parametrize("as_of", ["not-a-timestamp", "2026-09-01T08:30:00"])
def test_malformed_or_timezone_naive_evaluation_is_rejected(as_of):
    with pytest.raises(ValidationError):
        SalesIntelligencePreviewRequest(subject_ref="lead:lead-001", as_of=as_of)


def test_utc_ict_boundary_does_not_change_deadline_ordering():
    store, _ = build_store()
    ict = timezone(timedelta(hours=7))
    for offset, expected in [(0, "pending"), (1, "overdue_missing_evidence")]:
        as_of = (BASE + timedelta(minutes=15, microseconds=offset)).astimezone(ict)
        snapshot = SalesIntelligenceService(store).preview(SalesIntelligencePreviewRequest(
            subject_ref="lead:lead-001", as_of=as_of))
        assert snapshot.first_response_sla.status.value == expected
        assert assess(snapshot)[1]["truthful"] is True


@pytest.mark.parametrize("wrong_subject,stale", [(True, False), (False, True)])
def test_wrong_subject_or_pre_clock_evidence_cannot_satisfy_response_sla(wrong_subject, stale):
    store, campaign = build_store()
    observation = activity("act-untrusted", SalesActivityType.FIRST_RESPONSE,
                           BASE + timedelta(minutes=-1 if stale else 1), campaign.campaign_id,
                           lead_id="another-lead" if wrong_subject else "lead-001")
    snapshot = SalesIntelligenceService(store).preview(SalesIntelligencePreviewRequest(
        subject_ref="lead:lead-001", observations=[observation], as_of=BASE + timedelta(minutes=16)))
    assert snapshot.untrusted_activity_count == 1
    assert snapshot.first_response_sla.status.value == "overdue_missing_evidence"
    assert snapshot.first_response_sla.evidence_refs == []
    assert assess(snapshot)[1]["truthful"] is True


def test_stale_completeness_watermark_never_confirms_an_overdue_breach():
    from test_sales_completeness import delivery_service, proof_for
    store, campaign = build_store()
    delivery = delivery_service(store)
    proof = proof_for(delivery, campaign_id=campaign.campaign_id, observations=[],
                      covered_activity_types=[SalesActivityType.FIRST_RESPONSE],
                      complete_through=BASE + timedelta(minutes=5))
    snapshot = SalesIntelligenceService(store, JourneyService(store), delivery).preview(
        SalesIntelligencePreviewRequest(subject_ref="lead:lead-001", as_of=BASE + timedelta(minutes=60),
                                        completeness_proof=proof))
    assert snapshot.completeness_verified is True
    assert snapshot.first_response_sla.status.value == "overdue_missing_evidence"
    assert snapshot.first_response_sla.completeness_receipt_id is None
    assert assess(snapshot)[1]["truthful"] is True


def test_terminal_internal_answer_and_audit_timestamps_never_create_business_sla_clock():
    store, case = production_shaped_store()
    executor = ForbiddenExternalExecutor()
    local_hub = AgentHub(store=store, executor=executor)
    task = pilot_task(case)
    local_hub.run(task)
    report = asyncio.run(local_hub.analyze(task.task_id))
    report.answer.status = AnswerStatus.COMPLETED
    store.save_report(report)
    store.append_audit(AuditEvent(task_id=task.task_id, event_type=AuditEventType.ANSWER_GENERATED,
                                 actor="commander", created_at=case.as_of - timedelta(days=30)))
    snapshot = SalesIntelligenceService(store).preview(case)
    assert snapshot.first_response_sla.status.value == "not_evaluable"
    assert snapshot.first_response_sla.clock_start_at is None
    assert report.answer.items[0].details["first_response_sla_reason"] == "SLA_CLOCK_UNAVAILABLE"
    assert executor.calls == 0


@pytest.mark.parametrize("field,value", [
    ("first_response_sla_deadline_at", None),
    ("first_response_sla_deadline_at", "bad-time"),
    ("first_response_sla_clock_start_at", "2026-09-01T08:00:00"),
    ("first_response_sla_clock_basis", "opportunity_stage_changed"),
    ("first_response_sla_clock_basis", []),
    ("first_response_sla_policy_source", "task_created_at"),
    ("first_response_sla_policy_available", False),
    ("first_response_sla_target_minutes", True),
    ("first_response_sla_target_minutes", 0),
    ("first_response_sla_target_minutes", 10**100),
    ("first_response_sla", "not_evaluable"),
    ("first_response_sla", []),
    ("first_response_sla_completeness_covered", True),
    ("first_response_sla_reason", "SLA_CLOCK_UNAVAILABLE"),
    ("sales_sla_semantics_version", "stale-v0"),
    ("sla_evaluation_as_of", "2026-09-01T08:14:00Z"),
])
def test_sla_basis_and_enum_tamper_fail_closed(field, value):
    store, _ = build_store()
    snapshot = SalesIntelligenceService(store).preview(SalesIntelligencePreviewRequest(
        subject_ref="lead:lead-001", as_of=BASE + timedelta(minutes=16)))
    fields, _ = assess(snapshot)
    fields[field] = value
    result = validate_first_response_sla(fields, report_as_of=snapshot.as_of.isoformat())
    assert result["truthful"] is False
    assert result["overdue_missing_evidence_covered"] is False
    assert result["classification"] == "SLA_SEMANTICS_INVALID"


@pytest.mark.parametrize("missing_clock", [True, False])
def test_api_preview_and_internal_report_serialize_the_same_enum_and_basis_with_rbac(monkeypatch, missing_clock):
    main = importlib.import_module("npd_agent_hub.main")
    if missing_clock:
        store, case = production_shaped_store()
    else:
        store, _ = build_store()
        case = SalesIntelligencePreviewRequest(subject_ref="lead:lead-001", as_of=BASE + timedelta(minutes=60))
    expected = "not_evaluable" if missing_clock else "overdue_missing_evidence"
    executor = ForbiddenExternalExecutor()
    local_hub = AgentHub(store=store, executor=executor)
    monkeypatch.setattr(main, "hub", local_hub)
    monkeypatch.setattr(importlib.import_module("npd_agent_hub.routers.sales_intelligence"), "hub", local_hub)
    monkeypatch.setattr(authorizer, "settings", HubSettings(
        auth_mode="static_token", viewer_token="viewer-secret",
        operator_token="operator-secret", owner_token="owner-secret"))
    client = TestClient(main.app)
    viewer = {"Authorization": "Bearer viewer-secret"}
    operator = {"Authorization": "Bearer operator-secret"}
    payload = case.model_dump(mode="json")
    before = store.list_recent_tasks(100)
    assert client.post("/api/v1/sales-intelligence/preview", json=payload, headers=viewer).status_code == 403
    preview = client.post("/api/v1/sales-intelligence/preview", json=payload, headers=operator)
    assert preview.status_code == 200
    assert preview.json()["first_response_sla"]["status"] == expected
    assert (preview.json()["first_response_sla"]["deadline_at"] is None) == missing_clock
    assert store.list_recent_tasks(100) == before
    response = client.post("/api/v1/agent-tasks", headers=operator, json=pilot_task(case).model_dump(mode="json"))
    assert response.status_code == 200
    body = response.json()
    fields = body["answer"]["items"][0]["details"]
    assert fields["first_response_sla"] == preview.json()["first_response_sla"]["status"]
    result = validate_first_response_sla(fields, report_as_of=body["answer"]["metrics"]["as_of"])
    assert result["truthful"] is True and result["overdue_missing_evidence_covered"] == (not missing_clock)
    fetched = client.get("/api/v1/agent-tasks/" + body["task_id"], headers=viewer)
    assert fetched.json()["answer"]["items"][0]["details"] == fields
    assert fetched.headers["cache-control"] == "no-store"
    assert executor.calls == 0
