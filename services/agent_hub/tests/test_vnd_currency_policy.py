from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx
import pytest
from pydantic import ValidationError

from npd_agent_hub.attribution_models import OpportunityObservation, OpportunityStatus
from npd_agent_hub.campaign_models import CampaignBudget
from npd_agent_hub.config import HubSettings
from npd_agent_hub.espocrm_opportunities import (
    EspoOpportunityError,
    EspoOpportunityReader,
)
from npd_agent_hub.marketing_sources import MarketingSourceReader


def test_business_contracts_default_to_vnd_and_reject_usd() -> None:
    assert CampaignBudget(amount=1).currency == "VND"
    assert CampaignBudget(amount=1, currency="vnd").currency == "VND"
    with pytest.raises(ValidationError, match="only VND is supported"):
        CampaignBudget(amount=1, currency="USD")

    observation = OpportunityObservation(
        opportunity_id="opp-vnd",
        stage="Open",
        status=OpportunityStatus.OPEN,
        amount=1,
        observed_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
    )
    assert observation.currency == "VND"


def test_opportunity_model_validation_rejects_usd_payload() -> None:
    with pytest.raises(ValidationError, match="only VND is supported"):
        OpportunityObservation(
            opportunity_id="opp-usd",
            stage="Open",
            status=OpportunityStatus.OPEN,
            amount=1,
            currency="USD",
            observed_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
        )


def test_espocrm_explicit_usd_is_rejected_without_relabelling() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(
            200,
            json={
                "total": 1,
                "list": [
                    {
                        "id": "opp-legacy-usd",
                        "stage": "Closed Won",
                        "amount": 1,
                        "amountCurrency": "USD",
                        "closeDate": "2026-08-26",
                        "modifiedAt": "2026-08-26 08:00:00",
                    }
                ],
            },
        )

    reader = EspoOpportunityReader(
        HubSettings(
            espocrm_url="https://crm.local",
            espocrm_api_key="read-only-key",
        ),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(EspoOpportunityError, match="only VND is accepted"):
        asyncio.run(reader.read(limit=1))


def test_meta_ads_usd_is_reported_failed_and_not_relabelled() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "account_name": "Test",
                        "campaign_id": "1",
                        "campaign_name": "Test",
                        "spend": "1",
                        "impressions": "1",
                        "clicks": "1",
                        "actions": [],
                        "account_currency": "USD",
                    }
                ]
            },
        )

    reader = MarketingSourceReader(
        HubSettings(
            meta_ads_account_id="123",
            meta_ads_access_token="read-only-token",
            meta_graph_version="v23.0",
        ),
        transport=httpx.MockTransport(handler),
    )
    result = asyncio.run(reader.read_all(period_days=1))
    assert result["source_status"]["meta_ads"] == "failed"
    assert result["sources"].get("meta_ads") is None
    assert "only VND is accepted" in result["source_errors"]["meta_ads"]
