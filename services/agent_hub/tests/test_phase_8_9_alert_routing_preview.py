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


def alert(
    now,
    *,
    severity=ProviderAlertSeverity.CRITICAL,
    age_minutes=20,
    since_last_minutes=20,
    occurrence_count=2,
    status=ProviderAlertStatus.OPEN,
):
    return ProviderHealthAlert(
        alert_id="pha_1234567890abcdef12345678",
        dedupe_key="provider_health:n8n_lead_intake:freshness_stale",
        provider="n8n_lead_intake",
        alert_type="freshness_stale",
        severity=severity,
        detail="Producer heartbeat exceeded its freshness SLO.",
        first_detected_at=now - timedelta(minutes=age_minutes),
        last_detected_at=now - timedelta(minutes=since_last_minutes),
        occurrence_count=occurrence_count,
        status=status,
    )


def critical_alert(now):
    return alert(now)


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


def test_acknowledged_critical_alert_meeting_time_threshold_does_not_escalate():
    now = datetime(2026, 8, 22, 16, 0, tzinfo=UTC)
    store = MemoryHubStore()
    row = alert(
        now,
        age_minutes=20,
        occurrence_count=1,
        status=ProviderAlertStatus.ACKNOWLEDGED,
    )
    store.save_provider_alert(row)

    preview = service(store, now).routing_preview(row.alert_id)

    assert preview.suppression.value == "acknowledged"
    assert preview.escalation_would_apply is False


def test_acknowledged_critical_alert_meeting_occurrence_threshold_does_not_escalate():
    now = datetime(2026, 8, 22, 16, 0, tzinfo=UTC)
    store = MemoryHubStore()
    row = alert(
        now,
        age_minutes=5,
        since_last_minutes=20,
        occurrence_count=2,
        status=ProviderAlertStatus.ACKNOWLEDGED,
    )
    store.save_provider_alert(row)

    preview = service(store, now).routing_preview(row.alert_id)

    assert preview.suppression.value == "acknowledged"
    assert preview.escalation_would_apply is False


def test_resolved_critical_alert_meeting_thresholds_does_not_escalate():
    now = datetime(2026, 8, 22, 16, 0, tzinfo=UTC)
    store = MemoryHubStore()
    row = alert(
        now,
        status=ProviderAlertStatus.RESOLVED,
    ).model_copy(update={"resolved_at": now})
    store.save_provider_alert(row)

    preview = service(store, now).routing_preview(row.alert_id)

    assert preview.suppression.value == "resolved"
    assert preview.escalation_would_apply is False


def test_cooldown_alert_is_not_yet_eligible_for_escalation():
    now = datetime(2026, 8, 22, 16, 0, tzinfo=UTC)
    store = MemoryHubStore()
    row = alert(now, since_last_minutes=5)
    store.save_provider_alert(row)

    preview = service(store, now).routing_preview(row.alert_id)

    assert preview.suppression.value == "cooldown"
    assert preview.cooldown_remaining_minutes == 10
    assert preview.escalation_would_apply is False


def test_warning_alert_can_escalate_only_when_open_and_preview_eligible():
    now = datetime(2026, 8, 22, 16, 0, tzinfo=UTC)
    store = MemoryHubStore()
    row = alert(
        now,
        severity=ProviderAlertSeverity.WARNING,
        age_minutes=70,
        since_last_minutes=35,
        occurrence_count=3,
    )
    store.save_provider_alert(row)

    preview = service(store, now).routing_preview(row.alert_id)

    assert preview.suppression.value == "preview_eligible"
    assert preview.escalation_would_apply is True


def test_info_alert_has_no_escalation_policy():
    now = datetime(2026, 8, 22, 16, 0, tzinfo=UTC)
    store = MemoryHubStore()
    row = alert(
        now,
        severity=ProviderAlertSeverity.INFO,
        age_minutes=120,
        since_last_minutes=65,
        occurrence_count=20,
    )
    store.save_provider_alert(row)

    preview = service(store, now).routing_preview(row.alert_id)

    assert preview.suppression.value == "preview_eligible"
    assert preview.escalation_would_apply is False


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
