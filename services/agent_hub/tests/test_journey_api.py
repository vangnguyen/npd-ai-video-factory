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


def seed(store: MemoryHubStore) -> None:
    store.append_touchpoint(
        TouchpointEvent(
            event_id="tpt_" + "1" * 32,
            campaign_id="CMP-VGP-VINHTIEN-202609-01",
            event_type=TouchpointType.LEAD_CREATED,
            occurred_at=datetime(2026, 9, 1, 9, tzinfo=UTC),
            source_system="EspoCRM",
            channel="crm",
            lead_id="lead-001",
        )
    )
    store.append_touchpoint(
        TouchpointEvent(
            event_id="tpt_" + "2" * 32,
            campaign_id="CMP-VGP-VINHTIEN-202609-01",
            event_type=TouchpointType.LANDING_VIEW,
            occurred_at=datetime(2026, 9, 1, 10, tzinfo=UTC),
            source_system="GA4",
            channel="web",
            lead_id="lead-001",
        )
    )


def test_journey_http_surface_is_viewer_only_read_and_fail_closed():
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
        projection = client.get("/api/v1/journeys/lead:lead-001", headers=viewer)
        assert projection.status_code == 200
        body = projection.json()
        assert body["current_state"] == "engaged"
        assert body["shadow_mode"] is True
        assert body["execution_enabled"] is False
        assert body["external_writes_enabled"] is False
        assert body["contains_raw_pii"] is False
        assert projection.headers["cache-control"] == "no-store"

        history = client.get(
            "/api/v1/journeys/lead:lead-001/history", headers=viewer
        )
        assert history.status_code == 200
        assert [item["new_state"] for item in history.json()] == ["lead", "engaged"]

        assert client.get("/api/v1/journeys/lead:missing", headers=viewer).status_code == 404
        assert (
            client.get(
                "/api/v1/journeys/lead:user@example.com", headers=viewer
            ).status_code
            == 422
        )
        assert client.post("/api/v1/journeys/lead:lead-001", headers=owner).status_code == 405
    finally:
        authorizer.settings = previous_settings
        hub.store = previous_store
        hub.journeys = previous_journeys


def test_journey_openapi_exposes_get_only_and_no_execution_endpoint():
    paths = app.openapi()["paths"]
    journey_subject_paths = {
        path: set(operations)
        for path, operations in paths.items()
        if path.startswith("/api/v1/journeys")
        and not path.startswith("/api/v1/journeys/sources/")
    }

    assert journey_subject_paths == {
        "/api/v1/journeys/{subject_ref}": {"get"},
        "/api/v1/journeys/{subject_ref}/history": {"get"},
    }
    assert not any(
        "execute" in path or "contact" in path for path in journey_subject_paths
    )
