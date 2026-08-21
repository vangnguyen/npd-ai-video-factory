from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime, timedelta

import fakeredis
import httpx
import pytest
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
    ExperimentEvaluationRequest,
    ExperimentGuardrail,
    ExperimentMetric,
    ExperimentObservationCreate,
    ExperimentObservationQualityDecision,
    ExperimentStatus,
    ExperimentStopCondition,
    ExperimentType,
    ExperimentVariant,
    ObservationSource,
    ObservationQualityState,
    ObservationState,
    RecommendationAction,
    VariantObservation,
)
from npd_agent_hub.experiments import ExperimentService
from npd_agent_hub.marketing_sources import MarketingSourceReader
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


def observation_request(
    *,
    state: ObservationState = ObservationState.VERIFIED_READ_ONLY,
    control_conversions: int = 25,
    challenger_conversions: int = 45,
    sample_size: int = 1000,
) -> ExperimentObservationCreate:
    collected_at = datetime.now(UTC)
    return ExperimentObservationCreate(
        source_system=ObservationSource.GA4,
        source_state=state,
        source_snapshot_id="ga4:campaign:vinh-tien:20260901-20260914",
        window_start=collected_at - timedelta(days=14),
        window_end=collected_at - timedelta(minutes=5),
        collected_at=collected_at,
        variants=[
            VariantObservation(
                variant_id="VAR-CONTROL",
                sample_size=sample_size,
                conversions=control_conversions,
                guardrail_values={"Cost per qualified lead": 1_200_000},
            ),
            VariantObservation(
                variant_id="VAR-HOOKA",
                sample_size=sample_size,
                conversions=challenger_conversions,
                guardrail_values={"Cost per qualified lead": 1_300_000},
            ),
        ],
        note="Verified read-only fixture; no traffic or source-system mutation.",
    )


def accept_observation(service, experiment_id: str, observation_id: str):
    return service.decide_observation_quality(
        experiment_id,
        observation_id,
        ExperimentObservationQualityDecision(accepted=True, note="Owner verified source snapshot"),
        actor="owner",
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


def test_read_only_observation_generates_advisory_winner_candidate():
    store = MemoryHubStore()
    campaign, reconciliation = accepted_fixture(store)
    service = ExperimentService(store)
    experiment = service.create(
        experiment_request(campaign.campaign_id, reconciliation.reconciliation_id),
        actor="operator",
    )
    observation = service.add_observation(
        experiment.experiment_id, observation_request(), actor="operator"
    )
    accept_observation(service, experiment.experiment_id, observation.observation_id)
    evaluation = service.evaluate(
        experiment.experiment_id,
        ExperimentEvaluationRequest(min_sample_per_variant=100),
        actor="operator",
    )

    assert observation.contains_raw_pii is False
    assert observation.external_writes_enabled is False
    assert evaluation.recommendation == RecommendationAction.WINNER_CANDIDATE
    assert evaluation.winner_candidate_variant_id == "VAR-HOOKA"
    assert evaluation.sample_sufficient is True
    assert evaluation.source_fresh is True
    assert evaluation.observed_lift_percent == 80
    assert evaluation.p_value is not None and evaluation.p_value < 0.05
    assert evaluation.external_writes_enabled is False
    assert evaluation.automatic_decision_enabled is False
    assert service.get(experiment.experiment_id).status == ExperimentStatus.PLANNED
    assert [item.event_type for item in service.history(experiment.experiment_id)[:3]] == [
        "experiment_evaluated",
        "experiment_observation_quality_decided",
        "experiment_observation_ingested",
    ]


def test_partial_or_insufficient_observation_cannot_produce_winner():
    store = MemoryHubStore()
    campaign, reconciliation = accepted_fixture(store)
    service = ExperimentService(store)
    experiment = service.create(
        experiment_request(campaign.campaign_id, reconciliation.reconciliation_id),
        actor="operator",
    )
    partial = service.add_observation(
        experiment.experiment_id,
        observation_request(state=ObservationState.PARTIAL),
        actor="operator",
    )
    accept_observation(service, experiment.experiment_id, partial.observation_id)
    partial_result = service.evaluate(
        experiment.experiment_id,
        ExperimentEvaluationRequest(observation_id=partial.observation_id),
        actor="operator",
    )
    assert partial_result.recommendation == RecommendationAction.MANUAL_REVIEW
    assert partial_result.winner_candidate_variant_id is None

    insufficient = service.add_observation(
        experiment.experiment_id,
        observation_request(sample_size=50, control_conversions=2, challenger_conversions=4),
        actor="operator",
    )
    accept_observation(service, experiment.experiment_id, insufficient.observation_id)
    insufficient_result = service.evaluate(
        experiment.experiment_id,
        ExperimentEvaluationRequest(
            observation_id=insufficient.observation_id,
            min_sample_per_variant=100,
        ),
        actor="operator",
    )
    assert insufficient_result.recommendation == RecommendationAction.INSUFFICIENT_DATA
    assert insufficient_result.sample_sufficient is False


def test_observation_contract_rejects_pii_write_flags_and_unknown_variants():
    base = observation_request().model_dump()
    with pytest.raises(ValueError, match="raw PII"):
        ExperimentObservationCreate.model_validate({**base, "contains_raw_pii": True})
    with pytest.raises(ValueError, match="read-only"):
        ExperimentObservationCreate.model_validate(
            {**base, "external_writes_enabled": True}
        )

    store = MemoryHubStore()
    campaign, reconciliation = accepted_fixture(store)
    service = ExperimentService(store)
    experiment = service.create(
        experiment_request(campaign.campaign_id, reconciliation.reconciliation_id),
        actor="operator",
    )
    unknown = observation_request()
    unknown.variants[1].variant_id = "VAR-UNKNOWN"
    with pytest.raises(ValueError, match="outside the experiment plan"):
        service.add_observation(experiment.experiment_id, unknown, actor="operator")


def test_owner_quality_gate_blocks_evaluation_until_snapshot_is_accepted():
    store = MemoryHubStore()
    campaign, reconciliation = accepted_fixture(store)
    service = ExperimentService(store)
    experiment = service.create(
        experiment_request(campaign.campaign_id, reconciliation.reconciliation_id),
        actor="operator",
    )
    observation = service.add_observation(
        experiment.experiment_id, observation_request(), actor="operator"
    )
    assert observation.quality_state == ObservationQualityState.PENDING_OWNER
    with pytest.raises(ValueError, match="accepted by an owner"):
        service.evaluate(experiment.experiment_id, ExperimentEvaluationRequest(), actor="operator")
    rejected = service.decide_observation_quality(
        experiment.experiment_id,
        observation.observation_id,
        ExperimentObservationQualityDecision(accepted=False, note="Tracking mismatch"),
        actor="owner",
    )
    assert rejected.quality_state == ObservationQualityState.REJECTED
    with pytest.raises(ValueError, match="accepted by an owner"):
        service.evaluate(experiment.experiment_id, ExperimentEvaluationRequest(), actor="operator")


def test_direct_ga4_read_maps_campaign_and_utm_content_without_side_effects():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        captured["authorization"] = request.headers.get("Authorization")
        return httpx.Response(
            200,
            json={
                "rows": [
                    {
                        "dimensionValues": [
                            {"value": "cmp-vgp-vinhtien-202609-01"},
                            {"value": "VAR-CONTROL"},
                        ],
                        "metricValues": [{"value": "1000"}, {"value": "25"}],
                    },
                    {
                        "dimensionValues": [
                            {"value": "cmp-vgp-vinhtien-202609-01"},
                            {"value": "VAR-HOOKA"},
                        ],
                        "metricValues": [{"value": "1000"}, {"value": "45"}],
                    },
                ],
                "rowCount": 2,
            },
        )

    store = MemoryHubStore()
    campaign, reconciliation = accepted_fixture(store)
    reader = MarketingSourceReader(
        HubSettings(ga4_property_id="251054384"),
        transport=httpx.MockTransport(handler),
        ga4_token_provider=lambda: "read-only-token",
    )
    service = ExperimentService(
        store,
        source_status_provider=reader.configuration_status,
        source_reader=reader,
    )
    experiment = service.create(
        experiment_request(campaign.campaign_id, reconciliation.reconciliation_id),
        actor="operator",
    )
    from npd_agent_hub.experiment_models import ExperimentSourceReadRequest

    result = asyncio.run(
        service.read_source_observation(
            experiment.experiment_id,
            ExperimentSourceReadRequest(
                source_system=ObservationSource.GA4,
                window_start=date.today() - timedelta(days=7),
                window_end=date.today(),
            ),
            actor="operator",
        )
    )
    assert result.state == "observed"
    assert result.observation is not None
    assert result.observation.quality_state == ObservationQualityState.PENDING_OWNER
    assert result.observation.external_writes_enabled is False
    body = captured["body"]
    assert body["dimensionFilter"]["filter"]["stringFilter"]["value"] == campaign.tracking.utm_campaign
    assert [item["name"] for item in body["dimensions"]] == [
        "sessionManualCampaignName",
        "sessionManualAdContent",
    ]
    assert "read-only-token" not in json.dumps(result.model_dump(mode="json"))
    assert service.get(experiment.experiment_id).last_evaluation is None


def test_meta_tracking_requires_explicit_campaign_and_ad_id_mappings():
    store = MemoryHubStore()
    campaign, reconciliation = accepted_fixture(store)
    reader = MarketingSourceReader(
        HubSettings(
            meta_ads_account_id="123456",
            meta_ads_access_token="read-only-token",
            meta_graph_version="v23.0",
        )
    )
    service = ExperimentService(
        store,
        source_status_provider=reader.configuration_status,
        source_reader=reader,
    )
    experiment = service.create(
        experiment_request(campaign.campaign_id, reconciliation.reconciliation_id),
        actor="operator",
    )
    validation = service.validate_tracking(experiment.experiment_id, ObservationSource.META_ADS)
    assert validation.state == "partial"
    assert any("meta_ads_campaign_id" in issue for issue in validation.issues)
    assert sum("asset_ref" in issue for issue in validation.issues) == 2


def test_guardrail_breach_stops_for_manual_review_without_execution():
    store = MemoryHubStore()
    campaign, reconciliation = accepted_fixture(store)
    service = ExperimentService(store)
    experiment = service.create(
        experiment_request(campaign.campaign_id, reconciliation.reconciliation_id),
        actor="operator",
    )
    request = observation_request()
    request.variants[1].guardrail_values["Cost per qualified lead"] = 1_700_000
    observation = service.add_observation(experiment.experiment_id, request, actor="operator")
    accept_observation(service, experiment.experiment_id, observation.observation_id)
    evaluation = service.evaluate(
        experiment.experiment_id, ExperimentEvaluationRequest(), actor="operator"
    )
    assert evaluation.recommendation == RecommendationAction.STOP_AND_REVIEW
    assert evaluation.guardrail_breaches
    assert service.get(experiment.experiment_id).execution_enabled is False


def test_observation_and_evaluation_recover_from_redis():
    client = fakeredis.FakeRedis(decode_responses=True)
    store = RedisHubStore(client=client, namespace="test:agent-hub")
    campaign, reconciliation = accepted_fixture(store)
    service = ExperimentService(store)
    experiment = service.create(
        experiment_request(campaign.campaign_id, reconciliation.reconciliation_id),
        actor="operator",
    )
    observation = service.add_observation(
        experiment.experiment_id, observation_request(), actor="operator"
    )
    accept_observation(service, experiment.experiment_id, observation.observation_id)
    service.evaluate(
        experiment.experiment_id, ExperimentEvaluationRequest(), actor="operator"
    )

    restored = ExperimentService(
        RedisHubStore(client=client, namespace="test:agent-hub")
    ).get(experiment.experiment_id)
    assert len(restored.observations) == 1
    assert restored.last_evaluation is not None
    assert restored.last_evaluation.recommendation == RecommendationAction.WINNER_CANDIDATE


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
        tracking = client.get(
            f"/api/v1/experiments/{experiment_id}/tracking-validation",
            headers=viewer,
            params={"source_system": "ga4"},
        )
        assert tracking.status_code == 200
        assert tracking.json()["state"] == "not_configured"
        source_payload = {
            "source_system": "ga4",
            "window_start": (date.today() - timedelta(days=13)).isoformat(),
            "window_end": date.today().isoformat(),
        }
        assert client.post(
            f"/api/v1/experiments/{experiment_id}/source-read",
            headers=viewer,
            json=source_payload,
        ).status_code == 403
        no_source = client.post(
            f"/api/v1/experiments/{experiment_id}/source-read",
            headers=operator,
            json=source_payload,
        )
        assert no_source.status_code == 200
        assert no_source.json()["state"] == "not_configured"
        assert no_source.json()["observation"] is None
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
            f"/api/v1/experiments/{experiment_id}/observations",
            headers=viewer,
            json=observation_request().model_dump(mode="json"),
        ).status_code == 403
        observed = client.post(
            f"/api/v1/experiments/{experiment_id}/observations",
            headers=operator,
            json=observation_request().model_dump(mode="json"),
        )
        assert observed.status_code == 201
        observation_id = observed.json()["observation_id"]
        assert client.get(
            f"/api/v1/experiments/{experiment_id}/observations", headers=viewer
        ).status_code == 200
        assert client.post(
            f"/api/v1/experiments/{experiment_id}/evaluations",
            headers=viewer,
            json={},
        ).status_code == 403
        assert client.post(
            f"/api/v1/experiments/{experiment_id}/observations/{observation_id}/quality-decision",
            headers=operator,
            json={"accepted": True, "note": "operator must not decide"},
        ).status_code == 403
        accepted = client.post(
            f"/api/v1/experiments/{experiment_id}/observations/{observation_id}/quality-decision",
            headers=owner,
            json={"accepted": True, "note": "Owner verified aggregate evidence"},
        )
        assert accepted.status_code == 200
        assert accepted.json()["quality_state"] == "accepted"
        evaluated = client.post(
            f"/api/v1/experiments/{experiment_id}/evaluations",
            headers=operator,
            json={},
        )
        assert evaluated.status_code == 200
        assert evaluated.json()["recommendation"] == "winner_candidate"
        assert evaluated.json()["automatic_decision_enabled"] is False
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
    assert TOOL_REGISTRY["experiment.observation.read"].mode.value == "read"
    assert (
        TOOL_REGISTRY["experiment.recommendation.evaluate"].execution_state.value
        == "planning_only"
    )
    assert local_hub.list_executions(report.task_id) == []


def test_dashboard_exposes_responsive_experiment_workspace():
    assert "Experiment & Optimization OS" in DASHBOARD_HTML
    assert "/api/v1/experiments/status" in DASHBOARD_HTML
    assert "/api/v1/experiments/" in DASHBOARD_HTML
    assert "Production execution" in DASHBOARD_HTML
    assert "Traffic allocation: chưa thực thi" in DASHBOARD_HTML
    assert "Đánh giá bằng dữ liệu chỉ-đọc" in DASHBOARD_HTML
    assert "/observations" in DASHBOARD_HTML
    assert "/evaluations" in DASHBOARD_HTML
    assert "/source-read" in DASHBOARD_HTML
    assert "/quality-decision" in DASHBOARD_HTML
    assert "Owner chấp nhận dữ liệu" in DASHBOARD_HTML
