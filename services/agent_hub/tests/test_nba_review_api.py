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


def test_nba_review_api_records_judgement_not_execution():
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
    store.append_touchpoint(
        TouchpointEvent(
            event_id="tpt_" + "1" * 32,
            campaign_id=CAMPAIGN_ID,
            event_type=TouchpointType.LEAD_CREATED,
            occurred_at=datetime(2026, 9, 1, 8, tzinfo=UTC),
            source_system="EspoCRM",
            channel="crm",
            lead_id="lead-001",
        )
    )
    hub.store = store
    hub.journeys = JourneyService(store)
    client = TestClient(app)
    viewer = {"Authorization": "Bearer viewer-secret"}
    operator = {"Authorization": "Bearer operator-secret"}

    payload = {
        "subject_ref": "lead:lead-001",
        "disposition": "not_relevant",
        "note": "Recommendation does not match the verified context.",
        "as_of": "2026-09-01T12:00:00+00:00",
    }

    try:
        assert (
            client.post(
                "/api/v1/next-best-actions/reviews",
                json=payload,
                headers=viewer,
            ).status_code
            == 403
        )
        created = client.post(
            "/api/v1/next-best-actions/reviews",
            json=payload,
            headers=operator,
        )
        assert created.status_code == 201
        body = created.json()
        assert body["disposition"] == "not_relevant"
        assert body["false_positive"] is True
        assert body["reviewer_role"] == "operator"
        assert body["recommendation_executed"] is False
        assert body["execution_enabled"] is False
        assert body["external_writes_enabled"] is False
        assert body["customer_contact_enabled"] is False

        listed = client.get(
            "/api/v1/next-best-actions/reviews",
            params={"subject_ref": "lead:lead-001"},
            headers=viewer,
        )
        assert listed.status_code == 200
        assert len(listed.json()) == 1

        summary = client.get(
            "/api/v1/next-best-actions/reviews/summary",
            params={"subject_ref": "lead:lead-001"},
            headers=viewer,
        )
        assert summary.status_code == 200
        assert summary.json()["false_positive_rate"] == 1.0
        assert store.list_recent_tasks(10) == []

        invalid_note = dict(payload)
        invalid_note["note"] = "Contact +84 912 345 678 before review."
        assert (
            client.post(
                "/api/v1/next-best-actions/reviews",
                json=invalid_note,
                headers=operator,
            ).status_code
            == 422
        )
    finally:
        authorizer.settings = previous_settings
        hub.store = previous_store
        hub.journeys = previous_journeys


def test_nba_review_openapi_has_telemetry_routes_but_no_accept_or_execute_route():
    paths = app.openapi()["paths"]
    review_paths = {
        path: set(operations)
        for path, operations in paths.items()
        if path.startswith("/api/v1/next-best-actions/reviews")
    }

    assert review_paths == {
        "/api/v1/next-best-actions/reviews": {"get", "post"},
        "/api/v1/next-best-actions/reviews/summary": {"get"},
    }
    forbidden = ("accept", "execute", "send", "contact")
    assert not any(any(word in path for word in forbidden) for path in review_paths)
