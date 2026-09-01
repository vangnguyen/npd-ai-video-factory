from __future__ import annotations

from datetime import datetime, timezone
import json

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


def test_phase9_shadow_evaluation_api_is_operator_only_aggregate_and_non_persisting():
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
        "subject_refs": ["lead:lead-001", "lead:missing", "lead:lead-001"],
        "as_of": "2026-09-01T12:00:00+00:00",
    }

    try:
        assert (
            client.post(
                "/api/v1/phase9/shadow-evaluation/preview",
                json=payload,
                headers=viewer,
            ).status_code
            == 403
        )
        before_touchpoints = store.list_touchpoints(limit=100)
        response = client.post(
            "/api/v1/phase9/shadow-evaluation/preview",
            json=payload,
            headers=operator,
        )
        after_touchpoints = store.list_touchpoints(limit=100)

        assert response.status_code == 200
        body = response.json()
        assert body["evaluation_version"] == "phase-9a-shadow-eval-v1"
        assert body["requested_subject_count"] == 3
        assert body["unique_subject_count"] == 2
        assert body["duplicate_subject_count"] == 1
        assert body["evaluated_subject_count"] == 1
        assert body["failed_subject_count"] == 1
        assert body["failure_counts"] == {"not_found": 1}
        assert body["aggregate_only"] is True
        assert body["contains_subject_ids"] is False
        assert body["persisted"] is False
        assert body["execution_enabled"] is False
        assert body["external_writes_enabled"] is False
        assert body["customer_contact_enabled"] is False
        assert response.headers["cache-control"] == "no-store"

        serialized = json.dumps(body, ensure_ascii=False)
        assert "lead-001" not in serialized
        assert "lead:missing" not in serialized
        assert before_touchpoints == after_touchpoints
        assert store.list_recent_tasks(10) == []
    finally:
        authorizer.settings = previous_settings
        hub.store = previous_store
        hub.journeys = previous_journeys


def test_phase9_shadow_evaluation_openapi_is_preview_only():
    paths = app.openapi()["paths"]
    phase9_paths = {
        path: set(operations)
        for path, operations in paths.items()
        if path.startswith("/api/v1/phase9/shadow-evaluation")
    }

    assert phase9_paths == {
        "/api/v1/phase9/shadow-evaluation/preview": {"post"},
    }
    forbidden = ("execute", "accept", "send", "contact", "publish")
    assert not any(any(word in path for word in forbidden) for path in phase9_paths)
