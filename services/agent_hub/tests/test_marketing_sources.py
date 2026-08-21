import asyncio
import json
from datetime import date, timedelta

import httpx

from npd_agent_hub.config import HubSettings
from npd_agent_hub.marketing_sources import MarketingSourceReader


def run(coro):
    return asyncio.run(coro)


def test_multi_source_reader_normalizes_meta_ga4_and_social_without_secret_leakage():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url), request.headers.get("Authorization")))
        if request.url.host == "graph.facebook.com":
            assert request.method == "GET"
            assert "account_name" in request.url.params["fields"]
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "campaign_id": "cmp-1",
                            "campaign_name": "Lead campaign",
                            "account_name": "Bat Dong San 1",
                            "spend": "1200000",
                            "impressions": "10000",
                            "clicks": "200",
                            "account_currency": "VND",
                            "actions": [
                                {"action_type": "lead", "value": "20"},
                                {"action_type": "onsite_conversion.lead_grouped", "value": "20"},
                                {"action_type": "link_click", "value": "200"},
                            ],
                        }
                    ]
                },
            )
        if request.url.host == "analyticsdata.googleapis.com":
            assert request.method == "POST"
            body = json.loads(request.content.decode("utf-8"))
            assert body["metrics"][0]["name"] == "sessions"
            return httpx.Response(
                200,
                json={
                    "metricHeaders": [
                        {"name": "sessions"},
                        {"name": "totalUsers"},
                        {"name": "keyEvents"},
                        {"name": "totalRevenue"},
                    ],
                    "rows": [
                        {
                            "dimensionValues": [{"value": "Paid Social"}],
                            "metricValues": [
                                {"value": "150"},
                                {"value": "120"},
                                {"value": "15"},
                                {"value": "0"},
                            ],
                        }
                    ],
                    "rowCount": 1,
                },
            )
        if request.url.host == "insights.internal.test":
            assert request.method == "GET"
            return httpx.Response(
                200,
                json={
                    "metrics": {
                        "reach": 5000,
                        "views": 7000,
                        "engagements": 450,
                        "clicks": 40,
                        "conversions": 3,
                        "private_field": "must-not-persist",
                    }
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    settings = HubSettings(
        meta_ads_account_id="123456",
        meta_ads_access_token="meta-secret",
        meta_graph_version="v23.0",
        ga4_property_id="987654",
        social_insights_url="https://insights.internal.test/read",
        social_insights_token="social-secret",
    )
    reader = MarketingSourceReader(
        settings,
        transport=httpx.MockTransport(handler),
        ga4_token_provider=lambda: "ga-secret",
    )

    result = run(reader.read_all(period_days=30))

    assert result["missing_sources"] == []
    assert result["source_status"] == {
        "crm": "available",
        "meta_ads": "available",
        "ga4": "available",
        "social": "available",
    }
    ads = result["sources"]["meta_ads"]
    assert ads["metrics"]["reported_cpl"] == 60000
    assert ads["metrics"]["ctr_pct"] == 2.0
    assert ads["metrics"]["currency"] == "VND"
    assert ads["campaigns"][0]["account_name"] == "Bat Dong San 1"
    assert result["sources"]["ga4"]["metrics"]["sessions"] == 150
    assert result["sources"]["social"]["metrics"]["reach"] == 5000
    serialized = json.dumps(result)
    assert "meta-secret" not in serialized
    assert "ga-secret" not in serialized
    assert "social-secret" not in serialized
    assert "private_field" not in serialized
    assert all("secret" not in url for _, url, _ in seen)


def test_source_failures_are_isolated_and_reported_as_partial_coverage():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "unavailable"})

    reader = MarketingSourceReader(
        HubSettings(social_insights_url="https://insights.internal.test/read"),
        transport=httpx.MockTransport(handler),
    )

    result = run(reader.read_all(period_days=7))

    assert result["source_status"]["crm"] == "available"
    assert result["source_status"]["social"] == "failed"
    assert result["source_status"]["meta_ads"] == "not_configured"
    assert result["sources"] == {}
    assert "social" in result["source_errors"]


def test_meta_ads_reader_aggregates_two_read_only_accounts():
    requested_accounts = []

    def handler(request: httpx.Request) -> httpx.Response:
        account_id = request.url.path.split("/")[-2].removeprefix("act_")
        requested_accounts.append(account_id)
        spend = "100" if account_id == "111" else "250"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "campaign_id": f"cmp-{account_id}",
                        "campaign_name": f"Campaign {account_id}",
                        "account_name": f"Account {account_id}",
                        "spend": spend,
                        "impressions": "1000",
                        "clicks": "10",
                        "account_currency": "VND",
                        "actions": [{"action_type": "lead", "value": "2"}],
                    }
                ]
            },
        )

    reader = MarketingSourceReader(
        HubSettings(
            meta_ads_account_id="act_111, 222,111",
            meta_ads_access_token="meta-secret",
            meta_graph_version="v23.0",
        ),
        transport=httpx.MockTransport(handler),
    )

    result = run(reader.read_all(period_days=7))["sources"]["meta_ads"]

    assert set(requested_accounts) == {"111", "222"}
    assert result["account_ids"] == ["111", "222"]
    assert result["metrics"]["spend"] == 350
    assert result["metrics"]["reported_leads"] == 4
    assert {campaign["account_id"] for campaign in result["campaigns"]} == {"111", "222"}
    assert {campaign["account_name"] for campaign in result["campaigns"]} == {
        "Account 111",
        "Account 222",
    }


def test_meta_experiment_reader_uses_explicit_campaign_and_ad_mappings_only():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["level"] = request.url.params["level"]
        captured["filtering"] = json.loads(request.url.params["filtering"])
        captured["authorization"] = request.headers.get("Authorization")
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "campaign_id": "998877",
                        "ad_id": "101",
                        "spend": "1200000",
                        "impressions": "2000",
                        "clicks": "200",
                        "actions": [{"action_type": "lead", "value": "20"}],
                    },
                    {
                        "campaign_id": "998877",
                        "ad_id": "202",
                        "spend": "1500000",
                        "impressions": "2500",
                        "clicks": "250",
                        "actions": [{"action_type": "lead", "value": "30"}],
                    },
                    {
                        "campaign_id": "998877",
                        "ad_id": "unmapped",
                        "spend": "999999",
                        "impressions": "9999",
                        "clicks": "999",
                        "actions": [{"action_type": "lead", "value": "999"}],
                    },
                ]
            },
        )

    reader = MarketingSourceReader(
        HubSettings(
            meta_ads_account_id="123456",
            meta_ads_access_token="meta-read-only-secret",
            meta_graph_version="v23.0",
        ),
        transport=httpx.MockTransport(handler),
    )
    result = run(
        reader.read_meta_experiment(
            source_campaign_id="998877",
            variant_ad_ids={"VAR-CONTROL": "101", "VAR-HOOKA": "202"},
            since="2026-08-01",
            until="2026-08-14",
        )
    )
    assert captured["level"] == "ad"
    assert captured["filtering"] == [
        {"field": "campaign.id", "operator": "EQUAL", "value": "998877"}
    ]
    assert result["present_variant_ids"] == ["VAR-CONTROL", "VAR-HOOKA"]
    assert result["variants"] == [
        {
            "variant_id": "VAR-CONTROL",
            "sample_size": 2000,
            "conversions": 20,
            "guardrail_values": {"Cost per qualified lead": 60000.0},
        },
        {
            "variant_id": "VAR-HOOKA",
            "sample_size": 2500,
            "conversions": 30,
            "guardrail_values": {"Cost per qualified lead": 50000.0},
        },
    ]
    assert "meta-read-only-secret" not in json.dumps(result)


def test_meta_page_social_reader_uses_separate_read_only_credential_and_aggregate_fields():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url), request.headers.get("Authorization")))
        assert request.method == "GET"
        assert request.headers["Authorization"] == "Bearer social-page-secret"
        if request.url.path.endswith("/112233"):
            assert request.url.params["fields"] == "name,fan_count,followers_count"
            return httpx.Response(
                200,
                json={
                    "id": "112233",
                    "name": "Căn Hộ Express",
                    "fan_count": 1200,
                    "followers_count": 1350,
                },
            )
        if request.url.path.endswith("/112233/posts"):
            fields = request.url.params["fields"]
            assert "message" not in fields
            assert "comments.limit(0).summary(true)" in fields
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "created_time": "2026-08-20T00:00:00+0000",
                            "shares": {"count": 3},
                            "comments": {"summary": {"total_count": 4}},
                            "reactions": {"summary": {"total_count": 10}},
                        }
                    ]
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    settings = HubSettings(
        social_meta_page_id="112233",
        social_meta_access_token="social-page-secret",
        social_meta_graph_version="v23.0",
    )
    reader = MarketingSourceReader(settings, transport=httpx.MockTransport(handler))

    result = run(reader.read_all(period_days=7))

    assert result["source_status"]["social"] == "available"
    social = result["sources"]["social"]
    assert social["page_name"] == "Căn Hộ Express"
    assert social["metrics"] == {
        "posts": 1,
        "reactions": 10,
        "comments": 4,
        "shares": 3,
        "engagements": 17,
        "followers": 1350,
        "fans": 1200,
    }
    serialized = json.dumps(result)
    assert "social-page-secret" not in serialized
    assert all("social-page-secret" not in url for _, url, _ in seen)


def test_meta_page_one_day_reader_uses_nonzero_exclusive_graph_range():
    posts_params = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/112233"):
            return httpx.Response(
                200,
                json={"name": "Căn Hộ Express", "followers_count": 1350},
            )
        if request.url.path.endswith("/112233/posts"):
            posts_params.update(dict(request.url.params))
            return httpx.Response(200, json={"data": []})
        raise AssertionError(f"unexpected request: {request.url}")

    reader = MarketingSourceReader(
        HubSettings(
            social_meta_page_id="112233",
            social_meta_access_token="social-page-secret",
            social_meta_graph_version="v23.0",
        ),
        transport=httpx.MockTransport(handler),
    )

    result = run(reader.read_all(period_days=1))

    reported_day = date.fromisoformat(result["period_end"])
    assert result["source_status"]["social"] == "available"
    assert posts_params["since"] == reported_day.isoformat()
    assert posts_params["until"] == (reported_day + timedelta(days=1)).isoformat()
    assert result["sources"]["social"]["period_end"] == reported_day.isoformat()


def test_partial_native_social_configuration_is_not_treated_as_configured():
    reader = MarketingSourceReader(HubSettings(social_meta_page_id="112233"))

    assert reader.configuration_status()["social"] == "incomplete"
    result = run(reader.read_all(period_days=7))
    assert result["source_status"]["social"] == "not_configured"
