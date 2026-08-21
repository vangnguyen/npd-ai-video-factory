from __future__ import annotations

from datetime import date, datetime, timezone

import fakeredis
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from npd_agent_hub.attribution import AttributionService
from npd_agent_hub.attribution_models import (
    CampaignIdentityMappingCreate,
    FreshnessState,
    IdentityResolutionState,
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


UTC = timezone.utc


def create_campaign(
    campaigns: CampaignService, *, project: str, project_code: str, name: str
):
    return campaigns.create(
        CampaignCreate(
            name=name,
            project=project,
            project_code=project_code,
            objective="Đo lường nguồn lead và chất lượng attribution",
            audience=["Khách hàng quan tâm bất động sản"],
            budget=CampaignBudget(amount=100_000_000),
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30),
            kpi_targets=[
                KPITarget(name="Lead", target=300, unit="lead", funnel_stage="lead")
            ],
            owner="owner@example.com",
        ),
        actor="operator",
    )


def register_meta(
    attribution: AttributionService,
    *,
    campaign_id: str,
    source_campaign_id: str,
    source_ad_id: str,
):
    return attribution.register_identity_mapping(
        CampaignIdentityMappingCreate(
            source_system=IdentitySource.META_ADS,
            source_account_id="act-001",
            source_campaign_id=source_campaign_id,
            source_ad_id=source_ad_id,
            campaign_id=campaign_id,
            note="Owner verified numeric IDs against Meta read-only API.",
        ),
        actor="owner@example.com",
    )


def source_event(
    *,
    source_event_id: str,
    source_campaign_id: str,
    source_ad_id: str,
    lead_id: str,
    canonical_campaign_id: str | None = None,
    metadata: dict[str, object] | None = None,
) -> SourceTouchpointEvent:
    return SourceTouchpointEvent(
        source_event_id=source_event_id,
        source_system=IdentitySource.META_ADS,
        event_type=TouchpointType.FORM_SUBMIT,
        occurred_at=datetime.now(UTC),
        channel="paid_social",
        canonical_campaign_id=canonical_campaign_id,
        source_account_id="act-001",
        source_campaign_id=source_campaign_id,
        source_ad_id=source_ad_id,
        lead_id=lead_id,
        utm_source="facebook",
        utm_medium="paid_social",
        metadata=metadata or {},
    )


def test_owner_verified_registry_separates_projects_without_name_inference():
    store = MemoryHubStore()
    campaigns = CampaignService(store)
    vinh_tien = create_campaign(
        campaigns,
        project="Vinhomes Green Paradise - Vịnh Tiên",
        project_code="VGP",
        name="Vịnh Tiên tháng 9",
    )
    vinh_ngoc = create_campaign(
        campaigns,
        project="Vịnh Ngọc",
        project_code="VNG",
        name="Vịnh Ngọc tháng 9",
    )
    attribution = AttributionService(store)

    first = register_meta(
        attribution,
        campaign_id=vinh_tien.campaign_id,
        source_campaign_id="1200001",
        source_ad_id="1200101",
    )
    repeated = register_meta(
        attribution,
        campaign_id=vinh_tien.campaign_id,
        source_campaign_id="1200001",
        source_ad_id="1200101",
    )
    second = register_meta(
        attribution,
        campaign_id=vinh_ngoc.campaign_id,
        source_campaign_id="1200001",
        source_ad_id="1200102",
    )

    assert repeated.mapping_id == first.mapping_id
    assert first.project != second.project
    assert len(attribution.list_identity_mappings()) == 2
    assert "name" not in CampaignIdentityMappingCreate.model_fields

    with pytest.raises(ValueError, match="overlaps a different Campaign"):
        attribution.register_identity_mapping(
            CampaignIdentityMappingCreate(
                source_system=IdentitySource.META_ADS,
                source_account_id="act-001",
                source_campaign_id="1200001",
                campaign_id=vinh_ngoc.campaign_id,
                note="Broad mapping would conflict with the verified Vịnh Tiên ad.",
            ),
            actor="owner@example.com",
        )


def test_ingest_resolves_deduplicates_and_reports_unknown_conflicts():
    store = MemoryHubStore()
    campaigns = CampaignService(store)
    vinh_tien = create_campaign(
        campaigns, project="Vịnh Tiên", project_code="VGP", name="Vịnh Tiên"
    )
    vinh_ngoc = create_campaign(
        campaigns, project="Vịnh Ngọc", project_code="VNG", name="Vịnh Ngọc"
    )
    attribution = AttributionService(store)
    register_meta(
        attribution,
        campaign_id=vinh_tien.campaign_id,
        source_campaign_id="1200001",
        source_ad_id="1200101",
    )
    register_meta(
        attribution,
        campaign_id=vinh_ngoc.campaign_id,
        source_campaign_id="1200001",
        source_ad_id="1200102",
    )
    first = source_event(
        source_event_id="meta-lead-001",
        source_campaign_id="1200001",
        source_ad_id="1200101",
        lead_id="lead-hash-001",
    )
    snapshot = attribution.ingest_source_touchpoints(
        SourceTouchpointIngestRequest(
            events=[
                first,
                source_event(
                    source_event_id="meta-lead-002",
                    source_campaign_id="1200001",
                    source_ad_id="1200102",
                    lead_id="lead-hash-002",
                ),
                source_event(
                    source_event_id="meta-lead-003",
                    source_campaign_id="1200001",
                    source_ad_id="1200999",
                    lead_id="lead-hash-003",
                    metadata={"campaign_label": "Vịnh Tiên must not be inferred"},
                ),
                source_event(
                    source_event_id="meta-lead-004",
                    source_campaign_id="1200001",
                    source_ad_id="1200102",
                    lead_id="lead-hash-004",
                    canonical_campaign_id=vinh_tien.campaign_id,
                ),
                first,
            ]
        ),
        actor="operator@example.com",
    )

    assert snapshot.received == 5
    assert snapshot.resolved == 3
    assert snapshot.inserted == 2
    assert snapshot.duplicates == 1
    assert snapshot.unknown == 1
    assert snapshot.conflicts == 1
    assert snapshot.coverage_rate == 0.6
    assert snapshot.mismatch_rate == 0.4
    assert snapshot.freshness_state == FreshnessState.FRESH
    assert {item.state for item in snapshot.issues} == {
        IdentityResolutionState.UNKNOWN,
        IdentityResolutionState.CONFLICT,
    }
    rows = attribution.list_touchpoints(limit=20)
    assert {item.campaign_id for item in rows} == {
        vinh_tien.campaign_id,
        vinh_ngoc.campaign_id,
    }
    assert all(item.metadata["external_side_effect"] is False for item in rows)
    assert attribution.identity_status().production_write_enabled is False


def test_utm_contract_resolves_without_guessing_source_campaign_name():
    store = MemoryHubStore()
    campaigns = CampaignService(store)
    campaign = create_campaign(
        campaigns, project="Vịnh Tiên", project_code="VGP", name="Vịnh Tiên"
    )
    attribution = AttributionService(store)
    event = SourceTouchpointEvent(
        source_event_id="ga4-event-001",
        source_system=IdentitySource.GA4,
        event_type=TouchpointType.FORM_SUBMIT,
        occurred_at=datetime.now(UTC),
        channel="web",
        lead_id="lead-hash-ga4",
        utm_campaign=campaign.tracking.utm_campaign,
        utm_source="google",
        utm_medium="cpc",
    )
    result = attribution.ingest_source_touchpoints(
        SourceTouchpointIngestRequest(events=[event]), actor="operator"
    )
    assert result.inserted == 1
    stored = attribution.list_touchpoints(limit=1)[0]
    assert stored.campaign_id == campaign.campaign_id
    assert stored.metadata["identity_resolution"] == ["utm_contract"]


def test_quality_snapshot_marks_old_source_data_stale():
    store = MemoryHubStore()
    campaigns = CampaignService(store)
    campaign = create_campaign(
        campaigns, project="Vịnh Tiên", project_code="VGP", name="Vịnh Tiên"
    )
    attribution = AttributionService(store)
    register_meta(
        attribution,
        campaign_id=campaign.campaign_id,
        source_campaign_id="1200001",
        source_ad_id="1200101",
    )
    old = source_event(
        source_event_id="meta-old-001",
        source_campaign_id="1200001",
        source_ad_id="1200101",
        lead_id="lead-hash-old",
    ).model_copy(update={"occurred_at": datetime(2026, 1, 1, tzinfo=UTC)})
    snapshot = attribution.ingest_source_touchpoints(
        SourceTouchpointIngestRequest(events=[old], stale_after_hours=72),
        actor="operator",
    )
    assert snapshot.freshness_state == FreshnessState.STALE
    assert snapshot.freshness_age_hours is not None
    assert snapshot.freshness_age_hours > 72


def test_source_ingest_rejects_pii_and_changed_immutable_payload():
    with pytest.raises(ValidationError, match="raw PII"):
        source_event(
            source_event_id="meta-pii-001",
            source_campaign_id="1200001",
            source_ad_id="1200101",
            lead_id="lead-hash",
            metadata={"customer_email": "customer@example.com"},
        )
    with pytest.raises(ValidationError, match="cannot enable writes"):
        source_event(
            source_event_id="meta-write-001",
            source_campaign_id="1200001",
            source_ad_id="1200101",
            lead_id="lead-hash",
            metadata={"external_writes_enabled": True},
        )

    store = MemoryHubStore()
    campaigns = CampaignService(store)
    campaign = create_campaign(
        campaigns, project="Vịnh Tiên", project_code="VGP", name="Vịnh Tiên"
    )
    attribution = AttributionService(store)
    register_meta(
        attribution,
        campaign_id=campaign.campaign_id,
        source_campaign_id="1200001",
        source_ad_id="1200101",
    )
    original = source_event(
        source_event_id="meta-fixed-001",
        source_campaign_id="1200001",
        source_ad_id="1200101",
        lead_id="lead-hash-001",
    )
    attribution.ingest_source_touchpoints(
        SourceTouchpointIngestRequest(events=[original]), actor="operator"
    )
    changed = original.model_copy(update={"utm_content": "changed"})
    snapshot = attribution.ingest_source_touchpoints(
        SourceTouchpointIngestRequest(events=[changed]), actor="operator"
    )
    assert snapshot.inserted == 0
    assert snapshot.conflicts == 1
    assert "immutable ledger" in snapshot.issues[0].detail


def test_redis_recovers_identity_registry_quality_and_touchpoints():
    redis_client = fakeredis.FakeRedis(decode_responses=True)
    store = RedisHubStore(client=redis_client, namespace="test:agent-hub")
    campaigns = CampaignService(store)
    campaign = create_campaign(
        campaigns, project="Vịnh Tiên", project_code="VGP", name="Vịnh Tiên"
    )
    attribution = AttributionService(store)
    mapping = register_meta(
        attribution,
        campaign_id=campaign.campaign_id,
        source_campaign_id="1200001",
        source_ad_id="1200101",
    )
    snapshot = attribution.ingest_source_touchpoints(
        SourceTouchpointIngestRequest(
            events=[
                source_event(
                    source_event_id="meta-redis-001",
                    source_campaign_id="1200001",
                    source_ad_id="1200101",
                    lead_id="lead-hash-redis",
                )
            ]
        ),
        actor="operator",
    )
    restarted = AttributionService(
        RedisHubStore(client=redis_client, namespace="test:agent-hub")
    )
    assert restarted.list_identity_mappings()[0].mapping_id == mapping.mapping_id
    assert restarted.list_data_quality_snapshots()[0].snapshot_id == snapshot.snapshot_id
    assert restarted.identity_status().touchpoint_count == 1
    keys = {str(key) for key in redis_client.scan_iter("*")}
    assert any("attribution-os:identity-mapping:" in key for key in keys)
    assert any("attribution-os:data-quality:" in key for key in keys)
    assert not any("npd:video-jobs" in key for key in keys)


def test_identity_api_rbac_and_read_only_status():
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
    campaigns = CampaignService(store)
    campaign = create_campaign(
        campaigns, project="Vịnh Tiên", project_code="VGP", name="Vịnh Tiên"
    )
    hub.store = store
    hub.campaigns = campaigns
    hub.attribution = AttributionService(store)
    client = TestClient(app)
    viewer = {"Authorization": "Bearer viewer-secret"}
    operator = {"Authorization": "Bearer operator-secret"}
    owner = {"Authorization": "Bearer owner-secret"}
    mapping_payload = {
        "source_system": "meta_ads",
        "source_account_id": "act-001",
        "source_campaign_id": "1200001",
        "source_ad_id": "1200101",
        "campaign_id": campaign.campaign_id,
        "note": "Owner verified numeric IDs against Meta read-only API.",
    }
    try:
        url = "/api/v1/attribution/identity-mappings"
        assert client.post(url, headers=viewer, json=mapping_payload).status_code == 403
        assert client.post(url, headers=operator, json=mapping_payload).status_code == 403
        created = client.post(url, headers=owner, json=mapping_payload)
        assert created.status_code == 201
        assert created.json()["external_writes_enabled"] is False
        assert len(client.get(url, headers=viewer).json()) == 1

        ingest_payload = {
            "events": [
                source_event(
                    source_event_id="meta-api-001",
                    source_campaign_id="1200001",
                    source_ad_id="1200101",
                    lead_id="lead-hash-api",
                ).model_dump(mode="json")
            ]
        }
        ingest_url = "/api/v1/attribution/touchpoints/ingest"
        assert client.post(ingest_url, headers=viewer, json=ingest_payload).status_code == 403
        ingested = client.post(ingest_url, headers=operator, json=ingest_payload)
        assert ingested.status_code == 200
        assert ingested.json()["inserted"] == 1
        identity_status = client.get(
            "/api/v1/attribution/identity/status", headers=viewer
        )
        assert identity_status.status_code == 200
        assert identity_status.json()["mapping_count"] == 1
        assert identity_status.json()["production_write_enabled"] is False
        assert len(
            client.get("/api/v1/attribution/data-quality", headers=viewer).json()
        ) == 1
    finally:
        authorizer.settings = previous_settings
        hub.store = previous_store
        hub.campaigns = previous_campaigns
        hub.attribution = previous_attribution


def test_identity_capabilities_are_non_executing():
    assert TOOL_REGISTRY["attribution.identity.read"].mode.value == "read"
    register = TOOL_REGISTRY["attribution.identity.register"]
    assert register.requires_approval is True
    assert register.execution_state.value == "planning_only"
    ingest = TOOL_REGISTRY["attribution.touchpoint.ingest"]
    assert ingest.mode.value == "draft"
    assert ingest.execution_state.value == "planning_only"


def test_dashboard_exposes_identity_coverage_freshness_and_mismatch():
    assert "Campaign Identity & Data Quality" in DASHBOARD_HTML
    assert "/api/v1/attribution/identity/status" in DASHBOARD_HTML
    assert "/api/v1/attribution/identity-mappings" in DASHBOARD_HTML
    assert "Identity coverage" in DASHBOARD_HTML
    assert "Unknown / conflict" in DASHBOARD_HTML
    assert "không suy đoán dự án từ tên Ads" in DASHBOARD_HTML
