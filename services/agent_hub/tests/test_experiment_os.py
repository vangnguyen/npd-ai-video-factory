from __future__ import annotations

from datetime import UTC, date, datetime

import fakeredis
from fastapi.testclient import TestClient

from npd_agent_hub.attribution import AttributionService
from npd_agent_hub.attribution_models import (
    AttributionAcceptanceRequest,
    OpportunityObservation,
    OpportunityStatus,
    ReconciliationRequest,
)
from npd_agent_hub.auth import authorizer
from npd_agent_hub.campaign_models import CampaignBudget, CampaignCreate, KPITarget
from npd_agent_hub.campaigns import CampaignService
from npd_agent_hub.config import HubSettings
from npd_agent_hub.dashboard import DASHBOARD_HTML
from npd_agent_hub.experiment_models import (
    ExperimentApprovalDecision,
    ExperimentCreate,
    ExperimentGuardrail,
    ExperimentMetric,
    ExperimentStatus,
    ExperimentStopCondition,
    ExperimentType,
    ExperimentVariant,
)
from npd_agent_hub.experiments import ExperimentService
from npd_agent_hub.main import app
from npd_agent_hub.models import AgentName, AgentTask
from npd_agent_hub.orchestrator import AgentHub, hub
from npd_agent_hub.store import MemoryHubStore, RedisHubStore
from npd_agent_hub.tool_registry import TOOL_REGISTRY


def accepted_fixture(store):
    campaign = CampaignService(store).create(
        CampaignCreate(
            name="Vịnh Tiên",
            project="Vinhomes Green Paradise – Vịnh Tiên",
            project_code="VGP",
            objective="Tạo lead đủ điều kiện và lịch đi xem",
            audience=["Nhà đầu tư"],
            budget=CampaignBudget(amount=100_000_000, currency="VND"),
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30),
            kpi_targets=[
                KPITarget(name="Lead", target=300, unit="lead", funnel_stage="lead")
            ],
            owner="owner@example.com",
        ),
        actor="operator",
    )
    attribution = AttributionService(store)
    reconciliation = attribution.reconcile(
        ReconciliationRequest(
            observations=[
                OpportunityObservation(
                    opportunity_id="opp-exp-001",
                    campaign_id_hint=campaign.campaign_id,
                    stage="Closed Won",
                    status=OpportunityStatus.WON,
                    amount=12_000_000,
                    currency="VND",
                    observed_at=datetime(2026, 9, 20, tzinfo=UTC),
                    closed_at=datetime(2026, 9, 19, tzinfo=UTC),
                )
            ]
        ),
        actor="operator",
    )
    accepted = attribution.accept_quality(
        reconciliation.reconciliation_id,
        AttributionAcceptanceRequest(accepted=True, note="accepted fixture"),
        actor="owner",
    )
    return campaign, accepted


def experiment_request(campaign_id: str, reconciliation_id: str) -> ExperimentCreate:
    return ExperimentCreate(
        campaign_id=campaign_id,
        attribution_reconciliation_id=reconciliation_id,
        name="Creative hook test",
        experiment_type=ExperimentType.CREATIVE,
        hypothesis="Hook nêu lợi ích đầu tư rõ hơn sẽ tăng tỷ lệ form submit.",
        primary_metric=ExperimentMetric(
            name="Form conversion rate",
            unit="percent",
            source="GA4 accepted campaign events",
        ),
        baseline_value=2.5,
        target_lift_percent=20,
        variants=[
            ExperimentVariant(
                variant_id="VAR-CONTROL",
                name="Control",
                description="Creative hiện tại giữ nguyên.",
                allocation_percent=50,
            ),
            ExperimentVariant(
                variant_id="VAR-HOOKA",
                name="Benefit hook",
                description="Creative draft với hook lợi ích đầu tư.",
                allocation_percent=50,
            ),
        ],
        guardrails=[
            ExperimentGuardrail(
                metric="Cost per qualified lead",
                operator="<=",
                threshold=1_500_000,
                unit="VND",
            )
        ],
        stop_conditions=[
            ExperimentStopCondition(
                condition="Guardrail breached for two review windows",
                reason="Protect lead economics",
            )
        ],
        evaluation_window_days=14,
        owner="owner@example.com",
    )


def test_experiment_requires_owner_accepted_attribution_and_campaign_coverage():
    store = MemoryHubStore()
    campaign = CampaignService(store).create(
        CampaignCreate(
            name="Vịnh Tiên",
            project="Vịnh Tiên",
            project_code="VGP",
            objective="Campaign test",
            audience=["Nhà đầu tư"],
            budget=CampaignBudget(amount=1),
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30),
            kpi_targets=[KPITarget(name="Lead", target=1, unit="lead", funnel_stage="lead")],
            owner="owner",
        ),
        actor="operator",
    )
    reconciliation = AttributionService(store).reconcile(
        ReconciliationRequest(
            observations=[
                OpportunityObservation(
                    opportunity_id="opp-blocked",
                    campaign_id_hint=campaign.campaign_id,
                    stage="Closed Won",
                    status=OpportunityStatus.WON,
                    amount=1,
                    currency="VND",
                    observed_at=datetime.now(UTC),
                    closed_at=datetime.now(UTC),
                )
            ]
        ),
        actor="operator",
    )
    try:
        ExperimentService(store).create(
            experiment_request(campaign.campaign_id, reconciliation.reconciliation_id),
            actor="operator",
        )
        assert False, "unaccepted attribution must block experiment creation"
    except ValueError as exc:
        assert "owner-accepted" in str(exc)


def test_plan_preview_approval_and_no_external_side_effects():
    store = MemoryHubStore()
    campaign, reconciliation = accepted_fixture(store)
    service = ExperimentService(store)
    experiment = service.create(
        experiment_request(campaign.campaign_id, reconciliation.reconciliation_id),
        actor="operator",
    )

    assert experiment.experiment_id == "EXP-VGP-202609-001"
    assert experiment.status == ExperimentStatus.PLANNED
    assert experiment.execution_enabled is False
    preview = service.preview(experiment.experiment_id, actor="operator")
    assert preview.target_value == 3.0
    assert preview.external_writes_enabled is False
    pending = service.request_approval(
        experiment.experiment_id, actor="operator", note="plan ready"
    )
    assert pending.status == ExperimentStatus.AWAITING_APPROVAL
    approved = service.decide_approval(
        experiment.experiment_id,
        ExperimentApprovalDecision(approved=True, note="plan approved only"),
        actor="owner",
    )
    assert approved.status == ExperimentStatus.APPROVED
    assert approved.execution_enabled is False
    assert approved.external_writes_enabled is False
    assert [item.event_type for item in service.history(experiment.experiment_id)] == [
        "experiment_approval_decided",
        "experiment_approval_requested",
        "experiment_previewed",
        "experiment_planned",
    ]


def test_redis_recovery_uses_experiment_subnamespace():
    client = fakeredis.FakeRedis(decode_responses=True)
    first_store = RedisHubStore(client=client, namespace="test:agent-hub")
    campaign, reconciliation = accepted_fixture(first_store)
    first = ExperimentService(first_store)
    experiment = first.create(
        experiment_request(campaign.campaign_id, reconciliation.reconciliation_id),
        actor="operator",
    )
    first.preview(experiment.experiment_id, actor="operator")

    restarted = ExperimentService(
        RedisHubStore(client=client, namespace="test:agent-hub")
    )
    restored = restarted.get(experiment.experiment_id)
    assert restored.last_preview is not None
    assert restored.status == ExperimentStatus.PREVIEWED
    keys = {str(item) for item in client.scan_iter("*")}
    assert any(item.startswith("test:agent-hub:experiment-os:") for item in keys)
    assert not any("npd:video-jobs" in item for item in keys)


def test_experiment_http_rbac_and_no_execution_endpoint():
    previous_settings = authorizer.settings
    previous_store = hub.store
    previous_campaigns = hub.campaigns
    previous_attribution = hub.attribution
    previous_experiments = hub.experiments
    authorizer.settings = HubSettings(
        auth_mode="static_token",
        viewer_token="viewer-secret",
        operator_token="operator-secret",
        owner_token="owner-secret",
    )
    store = MemoryHubStore()
    campaign, reconciliation = accepted_fixture(store)
    hub.store = store
    hub.campaigns = CampaignService(store)
    hub.attribution = AttributionService(store)
    hub.experiments = ExperimentService(store)
    client = TestClient(app)
    viewer = {"Authorization": "Bearer viewer-secret"}
    operator = {"Authorization": "Bearer operator-secret"}
    owner = {"Authorization": "Bearer owner-secret"}
    payload = experiment_request(
        campaign.campaign_id, reconciliation.reconciliation_id
    ).model_dump(mode="json")
    try:
        assert client.post("/api/v1/experiments", headers=viewer, json=payload).status_code == 403
        created = client.post("/api/v1/experiments", headers=operator, json=payload)
        assert created.status_code == 201
        experiment_id = created.json()["experiment_id"]
        assert client.post(
            f"/api/v1/experiments/{experiment_id}/preview", headers=operator
        ).status_code == 200
        assert client.post(
            f"/api/v1/experiments/{experiment_id}/approvals/request",
            headers=operator,
            json={"note": "ready"},
        ).status_code == 200
        assert client.post(
            f"/api/v1/experiments/{experiment_id}/approvals/decision",
            headers=operator,
            json={"approved": True},
        ).status_code == 403
        approved = client.post(
            f"/api/v1/experiments/{experiment_id}/approvals/decision",
            headers=owner,
            json={"approved": True, "note": "plan only"},
        )
        assert approved.status_code == 200
        assert approved.json()["execution_enabled"] is False
        assert client.post(
            f"/api/v1/experiments/{experiment_id}/execute", headers=owner
        ).status_code == 404
        assert client.get("/api/v1/experiments/status", headers=viewer).status_code == 200
    finally:
        authorizer.settings = previous_settings
        hub.store = previous_store
        hub.campaigns = previous_campaigns
        hub.attribution = previous_attribution
        hub.experiments = previous_experiments


def test_experiment_agent_and_tools_remain_plan_preview_only():
    local_hub = AgentHub(store=MemoryHubStore())
    report = local_hub.run(
        AgentTask(objective="Tạo A/B experiment tối ưu creative Vịnh Tiên")
    )
    assert AgentName.EXPERIMENT_OPTIMIZATION in report.selected_agents
    agent_report = next(
        item for item in report.reports if item.agent == AgentName.EXPERIMENT_OPTIMIZATION
    )
    assert {item.tool for item in agent_report.actions} == {
        "experiment.plan.create",
        "experiment.preview.generate",
    }
    assert all(
        TOOL_REGISTRY[item.tool].execution_state.value == "planning_only"
        for item in agent_report.actions
    )
    assert TOOL_REGISTRY["experiment.execution.start"].execution_state.value == "disabled"
    assert local_hub.list_executions(report.task_id) == []


def test_dashboard_exposes_responsive_experiment_workspace():
    assert "Experiment & Optimization OS" in DASHBOARD_HTML
    assert "/api/v1/experiments/status" in DASHBOARD_HTML
    assert "/api/v1/experiments/" in DASHBOARD_HTML
    assert "Production execution" in DASHBOARD_HTML
    assert "Traffic allocation: chưa thực thi" in DASHBOARD_HTML
