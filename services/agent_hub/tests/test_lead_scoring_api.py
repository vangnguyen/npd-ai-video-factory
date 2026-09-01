from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from npd_agent_hub.attribution_models import TouchpointEvent, TouchpointType
from npd_agent_hub.auth import authorizer
from npd_agent_hub.config import HubSettings
from npd_agent_hub.journeys import JourneyService
from npd_agent_hub.main import app
from npd_agent_hub.orchestrator import hub
from npd_agent_hub.store import MemoryHubStore


UTC = timezone.utc
CAMPAIGN_ID = "CMP-VGP-VINHTIEN-202609-01"


def seed(store: MemoryHubStore) -> None:
    rows = [
        TouchpointEvent(
            event_id="tpt_" + "1" * 32,
            campaign_id=CAMPAIGN_ID,
            event_type=TouchpointType.LEAD_CREATED,
            occurred_at=datetime(2026, 9, 1, 8, tzinfo=UTC),
            source_system="EspoCRM",
            channel="crm",
            lead_id="lead-001",
        ),
        TouchpointEvent(
            event_id="tpt_" + "2" * 32,
            campaign_id=CAMPAIGN_ID,
            event_type=TouchpointType.LANDING_VIEW,
            occurred_at=datetime(2026, 9, 1, 9, tzinfo=UTC),
            source_system="GA4",
            channel="web",
            lead_id="lead-001",
        ),
    ]
    for row in rows:
        store.append_touchpoint(row)


def test_lead_score_api_is_viewer_only_read_and_auditable():
    previous_settings = authorizer.settings
    previous_store = hub.store
    previous_journeys = hub.journeys
    authorizer.settings = HubSettings(
        auth_mode="static_token",
        viewer_token="viewer-secret",
        operator_token="operator-secret",
        owner_token="owner-secret",
    )
    store = MemoryHubStore()
    seed(store)
    hub.store = store
    hub.journeys = JourneyService(store)
    client = TestClient(app)
    viewer = {"Authorization": "Bearer viewer-secret"}
    owner = {"Authorization": "Bearer owner-secret"}

    try:
        response = client.get(
            "/api/v1/lead-scores/lead:lead-001",
            params={"as_of": "2026-09-01T12:00:00+00:00"},
            headers=viewer,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["methodology"] == "journey_momentum_v1"
        assert body["score_version"] == "phase-9a-score-v1"
        assert body["current_state"] == "engaged"
        assert [item["name"] for item in body["factors"]] == [
            "journey_state",
            "recency",
            "engagement_frequency",
        ]
        assert body["execution_enabled"] is False
        assert body["external_writes_enabled"] is False
        assert body["contains_raw_pii"] is False
        assert response.headers["cache-control"] == "no-store"

        assert (
            client.get(
                "/api/v1/lead-scores/lead:missing",
                params={"as_of": "2026-09-01T12:00:00+00:00"},
                headers=viewer,
            ).status_code
            == 404
        )
        assert (
            client.get(
                "/api/v1/lead-scores/lead:user@example.com",
                params={"as_of": "2026-09-01T12:00:00+00:00"},
                headers=viewer,
            ).status_code
            == 422
        )
        assert (
            client.get(
                "/api/v1/lead-scores/lead:lead-001",
                params={"as_of": "2026-09-01T12:00:00"},
                headers=viewer,
            ).status_code
            == 422
        )
        assert client.post(
            "/api/v1/lead-scores/lead:lead-001", headers=owner
        ).status_code == 405
    finally:
        authorizer.settings = previous_settings
        hub.store = previous_store
        hub.journeys = previous_journeys


def test_lead_score_openapi_preserves_v1_get_and_allows_only_static_sales_preview_post():
    paths = app.openapi()["paths"]
    score_paths = {
        path: set(operations)
        for path, operations in paths.items()
        if path.startswith("/api/v1/lead-scores")
    }

    assert score_paths == {
        "/api/v1/lead-scores/sales-preview": {"post"},
        "/api/v1/lead-scores/{subject_ref}": {"get"},
    }
    forbidden = ("execute", "contact", "send", "accept")
    assert not any(any(word in path for word in forbidden) for path in score_paths)
