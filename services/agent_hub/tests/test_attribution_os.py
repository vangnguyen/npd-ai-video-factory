from __future__ import annotations

from datetime import date, datetime, timezone

import fakeredis
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from npd_agent_hub.attribution import AttributionService
from npd_agent_hub.attribution_models import (
    AttributionAcceptanceRequest,
    AttributionModel,
    OpportunityObservation,
    OpportunityStatus,
    ReconciliationRequest,
    TouchpointBackfillRequest,
    TouchpointEvent,
    TouchpointType,
)
from npd_agent_hub.auth import authorizer
from npd_agent_hub.campaign_models import (
    CampaignBudget,
    CampaignCreate,
    KPITarget,
)
from npd_agent_hub.campaigns import CampaignService
from npd_agent_hub.config import HubSettings
from npd_agent_hub.dashboard import DASHBOARD_HTML
from npd_agent_hub.main import app
from npd_agent_hub.models import AgentName, AgentTask
from npd_agent_hub.orchestrator import AgentHub, hub
from npd_agent_hub.store import MemoryHubStore, RedisHubStore
from npd_agent_hub.tool_registry import TOOL_REGISTRY


UTC = timezone.utc


def campaign_create(name: str) -> CampaignCreate:
    return CampaignCreate(
        name=name,
        project="Vinhomes Green Paradise – Vịnh Tiên",
        project_code="VGP",
        objective="Đối soát pipeline và doanh thu chiến dịch",
        audience=["Nhà đầu tư"],
        budget=CampaignBudget(amount=100_000_000),
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 30),
        kpi_targets=[
            KPITarget(name="Lead", target=300, unit="lead", funnel_stage="lead")
        ],
        owner="owner@example.com",
    )


def build_fixture(store: MemoryHubStore | RedisHubStore):
    campaigns = CampaignService(store)
    first = campaigns.create(campaign_create("Vịnh Tiên Prospecting"), actor="operator")
    second = campaigns.create(campaign_create("Vịnh Tiên Retargeting"), actor="operator")
    attribution = AttributionService(store)
    touchpoints = [
        TouchpointEvent(
            campaign_id=first.campaign_id,
            event_type=TouchpointType.AD_CLICK,
            occurred_at=datetime(2026, 9, 2, 8, tzinfo=UTC),
            source_system="Meta Ads",
            channel="paid_social",
            lead_id="lead-001",
            opportunity_id="opp-001",
            source_campaign_id="meta-100",
            utm_source="facebook",
            utm_medium="paid_social",
        ),
        TouchpointEvent(
            campaign_id=second.campaign_id,
            event_type=TouchpointType.FORM_SUBMIT,
            occurred_at=datetime(2026, 9, 3, 9, tzinfo=UTC),
            source_system="Landing Page",
            channel="web",
            lead_id="lead-001",
            opportunity_id="opp-001",
            source_campaign_id="meta-200",
            utm_source="facebook",
            utm_medium="retargeting",
        ),
        TouchpointEvent(
            campaign_id=first.campaign_id,
            event_type=TouchpointType.LEAD_CREATED,
            occurred_at=datetime(2026, 9, 4, 10, tzinfo=UTC),
            source_system="EspoCRM",
            channel="crm",
            lead_id="lead-002",
            opportunity_id="opp-002",
        ),
    ]
    attribution.backfill(TouchpointBackfillRequest(touchpoints=touchpoints), actor="operator")
    observations = [
        OpportunityObservation(
            opportunity_id="opp-001",
            lead_id="lead-001",
            stage="Closed Won",
            status=OpportunityStatus.WON,
            amount=12_000_000,
            observed_at=datetime(2026, 9, 20, tzinfo=UTC),
            closed_at=datetime(2026, 9, 19, tzinfo=UTC),
        ),
        OpportunityObservation(
            opportunity_id="opp-002",
            lead_id="lead-002",
            stage="Negotiation",
            status=OpportunityStatus.OPEN,
            amount=8_000_000,
            observed_at=datetime(2026, 9, 20, tzinfo=UTC),
        ),
    ]
    return campaigns, attribution, first, second, touchpoints, observations


def test_immutable_touchpoint_ledger_is_idempotent_and_rejects_raw_pii():
    store = MemoryHubStore()
    _, attribution, _, _, touchpoints, _ = build_fixture(store)
    duplicate = attribution.backfill(
        TouchpointBackfillRequest(touchpoints=[touchpoints[0]]), actor="operator"
    )
    assert duplicate == {
        "inserted": 0,
        "duplicates": 1,
        "shadow_mode": True,
        "external_writes_enabled": False,
    }

    changed = touchpoints[0].model_copy(update={"utm_content": "changed"})
    with pytest.raises(ValueError, match="immutable"):
        attribution.backfill(
            TouchpointBackfillRequest(touchpoints=[changed]), actor="operator"
        )

    payload = touchpoints[0].model_dump()
    payload["event_id"] = "tpt_" + "a" * 32
    payload["metadata"] = {"customer_email": "not-allowed@example.com"}
    with pytest.raises(ValidationError, match="raw PII"):
        TouchpointEvent.model_validate(payload)

    payload["metadata"] = {}
    payload["lead_id"] = "+84901234567"
    with pytest.raises(ValidationError, match="raw contact data"):
        TouchpointEvent.model_validate(payload)


def test_backfill_preflights_the_whole_batch_before_writing():
    store = MemoryHubStore()
    _, attribution, first, _, touchpoints, _ = build_fixture(store)
    valid_new = touchpoints[0].model_copy(
        update={
            "event_id": "tpt_" + "b" * 32,
            "campaign_id": first.campaign_id,
        }
    )
    conflicting_existing = touchpoints[1].model_copy(update={"utm_content": "changed"})

    before = attribution.status().touchpoint_count
    with pytest.raises(ValueError, match="immutable"):
        attribution.backfill(
            TouchpointBackfillRequest(
                touchpoints=[valid_new, conflicting_existing]
            ),
            actor="operator",
        )
    assert attribution.status().touchpoint_count == before
    assert store.get_touchpoint(valid_new.event_id) is None


def test_revenue_is_blocked_until_owner_accepts_quality_gate():
    _, attribution, first, second, _, observations = build_fixture(MemoryHubStore())
    reconciliation = attribution.reconcile(
        ReconciliationRequest(observations=observations), actor="operator"
    )
    assert reconciliation.quality.eligible_for_acceptance is True
    assert reconciliation.quality.match_rate == 1
    assert reconciliation.accepted is False

    blocked = attribution.report(
        reconciliation.reconciliation_id, model=AttributionModel.LAST_TOUCH
    )
    assert blocked.state == "blocked_until_owner_quality_acceptance"
    assert blocked.attributed_revenue is None

    accepted = attribution.accept_quality(
        reconciliation.reconciliation_id,
        AttributionAcceptanceRequest(accepted=True, note="Sample reconciled"),
        actor="owner@example.com",
    )
    assert accepted.state == "quality_accepted"
    assert accepted.external_writes_enabled is False

    first_touch = attribution.report(
        reconciliation.reconciliation_id, model=AttributionModel.FIRST_TOUCH
    )
    last_touch = attribution.report(
        reconciliation.reconciliation_id, model=AttributionModel.LAST_TOUCH
    )
    linear = attribution.report(
        reconciliation.reconciliation_id, model=AttributionModel.LINEAR
    )
    assert first_touch.attributed_pipeline == 20_000_000
    assert first_touch.attributed_revenue == 12_000_000
    assert {row.campaign_id for row in linear.campaigns} == {
        first.campaign_id,
        second.campaign_id,
    }
    assert next(
        row for row in first_touch.campaigns if row.campaign_id == first.campaign_id
    ).attributed_revenue == 12_000_000
    assert next(
        row for row in last_touch.campaigns if row.campaign_id == second.campaign_id
    ).attributed_revenue == 12_000_000
    assert all(report.external_writes_enabled is False for report in (first_touch, last_touch, linear))


def test_bad_reconciliation_cannot_be_owner_accepted():
    store = MemoryHubStore()
    campaigns = CampaignService(store)
    campaign = campaigns.create(campaign_create("Vịnh Tiên"), actor="operator")
    attribution = AttributionService(store)
    observation = OpportunityObservation(
        opportunity_id="unmatched",
        campaign_id_hint=campaign.campaign_id,
        stage="Open",
        status=OpportunityStatus.OPEN,
        amount=5_000_000,
        observed_at=datetime(2026, 9, 20, tzinfo=UTC),
    )
    reconciliation = attribution.reconcile(
        ReconciliationRequest(observations=[observation]), actor="operator"
    )
    assert reconciliation.quality.eligible_for_acceptance is False
    assert "closed-won" in " ".join(reconciliation.quality.issues)
    with pytest.raises(ValueError, match="not eligible"):
        attribution.accept_quality(
            reconciliation.reconciliation_id,
            AttributionAcceptanceRequest(accepted=True),
            actor="owner",
        )


def test_redis_recovery_uses_attribution_subnamespace():
    redis_client = fakeredis.FakeRedis(decode_responses=True)
    store = RedisHubStore(client=redis_client, namespace="test:agent-hub")
    _, attribution, _, _, _, observations = build_fixture(store)
    reconciliation = attribution.reconcile(
        ReconciliationRequest(observations=observations), actor="operator"
    )
    restarted = AttributionService(
        RedisHubStore(client=redis_client, namespace="test:agent-hub")
    )
    assert restarted.status().touchpoint_count == 3
    assert restarted.get_reconciliation(reconciliation.reconciliation_id).quality.match_rate == 1
    keys = {str(key) for key in redis_client.scan_iter("*")}
    assert any(key.startswith("test:agent-hub:attribution-os:") for key in keys)
    assert not any("npd:video-jobs" in key for key in keys)


def test_attribution_agent_and_tool_registry_remain_read_or_planning_only():
    local_hub = AgentHub(store=MemoryHubStore())
    report = local_hub.run(
        AgentTask(objective="Đối soát attribution, pipeline và doanh thu closed won")
    )
    assert AgentName.REVENUE_ATTRIBUTION in report.selected_agents
    agent_report = next(
        item for item in report.reports if item.agent == AgentName.REVENUE_ATTRIBUTION
    )
    assert {item.tool for item in agent_report.actions} == {
        "attribution.ledger.read",
        "attribution.reconcile.preview",
        "revenue.report.read",
    }
    assert all(
        TOOL_REGISTRY[item.tool].mode.value in {"read", "draft"}
        for item in agent_report.actions
    )
    assert local_hub.list_executions(report.task_id) == []
    assert TOOL_REGISTRY["attribution.quality.accept"].requires_approval is True


def test_attribution_http_rbac_and_shadow_report():
    previous_settings = authorizer.settings
    previous_store = hub.store
    previous_campaigns = hub.campaigns
    previous_attribution = hub.attribution
    authorizer.settings = HubSettings(
        auth_mode="static_token",
        viewer_token="viewer-secret",
        operator_token="operator-secret",
        owner_token="owner-secret",
    )
    store = MemoryHubStore()
    campaigns, _, _, _, touchpoints, observations = build_fixture(store)
    hub.store = store
    hub.campaigns = campaigns
    hub.attribution = AttributionService(store)
    client = TestClient(app)
    viewer = {"Authorization": "Bearer viewer-secret"}
    operator = {"Authorization": "Bearer operator-secret"}
    owner = {"Authorization": "Bearer owner-secret"}
    try:
        payload = {"touchpoints": [touchpoints[0].model_dump(mode="json")]}
        assert client.post(
            "/api/v1/attribution/touchpoints/backfill", headers=viewer, json=payload
        ).status_code == 403
        duplicate = client.post(
            "/api/v1/attribution/touchpoints/backfill", headers=operator, json=payload
        )
        assert duplicate.status_code == 200
        assert duplicate.json()["duplicates"] == 1

        created = client.post(
            "/api/v1/attribution/reconciliations",
            headers=operator,
            json={"observations": [item.model_dump(mode="json") for item in observations]},
        )
        assert created.status_code == 201
        reconciliation_id = created.json()["reconciliation_id"]
        acceptance_url = f"/api/v1/attribution/reconciliations/{reconciliation_id}/acceptance"
        assert client.post(
            acceptance_url, headers=operator, json={"accepted": True}
        ).status_code == 403
        blocked = client.get(
            f"/api/v1/attribution/reconciliations/{reconciliation_id}/report",
            headers=viewer,
        )
        assert blocked.json()["attributed_revenue"] is None
        assert client.post(
            acceptance_url, headers=owner, json={"accepted": True, "note": "QA"}
        ).status_code == 200
        report = client.get(
            f"/api/v1/attribution/reconciliations/{reconciliation_id}/report?model=linear",
            headers=viewer,
        )
        assert report.status_code == 200
        assert report.json()["state"] == "calculated_shadow"
        assert report.json()["external_writes_enabled"] is False
        assert client.get("/api/v1/attribution/status", headers=viewer).status_code == 200
        assert client.get("/api/v1/attribution/audit", headers=viewer).status_code == 200
    finally:
        authorizer.settings = previous_settings
        hub.store = previous_store
        hub.campaigns = previous_campaigns
        hub.attribution = previous_attribution


def test_dashboard_exposes_read_only_attribution_workspace():
    assert "Attribution & Revenue OS" in DASHBOARD_HTML
    assert "Shadow chỉ-đọc" in DASHBOARD_HTML
    assert "/api/v1/attribution/status" in DASHBOARD_HTML
    assert "CAC/ROAS không được suy diễn" in DASHBOARD_HTML
