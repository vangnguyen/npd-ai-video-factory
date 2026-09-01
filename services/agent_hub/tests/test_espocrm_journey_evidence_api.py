from __future__ import annotations

import json

import httpx
from fastapi.testclient import TestClient

from npd_agent_hub.auth import authorizer
from npd_agent_hub.config import HubSettings
from npd_agent_hub.espocrm_opportunities import EspoOpportunityReader
from npd_agent_hub.main import app
from npd_agent_hub.orchestrator import hub
from npd_agent_hub.store import MemoryHubStore


CAMPAIGN_ID = "CMP-VGP-VINHTIEN-202609-01"


def test_espocrm_journey_preview_is_operator_only_and_does_not_ingest():
    previous_settings = authorizer.settings
    previous_store = hub.store
    previous_reader = hub.opportunity_reader

    authorizer.settings = HubSettings(
        auth_mode="static_token",
        viewer_token="viewer-secret",
        operator_token="operator-secret",
        owner_token="owner-secret",
    )
    source_settings = HubSettings(
        espocrm_url="https://crm.example.test",
        espocrm_api_key="test-key",
        espocrm_opportunity_campaign_field="cCampaignId",
        espocrm_journey_stage_map_json=json.dumps(
            {"Appointment Booked": "appointment"}
        ),
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "total": 1,
                "list": [
                    {
                        "id": "opp-001",
                        "stage": "Appointment Booked",
                        "amount": 0,
                        "amountCurrency": "VND",
                        "cCampaignId": CAMPAIGN_ID,
                        "modifiedAt": "2026-09-01T09:00:00Z",
                    }
                ],
            },
        )

    store = MemoryHubStore()
    hub.store = store
    hub.opportunity_reader = EspoOpportunityReader(
        source_settings,
        transport=httpx.MockTransport(handler),
    )
    client = TestClient(app)
    viewer = {"Authorization": "Bearer viewer-secret"}
    operator = {"Authorization": "Bearer operator-secret"}

    try:
        assert (
            client.get(
                "/api/v1/journeys/sources/espocrm/preview",
                headers=viewer,
            ).status_code
            == 403
        )
        before = store.list_touchpoints(limit=100)
        response = client.get(
            "/api/v1/journeys/sources/espocrm/preview",
            headers=operator,
        )
        after = store.list_touchpoints(limit=100)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "available"
        assert len(body["candidates"]) == 1
        assert body["candidates"][0]["metadata"]["journey_evidence"]["state"] == "appointment"
        assert body["ingest_enabled"] is False
        assert body["execution_enabled"] is False
        assert body["external_writes_enabled"] is False
        assert response.headers["cache-control"] == "no-store"
        assert before == after == []
        assert store.list_recent_tasks(10) == []
    finally:
        authorizer.settings = previous_settings
        hub.store = previous_store
        hub.opportunity_reader = previous_reader


def test_espocrm_journey_preview_openapi_is_get_only():
    paths = app.openapi()["paths"]
    source_paths = {
        path: set(operations)
        for path, operations in paths.items()
        if path.startswith("/api/v1/journeys/sources/espocrm")
    }

    assert source_paths == {
        "/api/v1/journeys/sources/espocrm/preview": {"get"},
    }
    forbidden = ("ingest", "execute", "write", "contact")
    assert not any(any(word in path for word in forbidden) for path in source_paths)
