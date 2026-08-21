from __future__ import annotations

from datetime import date

import fakeredis
from fastapi.testclient import TestClient
from pydantic import ValidationError

from npd_agent_hub.auth import StaticTokenAuthorizer, authorizer
from npd_agent_hub.campaign_models import (
    CampaignApprovalDecision,
    CampaignBriefRequest,
    CampaignBudget,
    CampaignCreate,
    CampaignDraftUpdate,
    CampaignStatus,
    KPITarget,
    build_campaign_id,
)
from npd_agent_hub.campaign_providers import campaign_provider_contracts
from npd_agent_hub.campaigns import CampaignService
from npd_agent_hub.config import HubSettings
from npd_agent_hub.main import app
from npd_agent_hub.models import AgentName, AgentTask
from npd_agent_hub.orchestrator import AgentHub, hub
from npd_agent_hub.store import MemoryHubStore, RedisHubStore
from npd_agent_hub.tool_registry import TOOL_REGISTRY


def campaign_request() -> CampaignCreate:
    return CampaignCreate(
        name="Vịnh Tiên tháng 9",
        project="Vinhomes Green Paradise – Vịnh Tiên",
        project_code="VGP",
        objective="Tạo 300 lead và 30 khách đi xem",
        audience=["Nhà đầu tư", "Khách quan tâm Vịnh Tiên"],
        budget=CampaignBudget(amount=100_000_000),
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 30),
        kpi_targets=[
            KPITarget(name="Lead", target=300, unit="lead", funnel_stage="lead"),
            KPITarget(name="Đi xem", target=30, unit="booking", funnel_stage="site_visit"),
        ],
        owner="owner@example.com",
    )


def test_campaign_id_generation_and_validation():
    assert build_campaign_id(
        project_code="VGP",
        campaign_name="Vịnh Tiên",
        start_date=date(2026, 9, 1),
        sequence=1,
    ) == "CMP-VGP-VINHTIEN-202609-01"

    bad = campaign_request().model_dump()
    bad["crm_source_refs"] = {"access_token": "must-not-be-stored"}
    try:
        CampaignCreate.model_validate(bad)
        assert False, "Campaign input must reject secret-bearing keys"
    except ValidationError as exc:
        assert "cannot store secrets" in str(exc)


def test_zero_budget_existing_customer_source_is_valid_without_execution():
    request = campaign_request().model_copy(
        update={
            "name": "Khách hàng cũ",
            "project": "Vinhomes Sài Gòn Park",
            "project_code": "VSGP",
            "objective": "Ghi nhận doanh thu từ nguồn khách hàng cũ đã được owner xác nhận",
            "audience": ["Khách hàng cũ"],
            "budget": CampaignBudget(amount=0, currency="VND"),
            "kpi_targets": [
                KPITarget(
                    name="Giao dịch đã chốt",
                    target=1,
                    unit="opportunity",
                    funnel_stage="closed_won",
                )
            ],
            "crm_source_refs": {
                "source_type": "existing_customer",
                "classification": "owner_confirmed",
            },
        }
    )
    campaign = CampaignService(MemoryHubStore()).create(request, actor="owner")

    assert campaign.campaign_id == "CMP-VSGP-KHACHHANGCU-202609-01"
    assert campaign.budget.amount == 0
    assert campaign.status == CampaignStatus.DRAFT
    assert campaign.channel_plans == []
    assert campaign.approval_package
    assert all(not item.execution_enabled for item in campaign.approval_package)


def test_sample_vinh_tien_acceptance_creates_full_planning_package_without_side_effects():
    service = CampaignService(MemoryHubStore())
    campaign = service.create_from_brief(
        CampaignBriefRequest(
            request="Tạo chiến dịch Vịnh Tiên tháng 9, ngân sách 100 triệu, mục tiêu 300 lead và 30 khách đi xem.",
            owner="nguyenvanvangct@gmail.com",
        ),
        actor="operator@example.com",
    )

    assert campaign.campaign_id == "CMP-VGP-VINHTIEN-202609-01"
    assert campaign.status == CampaignStatus.PLANNED
    assert campaign.budget.amount == 100_000_000
    assert {plan.channel.value for plan in campaign.channel_plans} == {
        "meta_ads",
        "google_ads",
        "email",
        "zalo_zbs",
        "web_landing",
    }
    assert all(not plan.execution_enabled for plan in campaign.channel_plans)
    assert campaign.landing_pages[0].environment == "staging"
    assert not campaign.landing_pages[0].production_publish_enabled
    assert campaign.email_sequence_refs and not campaign.email_sequence_refs[0].live_send_enabled
    assert campaign.zalo_zbs_sequence_refs and not campaign.zalo_zbs_sequence_refs[0].live_send_enabled
    assert campaign.tracking.campaign_id == campaign.campaign_id
    assert campaign.tracking.lead_id == "{{lead_id}}"
    assert campaign.tracking.opportunity_id == "{{opportunity_id}}"
    assert campaign.sales_handoff.first_response_sla_minutes == 15
    assert all(not approval.execution_enabled for approval in campaign.approval_package)


def test_lifecycle_approval_boundary_and_audit_history():
    service = CampaignService(MemoryHubStore())
    campaign = service.create(campaign_request(), actor="operator")
    campaign = service.refresh_plans(campaign.campaign_id, actor="operator")
    campaign = service.request_approval(
        campaign.campaign_id, scope="campaign", actor="operator", note="Ready for review"
    )
    assert campaign.status == CampaignStatus.AWAITING_APPROVAL

    campaign = service.decide_approval(
        campaign.campaign_id,
        scope="campaign",
        decision=CampaignApprovalDecision(approved=True, note="Owner approved plan"),
        actor="owner",
    )
    assert campaign.status == CampaignStatus.APPROVED
    campaign = service.transition(
        campaign.campaign_id,
        target=CampaignStatus.READY_TO_EXECUTE,
        actor="operator",
        owner_authorized=False,
    )
    assert campaign.status == CampaignStatus.READY_TO_EXECUTE

    try:
        service.transition(
            campaign.campaign_id,
            target=CampaignStatus.ACTIVE,
            actor="owner",
            owner_authorized=True,
        )
        assert False, "Phase 6B must not activate live execution"
    except ValueError as exc:
        assert "production execution is disabled" in str(exc)

    history = service.history(campaign.campaign_id)
    assert [event.event_type for event in history[:4]] == [
        "status_transitioned",
        "approval_decided",
        "approval_requested",
        "channel_plans_refreshed",
    ]


def test_draft_safe_updates_stop_after_approval_request():
    service = CampaignService(MemoryHubStore())
    campaign = service.create(campaign_request(), actor="operator")
    updated = service.update_draft(
        campaign.campaign_id,
        CampaignDraftUpdate(objective="Updated draft objective"),
        actor="operator",
    )
    assert updated.objective == "Updated draft objective"
    planned = service.refresh_plans(campaign.campaign_id, actor="operator")
    service.request_approval(planned.campaign_id, scope="campaign", actor="operator")
    try:
        service.update_draft(
            planned.campaign_id,
            CampaignDraftUpdate(objective="Too late"),
            actor="operator",
        )
        assert False, "awaiting approval campaigns must be immutable through draft PATCH"
    except ValueError as exc:
        assert "draft-safe" in str(exc)


def test_specific_channel_plan_approval_returns_to_planned_for_next_scope():
    service = CampaignService(MemoryHubStore())
    campaign = service.create(campaign_request(), actor="operator")
    campaign = service.refresh_plans(campaign.campaign_id, actor="operator")
    campaign = service.request_approval(
        campaign.campaign_id, scope="meta_ads", actor="operator"
    )
    campaign = service.decide_approval(
        campaign.campaign_id,
        scope="meta_ads",
        decision=CampaignApprovalDecision(approved=True),
        actor="owner",
    )

    assert campaign.status == CampaignStatus.PLANNED
    assert next(
        plan for plan in campaign.channel_plans if plan.channel.value == "meta_ads"
    ).approval_state.value == "approved"
    assert next(
        item for item in campaign.approval_package if item.scope == "meta_ads"
    ).approved is True
    service.request_approval(campaign.campaign_id, scope="google_ads", actor="operator")


def test_redis_persistence_recovery_and_campaign_subnamespace():
    redis_client = fakeredis.FakeRedis(decode_responses=True)
    first = CampaignService(
        RedisHubStore(client=redis_client, namespace="test:agent-hub")
    )
    campaign = first.create_from_brief(
        CampaignBriefRequest(
            request="Tạo chiến dịch Vịnh Tiên tháng 9, ngân sách 100 triệu, mục tiêu 300 lead và 30 khách đi xem."
        ),
        actor="operator",
    )
    restarted = CampaignService(
        RedisHubStore(client=redis_client, namespace="test:agent-hub")
    )
    restored = restarted.get(campaign.campaign_id)

    assert restored.model_dump(mode="json") == campaign.model_dump(mode="json")
    keys = {str(key) for key in redis_client.scan_iter("*")}
    assert any(key.startswith("test:agent-hub:campaign-os:") for key in keys)
    assert not any("npd:video-jobs" in key for key in keys)
    assert restarted.history(campaign.campaign_id)


def test_four_specialists_plan_only_and_tool_policy_is_centralized():
    local_hub = AgentHub(store=MemoryHubStore())
    report = local_hub.run(
        AgentTask(
            objective="Tạo chiến dịch Vịnh Tiên tháng 9 với Ads, email, ZBS và landing page"
        )
    )
    assert report.selected_agents == [
        AgentName.MARKETING_LEADER,
        AgentName.PERFORMANCE_ADS,
        AgentName.EMAIL_MARKETING,
        AgentName.ZALO_ZBS_MARKETING,
        AgentName.WEB_LANDING,
    ]
    specialist_actions = [
        action
        for agent_report in report.reports
        if agent_report.agent != AgentName.MARKETING_LEADER
        for action in agent_report.actions
    ]
    assert specialist_actions
    assert all(TOOL_REGISTRY[action.tool].execution_state.value == "planning_only" for action in specialist_actions)
    assert all(not action.requires_approval for action in specialist_actions)
    assert local_hub.list_executions(report.task_id) == []
    for name in (
        "ads.launch",
        "email.bulk_send",
        "zalo_zbs.bulk_send",
        "landing.production_publish",
        "crm.mass_write",
        "sales.contact.send",
    ):
        assert TOOL_REGISTRY[name].requires_approval
        assert TOOL_REGISTRY[name].execution_state.value == "disabled"


def test_missing_campaign_providers_are_honest():
    contracts = campaign_provider_contracts()
    assert contracts["meta_ads"].status.value == "read_only"
    assert contracts["google_ads"].status.value == "not_configured"
    assert contracts["email"].status.value == "not_configured"
    assert contracts["zalo_zbs"].status.value == "not_configured"
    assert not any(contract.live_execution_enabled for contract in contracts.values())


def test_campaign_http_rbac_and_dashboard_api():
    previous = authorizer.settings
    previous_store = hub.store
    previous_campaigns = hub.campaigns
    authorizer.settings = HubSettings(
        auth_mode="static_token",
        viewer_token="viewer-secret",
        operator_token="operator-secret",
        owner_token="owner-secret",
    )
    store = MemoryHubStore()
    hub.store = store
    hub.campaigns = CampaignService(store)
    client = TestClient(app)
    viewer = {"Authorization": "Bearer viewer-secret"}
    operator = {"Authorization": "Bearer operator-secret"}
    owner = {"Authorization": "Bearer owner-secret"}
    payload = {
        "request": "Tạo chiến dịch Vịnh Tiên tháng 9, ngân sách 100 triệu, mục tiêu 300 lead và 30 khách đi xem."
    }
    try:
        assert client.post("/api/v1/campaigns/from-brief", headers=viewer, json=payload).status_code == 403
        created = client.post("/api/v1/campaigns/from-brief", headers=operator, json=payload)
        assert created.status_code == 201
        campaign = created.json()
        campaign_id = campaign["campaign_id"]
        assert client.get(f"/api/v1/campaigns/{campaign_id}", headers=viewer).status_code == 200
        assert client.get(f"/api/v1/campaigns/{campaign_id}/summary", headers=viewer).json()["execution_enabled"] is False

        requested = client.post(
            f"/api/v1/campaigns/{campaign_id}/approvals/request",
            headers=operator,
            json={"scope": "campaign"},
        )
        assert requested.status_code == 200
        decision_url = f"/api/v1/campaigns/{campaign_id}/approvals/campaign/decision"
        assert client.post(decision_url, headers=operator, json={"approved": True}).status_code == 403
        approved = client.post(decision_url, headers=owner, json={"approved": True})
        assert approved.status_code == 200
        assert approved.json()["status"] == "approved"
        assert client.get(f"/api/v1/campaigns/{campaign_id}/audit", headers=viewer).status_code == 200
        assert client.get("/api/v1/tools/capabilities", headers=viewer).status_code == 200
        assert client.get("/api/v1/integrations/campaign/status", headers=viewer).status_code == 200
    finally:
        authorizer.settings = previous
        hub.store = previous_store
        hub.campaigns = previous_campaigns
