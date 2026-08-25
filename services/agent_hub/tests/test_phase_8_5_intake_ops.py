from __future__ import annotations

from datetime import date, datetime, timezone

import fakeredis
from fastapi.testclient import TestClient

from npd_agent_hub.attribution import AttributionService
from npd_agent_hub.attribution_models import (
    CampaignIdentityMappingCreate,
    IdentitySource,
    SourceTouchpointEvent,
    SourceTouchpointIngestRequest,
    TouchpointType,
)
from npd_agent_hub.auth import authorizer
from npd_agent_hub.campaign_models import CampaignBudget, CampaignCreate, KPITarget
from npd_agent_hub.campaigns import CampaignService
from npd_agent_hub.config import HubSettings
from npd_agent_hub.dashboard import DASHBOARD_HTML
from npd_agent_hub.main import app
from npd_agent_hub.orchestrator import hub
from npd_agent_hub.store import MemoryHubStore, RedisHubStore
from npd_agent_hub.tool_registry import TOOL_REGISTRY


def create_campaign(campaigns: CampaignService, project_code: str = "VGP"):
    return campaigns.create(
        CampaignCreate(
            name=f"Lead Intake {project_code}",
            project=f"Project {project_code}",
            project_code=project_code,
            objective="Attribution intake quality",
            audience=["Pseudonymous lead events"],
            budget=CampaignBudget(amount=0),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
            kpi_targets=[
                KPITarget(name="Lead", target=1, unit="lead", funnel_stage="lead")
            ],
            owner="owner@example.com",
        ),
        actor="operator@example.com",
    )


def intake_event(event_id: str = "meta-lead-001") -> SourceTouchpointEvent:
    return SourceTouchpointEvent(
        source_event_id=event_id,
        source_system=IdentitySource.META_ADS,
        event_type=TouchpointType.LEAD_CREATED,
        occurred_at=datetime.now(timezone.utc),
        channel="paid_social",
        source_account_id="act-001",
        source_campaign_id="1200001",
        source_adset_id="1200011",
        source_ad_id="1200111",
        lead_id=f"lead-ref-{event_id}",
        utm_source="facebook",
        utm_medium="paid_social",
        metadata={"source_form_id": "form-001", "source_page_id": "page-001"},
    )


def register_mapping(service: AttributionService, campaign_id: str) -> None:
    service.register_identity_mapping(
        CampaignIdentityMappingCreate(
            source_system=IdentitySource.META_ADS,
            source_account_id="act-001",
            source_campaign_id="1200001",
            source_adset_id="1200011",
            source_ad_id="1200111",
            campaign_id=campaign_id,
            note="Owner verified Lead Intake IDs in the read-only source.",
        ),
        actor="owner@example.com",
    )


def test_unknown_intake_is_persisted_then_safely_replayed_after_mapping():
    store = MemoryHubStore()
    campaigns = CampaignService(store)
    campaign = create_campaign(campaigns)
    service = AttributionService(store)
    event = intake_event()

    first = service.ingest_source_touchpoints(
        SourceTouchpointIngestRequest(events=[event]), actor="n8n-lead-intake"
    )
    assert first.unknown == 1
    issue = service.list_intake_issues()[0]
    assert issue.status.value == "pending"
    assert issue.source_event.metadata["source_page_id"] == "page-001"
    assert service.identity_status().pending_intake_issues == 1
    assert service.preview_intake_issue(issue.issue_id).state == "unknown"

    register_mapping(service, campaign.campaign_id)
    preview = service.preview_intake_issue(issue.issue_id)
    assert preview.state == "ready_to_replay"
    assert preview.would_insert is True
    assert preview.candidate_campaign_ids == [campaign.campaign_id]

    replay = service.replay_intake_issue(issue.issue_id, actor="operator@example.com")
    assert replay.inserted == 1
    assert service.identity_status().pending_intake_issues == 0
    resolved = service.list_intake_issues(status="resolved")[0]
    assert resolved.resolved_campaign_id == campaign.campaign_id
    assert resolved.replay_snapshot_id == replay.snapshot_id
    assert resolved.external_writes_enabled is False
    assert service.replay_intake_issue(issue.issue_id, actor="operator@example.com").duplicates == 1


def test_conflicting_verified_evidence_stays_blocked():
    store = MemoryHubStore()
    campaigns = CampaignService(store)
    mapped = create_campaign(campaigns, "VGP")
    explicit = create_campaign(campaigns, "VNG")
    service = AttributionService(store)
    register_mapping(service, mapped.campaign_id)
    event = intake_event().model_copy(
        update={"canonical_campaign_id": explicit.campaign_id}
    )

    snapshot = service.ingest_source_touchpoints(
        SourceTouchpointIngestRequest(events=[event]), actor="n8n-lead-intake"
    )
    assert snapshot.conflicts == 1
    issue = service.list_intake_issues()[0]
    preview = service.preview_intake_issue(issue.issue_id)
    assert preview.state == "conflict"
    assert set(preview.candidate_campaign_ids) == {
        mapped.campaign_id,
        explicit.campaign_id,
    }
    assert store.list_touchpoints() == []


def test_redis_recovers_pending_intake_queue_without_video_namespace():
    client = fakeredis.FakeRedis(decode_responses=True)
    store = RedisHubStore(client=client, namespace="test:agent-hub")
    CampaignService(store)
    service = AttributionService(store)
    service.ingest_source_touchpoints(
        SourceTouchpointIngestRequest(events=[intake_event("redis-lead-001")]),
        actor="n8n-lead-intake",
    )

    restarted = AttributionService(
        RedisHubStore(client=client, namespace="test:agent-hub")
    )
    assert restarted.list_intake_issues()[0].source_event.source_event_id == "redis-lead-001"
    keys = {str(key) for key in client.scan_iter("*")}
    assert any("attribution-os:intake-issue:" in key for key in keys)
    assert not any("npd:video-jobs" in key for key in keys)


def test_intake_api_rbac_and_replay_boundary():
    old_settings = authorizer.settings
    old_store, old_campaigns, old_attribution = hub.store, hub.campaigns, hub.attribution
    authorizer.settings = HubSettings(
        auth_mode="static_token",
        viewer_token="viewer-secret",
        operator_token="operator-secret",
        owner_token="owner-secret",
    )
    store = MemoryHubStore()
    campaigns = CampaignService(store)
    campaign = create_campaign(campaigns)
    attribution = AttributionService(store)
    hub.store, hub.campaigns, hub.attribution = store, campaigns, attribution
    client = TestClient(app)
    viewer = {"Authorization": "Bearer viewer-secret"}
    operator = {"Authorization": "Bearer operator-secret"}
    try:
        attribution.ingest_source_touchpoints(
            SourceTouchpointIngestRequest(events=[intake_event("api-lead-001")]),
            actor="n8n-lead-intake",
        )
        issue_id = attribution.list_intake_issues()[0].issue_id
        base = f"/api/v1/attribution/intake/issues/{issue_id}"
        assert client.get("/api/v1/attribution/intake/issues", headers=viewer).status_code == 200
        assert client.get(f"{base}/preview", headers=viewer).json()["state"] == "unknown"
        assert client.post(f"{base}/replay", headers=viewer).status_code == 403
        assert client.post(f"{base}/replay", headers=operator).status_code == 409

        register_mapping(attribution, campaign.campaign_id)
        replay = client.post(f"{base}/replay", headers=operator)
        assert replay.status_code == 200
        assert replay.json()["inserted"] == 1
        assert replay.json()["external_writes_enabled"] is False
    finally:
        authorizer.settings = old_settings
        hub.store, hub.campaigns, hub.attribution = (
            old_store,
            old_campaigns,
            old_attribution,
        )


def test_phase_8_5_ui_and_capabilities_remain_non_executing():
    assert "Lead Intake exception queue" in DASHBOARD_HTML
    assert "/api/v1/attribution/intake/issues" in DASHBOARD_HTML
    assert "Replay shadow" in DASHBOARD_HTML
    assert TOOL_REGISTRY["attribution.intake.issue.read"].mode.value == "read"
    replay = TOOL_REGISTRY["attribution.intake.issue.replay"]
    assert replay.mode.value == "draft"
    assert replay.execution_state.value == "planning_only"
    assert TOOL_REGISTRY["ads.launch"].execution_state.value == "disabled"
