from __future__ import annotations

import importlib

from fastapi.testclient import TestClient

from npd_agent_hub.auth import authorizer
from npd_agent_hub.config import HubSettings
from npd_agent_hub.dashboard import DASHBOARD_HTML, command_center_html
from npd_agent_hub.models import AgentTask
from npd_agent_hub.sales_intelligence_models import SalesIntelligencePreviewRequest
from test_phase9_marketing_review import prepared_hub


def test_phase9_preset_uses_existing_validated_contract_without_execution_controls():
    assert 'id="phase9ReviewPreset"' in DASHBOARD_HTML
    assert 'id="phase9Subjects"' in DASHBOARD_HTML
    assert 'id="phase9AsOf" type="datetime-local"' in DASHBOARD_HTML
    assert "context:{phase9_review:{cases:" in DASHBOARD_HTML
    assert "subject_ref,observations:[],as_of:asOfDate.toISOString()" in DASHBOARD_HTML
    assert "refs.length>20" in DASHBOARD_HTML
    assert "Không được nhập email hoặc số điện thoại" in DASHBOARD_HTML

    function = DASHBOARD_HTML.split(
        "async function createPhase9ReviewTask()", 1
    )[1].split("async function refreshAll()", 1)[0]
    assert "/api/v1/agent-tasks" in function
    assert "external write" in function
    for forbidden in ("/execute", "publish", "notification", "render job"):
        assert forbidden not in function


def test_phase9_preset_is_role_gated_and_preserved_in_oidc_dashboard():
    assert "currentRole==='operator'||currentRole==='owner'" in DASHBOARD_HTML
    assert "phase9Create').disabled=!allowed" in DASHBOARD_HTML
    assert "chỉ được xem kết quả" in DASHBOARD_HTML

    oidc_html = command_center_html(browser_login_enabled=True).body.decode("utf-8")
    assert 'id="phase9ReviewPreset"' in oidc_html
    assert 'id="phase9Create"' in oidc_html
    assert 'id="token"' not in oidc_html
    assert "setPhase9Access(me.role)" in oidc_html


def test_phase9_preset_report_surface_calls_out_missing_data_without_inference():
    assert "renderPhase9DataStatus(a)" in DASHBOARD_HTML
    assert "Dữ liệu còn thiếu — không suy diễn" in DASHBOARD_HTML
    assert "Journey/evidence chưa đủ để đánh giá" in DASHBOARD_HTML
    assert "external writes disabled" in DASHBOARD_HTML


def test_phase9_browser_contract_is_operator_create_and_viewer_read_only(monkeypatch):
    main_module = importlib.import_module("npd_agent_hub.main")
    hub, signed_case, executor = prepared_hub()
    missing_case = SalesIntelligencePreviewRequest(
        subject_ref="lead:missing-browser-case",
        observations=[],
        as_of=signed_case.as_of,
    )
    task = AgentTask(
        objective="Rà soát hồ sơ cần Marketing và Sales xem xét",
        context={
            "phase9_review": {
                "cases": [missing_case.model_dump(mode="json")]
            }
        },
    )
    monkeypatch.setattr(main_module, "hub", hub)
    monkeypatch.setattr(
        authorizer,
        "settings",
        HubSettings(
            auth_mode="static_token",
            viewer_token="viewer-secret",
            operator_token="operator-secret",
            owner_token="owner-secret",
        ),
    )
    client = TestClient(main_module.app)
    viewer = {"Authorization": "Bearer viewer-secret"}
    operator = {"Authorization": "Bearer operator-secret"}

    assert client.post(
        "/api/v1/agent-tasks", json=task.model_dump(mode="json"), headers=viewer
    ).status_code == 403
    created = client.post(
        "/api/v1/agent-tasks", json=task.model_dump(mode="json"), headers=operator
    )
    assert created.status_code == 200
    body = created.json()
    assert body["answer"]["metrics"]["failed_subjects"] == 1
    assert body["answer"]["metrics"]["external_writes_enabled"] is False
    assert body["answer"]["metrics"]["customer_contact_enabled"] is False
    assert executor.calls == 0

    fetched = client.get(
        f"/api/v1/agent-tasks/{body['task_id']}", headers=viewer
    )
    assert fetched.status_code == 200
    assert fetched.json()["answer"]["items"][0]["details"][
        "evaluation_status"
    ] == "not_found"


def test_phase9_browser_flow_has_scoped_filters_summary_and_double_submit_guard():
    assert 'id="phase9PriorityFilter"' in DASHBOARD_HTML
    assert 'id="phase9MissingOnly"' in DASHBOARD_HTML
    assert "phase9-review-item" in DASHBOARD_HTML
    assert 'data-missing="' in DASHBOARD_HTML
    assert "phase9ReviewSubjects()" in DASHBOARD_HTML
    assert (
        "/api/v1/next-best-actions/reviews/sales/summary?subject_ref="
        in DASHBOARD_HTML
    )
    assert "NBA v2 feedback trong đúng cohort hiện tại" in DASHBOARD_HTML
    assert "Xem lại" in DASHBOARD_HTML

    feedback = DASHBOARD_HTML.split(
        "async function submitPhase9Feedback(index)", 1
    )[1].split("async function refreshAll()", 1)[0]
    assert (
        "phase9FeedbackPending.has(key)||phase9FeedbackSubmitted.has(key)"
        in feedback
    )
    assert feedback.index("phase9FeedbackPending.add(key)") < feedback.index(
        "await api("
    )
    assert "/api/v1/next-best-actions/reviews/sales" in feedback
    assert "recommendation_version!=='phase-9b-nba-v2'" in feedback
    assert "result.recommendation_executed" in feedback
    assert "result.external_writes_enabled" in feedback
    assert "result.customer_contact_enabled" in feedback
    assert "/execute" not in feedback
    assert "publish" not in feedback


def test_phase9_browser_output_is_escaped_and_viewer_controls_are_read_only():
    assert ".answer{min-width:0;overflow-wrap:anywhere}" in DASHBOARD_HTML
    item_renderer = DASHBOARD_HTML.split(
        "function renderGenericItems(items,phase9=false)", 1
    )[1].split("function renderPhase9DataStatus(a)", 1)[0]
    for escaped_value in (
        "esc(i.title)",
        "esc(i.reason)",
        "esc(k)",
        "esc(v??'—')",
        "esc(i.recommended_action)",
    ):
        assert escaped_value in item_renderer

    assert "data-phase9-write" in DASHBOARD_HTML
    assert "button.disabled=!allowed" in DASHBOARD_HTML
    assert "Viewer chỉ được xem; feedback cần operator hoặc owner." in DASHBOARD_HTML
    assert (
        "Viewer chỉ được xem; phân tích lại cần operator hoặc owner."
        in DASHBOARD_HTML
    )
    assert "Ghi chú feedback không được chứa email hoặc số điện thoại." in DASHBOARD_HTML
    assert "review telemetry, không phải execution approval" in DASHBOARD_HTML


def test_phase9_browser_feedback_recomputes_v2_and_never_executes(monkeypatch):
    main_module = importlib.import_module("npd_agent_hub.main")
    review_router = importlib.import_module("npd_agent_hub.routers.nba_reviews")
    hub, signed_case, executor = prepared_hub()
    browser_case = SalesIntelligencePreviewRequest(
        subject_ref=signed_case.subject_ref,
        observations=[],
        as_of=signed_case.as_of,
    )
    monkeypatch.setattr(main_module, "hub", hub)
    monkeypatch.setattr(review_router, "hub", hub)
    monkeypatch.setattr(
        authorizer,
        "settings",
        HubSettings(
            auth_mode="static_token",
            viewer_token="viewer-secret",
            operator_token="operator-secret",
            owner_token="owner-secret",
        ),
    )
    client = TestClient(main_module.app)
    viewer = {"Authorization": "Bearer viewer-secret"}
    operator = {"Authorization": "Bearer operator-secret"}
    task = AgentTask(
        objective="Rà soát SAMPLE cohort không PII",
        context={
            "phase9_review": {
                "cases": [browser_case.model_dump(mode="json")]
            }
        },
    )

    created = client.post(
        "/api/v1/agent-tasks",
        json=task.model_dump(mode="json"),
        headers=operator,
    )
    assert created.status_code == 200
    report = created.json()
    assert report["answer"]["metrics"]["evaluated_subjects"] == 1
    item = report["answer"]["items"][0]
    review_payload = {
        "evaluation": {
            "subject_ref": item["entity_id"],
            "observations": [],
            "as_of": item["details"]["as_of"],
        },
        "disposition": "relevant",
        "note": "SAMPLE evidence supports this internal recommendation.",
    }

    assert (
        client.post(
            "/api/v1/next-best-actions/reviews/sales",
            json=review_payload,
            headers=viewer,
        ).status_code
        == 403
    )
    reviewed = client.post(
        "/api/v1/next-best-actions/reviews/sales",
        json=review_payload,
        headers=operator,
    )
    assert reviewed.status_code == 201
    receipt = reviewed.json()
    assert receipt["recommendation_version"] == "phase-9b-nba-v2"
    assert receipt["recommendation_executed"] is False
    assert receipt["execution_enabled"] is False
    assert receipt["external_writes_enabled"] is False
    assert receipt["customer_contact_enabled"] is False

    summary = client.get(
        "/api/v1/next-best-actions/reviews/sales/summary",
        params={"subject_ref": item["entity_id"]},
        headers=viewer,
    )
    assert summary.status_code == 200
    assert summary.json()["total_reviews"] == 1
    assert summary.json()["relevant"] == 1
    assert client.get(
        f"/api/v1/agent-tasks/{report['task_id']}",
        headers=viewer,
    ).status_code == 200
    assert client.post(
        f"/api/v1/agent-tasks/{report['task_id']}/analyze",
        headers=viewer,
    ).status_code == 403
    assert executor.calls == 0
