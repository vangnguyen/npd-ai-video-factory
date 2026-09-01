from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from npd_agent_hub.config import HubSettings
from npd_agent_hub.espocrm_journey_evidence import (
    EspoJourneyEvidenceError,
    EspoJourneyEvidenceReader,
)
from npd_agent_hub.espocrm_opportunities import EspoOpportunityReader
from npd_agent_hub.journey_models import JourneyState


CAMPAIGN_ID = "CMP-VGP-VINHTIEN-202609-01"


def settings(stage_map: dict[str, str] | str) -> HubSettings:
    raw = json.dumps(stage_map) if isinstance(stage_map, dict) else stage_map
    return HubSettings(
        espocrm_url="https://crm.example.test",
        espocrm_api_key="test-key",
        espocrm_opportunity_campaign_field="cCampaignId",
        espocrm_journey_stage_map_json=raw,
    )


def test_preview_emits_only_explicit_mapped_candidates_with_campaign_identity():
    requested_select = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requested_select
        assert request.method == "GET"
        assert request.url.path == "/api/v1/Opportunity"
        requested_select = request.url.params.get("select", "")
        return httpx.Response(
            200,
            json={
                "total": 4,
                "list": [
                    {
                        "id": "opp-001",
                        "stage": "Appointment Booked",
                        "amount": 0,
                        "amountCurrency": "VND",
                        "cCampaignId": CAMPAIGN_ID,
                        "createdAt": "2026-09-01T08:00:00Z",
                        "modifiedAt": "2026-09-01T09:00:00Z",
                    },
                    {
                        "id": "opp-002",
                        "stage": "Site Visit",
                        "amount": 0,
                        "amountCurrency": "VND",
                        "campaignId": "espo-campaign-002",
                        "createdAt": "2026-09-01T08:00:00Z",
                        "modifiedAt": "2026-09-01T10:00:00Z",
                    },
                    {
                        "id": "opp-003",
                        "stage": "Prospecting",
                        "amount": 0,
                        "amountCurrency": "VND",
                        "cCampaignId": CAMPAIGN_ID,
                        "createdAt": "2026-09-01T08:00:00Z",
                        "modifiedAt": "2026-09-01T11:00:00Z",
                    },
                    {
                        "id": "opp-004",
                        "stage": "Closed Lost",
                        "amount": 0,
                        "amountCurrency": "VND",
                        "createdAt": "2026-09-01T08:00:00Z",
                        "modifiedAt": "2026-09-01T12:00:00Z",
                    },
                ],
            },
        )

    config = settings(
        {
            "Appointment Booked": "appointment",
            "Site Visit": "site_visit",
            "Closed Lost": "lost",
        }
    )
    opportunity_reader = EspoOpportunityReader(
        config,
        transport=httpx.MockTransport(handler),
    )
    preview = asyncio.run(
        EspoJourneyEvidenceReader(
            opportunity_reader=opportunity_reader,
            settings=config,
        ).preview()
    )

    assert preview.status == "partial"
    assert preview.records_read == 4
    assert preview.configured_stage_count == 3
    assert len(preview.candidates) == 2
    assert preview.skipped_unmapped == 1
    assert preview.skipped_missing_campaign_identity == 1
    assert preview.stage_mapping == {
        "Appointment Booked": JourneyState.APPOINTMENT,
        "Site Visit": JourneyState.SITE_VISIT,
        "Closed Lost": JourneyState.LOST,
    }
    assert "email" not in requested_select.casefold()
    assert "phone" not in requested_select.casefold()
    assert "name" not in requested_select.casefold()

    first, second = preview.candidates
    assert first.canonical_campaign_id == CAMPAIGN_ID
    assert first.source_campaign_id is None
    assert first.opportunity_id == "opp-001"
    assert first.metadata["journey_evidence"] == {
        "contract_version": "phase-9a-sales-v1",
        "state": "appointment",
        "source_record_ref": "espo-opportunity-opp-001",
        "external_writes_enabled": False,
    }
    assert second.canonical_campaign_id is None
    assert second.source_campaign_id == "espo-campaign-002"
    assert second.metadata["journey_evidence"]["state"] == "site_visit"
    assert preview.ingest_enabled is False
    assert preview.execution_enabled is False
    assert preview.external_writes_enabled is False


def test_missing_stage_map_returns_not_configured_without_provider_request():
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        raise AssertionError("provider must not be called without an explicit stage map")

    config = settings("")
    reader = EspoJourneyEvidenceReader(
        opportunity_reader=EspoOpportunityReader(
            config,
            transport=httpx.MockTransport(handler),
        ),
        settings=config,
    )

    preview = asyncio.run(reader.preview())

    assert preview.status == "not_configured"
    assert preview.candidates == []
    assert called is False


def test_invalid_stage_mapping_fails_before_network_and_does_not_infer_base_states():
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        raise AssertionError("provider must not be called for invalid mapping")

    for raw in (
        "not-json",
        json.dumps(["Appointment"]),
        json.dumps({"Appointment": "won"}),
        json.dumps({"Appointment": "unsupported_state"}),
    ):
        config = settings(raw)
        reader = EspoJourneyEvidenceReader(
            opportunity_reader=EspoOpportunityReader(
                config,
                transport=httpx.MockTransport(handler),
            ),
            settings=config,
        )
        with pytest.raises(EspoJourneyEvidenceError):
            asyncio.run(reader.preview())

    assert called is False


def test_stage_matching_is_normalized_but_mapping_remains_explicit():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "total": 1,
                "list": [
                    {
                        "id": "opp-005",
                        "stage": "  APPOINTMENT   BOOKED ",
                        "amount": 0,
                        "amountCurrency": "VND",
                        "cCampaignId": CAMPAIGN_ID,
                        "modifiedAt": "2026-09-01T13:00:00Z",
                    }
                ],
            },
        )

    config = settings({"Appointment Booked": "appointment"})
    preview = asyncio.run(
        EspoJourneyEvidenceReader(
            opportunity_reader=EspoOpportunityReader(
                config,
                transport=httpx.MockTransport(handler),
            ),
            settings=config,
        ).preview()
    )

    assert preview.status == "available"
    assert len(preview.candidates) == 1
    assert preview.candidates[0].metadata["journey_evidence"]["state"] == "appointment"
