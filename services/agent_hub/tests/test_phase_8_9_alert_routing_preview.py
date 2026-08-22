from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from npd_agent_hub.attribution import AttributionService
from npd_agent_hub.auth import authorizer
from npd_agent_hub.config import HubSettings
from npd_agent_hub.dashboard import DASHBOARD_HTML
from npd_agent_hub.delivery_observability import AttributionDeliveryService
from npd_agent_hub.main import app
from npd_agent_hub.orchestrator import hub
from npd_agent_hub.provider_health import ProviderHealthService
from npd_agent_hub.provider_health_models import (
    ProviderAlertSeverity,
    ProviderAlertStatus,
    ProviderHealthAlert,
)
from npd_agent_hub.store import MemoryHubStore
from npd_agent_hub.tool_registry import TOOL_REGISTRY


UTC = timezone.utc


def service(store, now):
    settings = HubSettings(
        attribution_receipt_signing_key="phase-8-9-signing-key-000000000000000000000",
        attribution_receipt_key_id="phase-8-9-v1",
    )
    attribution = AttributionService(store)
    delivery = AttributionDeliveryService(store, attribution, settings, clock=lambda: now)
    return ProviderHealthService(store, delivery, clock=lambda: now)


def critical_alert(now):
    return ProviderHealthAlert(
        alert_id="pha_1234567890abcdef12345678",
        dedupe_key="provider_health:n8n_lead_intake:freshness_stale",
        provider="n8n_lead_intake",
        alert_type="freshness_stale",
        severity=ProviderAlertSeverity.CRITICAL,
        detail="Producer heartbeat exceeded its freshness SLO.",
        first_detected_at=now - timedelta(minutes=20),
        last_detected_at=now - timedelta(minutes=20),
        occurrence_count=2,
    )


def test_critical_routing_preview_models_dedupe_cooldown_and_escalation_without_send():
    now = datetime(2026, 8, 22, 16, 0, tzinfo=UTC)
    store = MemoryHubStore()
    alert = critical_alert(now)
    store.save_provider_alert(alert)

    preview = service(store, now).routing_preview(alert.alert_id)

    assert preview.suppression.value == "preview_eligible"
    assert preview.cooldown_remaining_minutes == 0
    assert preview.escalation_would_apply is True
    assert preview.policy.dedupe_window_minutes == 15
    assert preview.policy.escalation_target == "owner_review_preview"
    assert preview.policy.external_provider_state == "not_configured"
    assert set(preview.policy.candidate_external_channels) == {
        "email",
        "pwa",
        "zalo",
        "ticket",
    }
    assert preview.would_send is False
    assert preview.external_notifications_enabled is False
    assert preview.production_write_enabled is False


def test_acknowledged_and_resolved_alerts_are_suppressed_in_preview():
    now = datetime(2026, 8, 22, 16, 0, tzinfo=UTC)
    store = MemoryHubStore()
    alert = critical_alert(now)
    store.save_provider_alert(alert.model_copy(update={"status": ProviderAlertStatus.ACKNOWLEDGED}))
    provider_health = service(store, now)
    assert provider_health.routing_preview(alert.alert_id).suppression.value == "acknowledged"

    store.save_provider_alert(alert.model_copy(update={"status": ProviderAlertStatus.RESOLVED, "resolved_at": now}))
    assert provider_health.routing_preview(alert.alert_id).suppression.value == "resolved"


def test_routing_preview_api_is_viewer_readable_and_has_no_external_effect():
    now = datetime(2026, 8, 22, 16, 0, tzinfo=UTC)
    old_settings, old_store, old_health = authorizer.settings, hub.store, hub.provider_health
    authorizer.settings = HubSettings(
        auth_mode="static_token",
        viewer_token="viewer-secret",
        operator_token="operator-secret",
        owner_token="owner-secret",
    )
    store = MemoryHubStore()
    alert = critical_alert(now)
    store.save_provider_alert(alert)
    hub.store, hub.provider_health = store, service(store, now)
    try:
        client = TestClient(app)
        response = client.get(
            f"/api/v1/provider-health/alerts/{alert.alert_id}/routing-preview",
            headers={"Authorization": "Bearer viewer-secret"},
        )
        assert response.status_code == 200
        assert response.json()["would_send"] is False
        assert response.json()["policy"]["execution_state"] == "preview_only"
        assert client.get(
            "/api/v1/provider-health/alerts/pha_aaaaaaaaaaaaaaaaaaaaaaaa/routing-preview",
            headers={"Authorization": "Bearer viewer-secret"},
        ).status_code == 404
    finally:
        authorizer.settings = old_settings
        hub.store, hub.provider_health = old_store, old_health


def test_dashboard_and_registry_expose_preview_only_routing():
    assert "Preview routing" in DASHBOARD_HTML
    assert 'id="providerRoutingPreview"' in DASHBOARD_HTML
    assert "/routing-preview" in DASHBOARD_HTML
    assert "Would send: no" in DASHBOARD_HTML
    capability = TOOL_REGISTRY["provider.alert.routing.preview"]
    assert capability.mode.value == "draft"
    assert capability.execution_state.value == "planning_only"
    assert capability.dry_run_support is True
