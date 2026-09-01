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
            event_type=TouchpointType.OPPORTUNITY_CREATED,
            occurred_at=datetime(2026, 9, 1, 9, tzinfo=UTC),
            source_system="EspoCRM",
            channel="crm",
            lead_id="lead-001",
            opportunity_id="opp-001",
        ),
    ]
    for row in rows:
        store.append_touchpoint(row)


def test_nba_get_and_preview_are_viewer_only_and_non_persisting():
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

    try:
        before = store.list_touchpoints(lead_id="lead-001", limit=100)
        get_response = client.get(
            "/api/v1/next-best-actions/lead:lead-001",
            params={"as_of": "2026-09-01T12:00:00+00:00"},
            headers=viewer,
        )
        preview_response = client.post(
            "/api/v1/next-best-actions/preview",
            json={
                "subject_ref": "lead:lead-001",
                "as_of": "2026-09-01T12:00:00+00:00",
            },
            headers=viewer,
        )
        after = store.list_touchpoints(lead_id="lead-001", limit=100)

        assert get_response.status_code == 200
        assert preview_response.status_code == 200
        assert get_response.json() == preview_response.json()
        body = get_response.json()
        assert body["recommendation_version"] == "phase-9a-nba-v1"
        assert body["sla_scope"] == "internal_review_only"
        assert body["execution_enabled"] is False
        assert body["external_writes_enabled"] is False
        assert body["customer_contact_enabled"] is False
        assert body["contains_raw_pii"] is False
        assert get_response.headers["cache-control"] == "no-store"
        assert [item.event_id for item in before] == [item.event_id for item in after]
        assert store.list_recent_tasks(10) == []

        assert (
            client.get(
                "/api/v1/next-best-actions/lead:user@example.com",
                headers=viewer,
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/v1/next-best-actions/preview",
                json={
                    "subject_ref": "lead:lead-001",
                    "as_of": "2026-09-01T12:00:00",
                },
                headers=viewer,
            ).status_code
            == 422
        )
    finally:
        authorizer.settings = previous_settings
        hub.store = previous_store
        hub.journeys = previous_journeys


def test_nba_openapi_has_read_and_preview_but_no_execution_accept_or_contact_route():
    paths = app.openapi()["paths"]
    core_nba_paths = {
        path: set(operations)
        for path, operations in paths.items()
        if path.startswith("/api/v1/next-best-actions")
        and not path.startswith("/api/v1/next-best-actions/reviews")
    }

    assert core_nba_paths == {
        "/api/v1/next-best-actions/{subject_ref}": {"get"},
        "/api/v1/next-best-actions/preview": {"post"},
    }
    forbidden = ("execute", "accept", "send", "contact")
    assert not any(any(word in path for word in forbidden) for path in core_nba_paths)
