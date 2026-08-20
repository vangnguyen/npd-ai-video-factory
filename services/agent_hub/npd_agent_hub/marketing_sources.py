from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from .config import HubSettings


ANALYTICS_READONLY_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
META_LEAD_ACTION_TYPES = (
    "lead",
    "onsite_conversion.lead_grouped",
    "offsite_conversion.fb_pixel_lead",
)


class MarketingSourceError(RuntimeError):
    pass


def _number(value: object) -> int | float:
    try:
        parsed = float(str(value))
    except (TypeError, ValueError):
        return 0
    return int(parsed) if parsed.is_integer() else round(parsed, 4)


def _sum_metric(rows: list[dict[str, Any]], name: str) -> int | float:
    return _number(sum(float(_number(row.get(name))) for row in rows))


def _reported_leads(actions: object) -> int | float:
    """Use one preferred Meta lead definition so overlapping actions are not double-counted."""
    totals: dict[str, float] = {}
    for item in actions if isinstance(actions, list) else []:
        if not isinstance(item, dict):
            continue
        action_type = str(item.get("action_type") or "")
        if action_type in META_LEAD_ACTION_TYPES:
            totals[action_type] = totals.get(action_type, 0) + float(_number(item.get("value")))
    for action_type in META_LEAD_ACTION_TYPES:
        if action_type in totals:
            return _number(totals[action_type])
    return 0


def _safe_https_url(value: str, *, name: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise MarketingSourceError(
            f"{name} must be an HTTPS URL without embedded credentials, query or fragment"
        )
    return value.rstrip("/")


class MarketingSourceReader:
    """Read and normalize aggregate marketing data without persisting credentials or PII."""

    def __init__(
        self,
        settings: HubSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        ga4_token_provider: Callable[[], str] | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport
        self.ga4_token_provider = ga4_token_provider

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self.settings.request_timeout_seconds,
            transport=self.transport,
        )

    def configuration_status(self) -> dict[str, str]:
        def status(values: tuple[str, ...]) -> str:
            present = sum(bool(value) for value in values)
            if present == len(values):
                return "configured"
            return "not_configured" if present == 0 else "incomplete"

        return {
            "crm": status((self.settings.espocrm_url, self.settings.espocrm_api_key)),
            "meta_ads": status(
                (
                    self.settings.meta_ads_account_id,
                    self.settings.meta_ads_access_token,
                    self.settings.meta_graph_version,
                )
            ),
            "ga4": (
                "configured"
                if self.settings.ga4_property_id and self.settings.ga4_service_account_file
                else "incomplete"
                if self.settings.ga4_property_id
                else "not_configured"
            ),
            "social": self._social_configuration_status(),
        }

    def _social_configuration_status(self) -> str:
        native_values = (
            self.settings.social_meta_page_id,
            self.settings.social_meta_access_token,
            self.settings.social_meta_graph_version,
        )
        native_present = sum(bool(value) for value in native_values)
        if native_present == len(native_values):
            return "configured"
        if native_present:
            return "incomplete"
        return "configured" if self.settings.social_insights_url else "not_configured"

    @staticmethod
    def _period(period_days: int) -> tuple[str, str]:
        until = date.today()
        since = until - timedelta(days=max(1, period_days) - 1)
        return since.isoformat(), until.isoformat()

    async def read_all(self, *, period_days: int) -> dict[str, object]:
        since, until = self._period(period_days)
        source_status: dict[str, str] = {"crm": "available"}
        sources: dict[str, dict[str, object]] = {}
        errors: dict[str, str] = {}

        configured = {
            "meta_ads": bool(
                self.settings.meta_ads_account_id
                and self.settings.meta_ads_access_token
                and self.settings.meta_graph_version
            ),
            "ga4": bool(
                self.settings.ga4_property_id
                and (self.settings.ga4_service_account_file or self.ga4_token_provider)
            ),
            "social": self._social_configuration_status() == "configured",
        }
        readers = {
            "meta_ads": self._read_meta_ads,
            "ga4": self._read_ga4,
            "social": self._read_social,
        }
        for name, reader in readers.items():
            if not configured[name]:
                source_status[name] = "not_configured"
                continue
            try:
                sources[name] = await reader(since=since, until=until)
                source_status[name] = "available"
            except MarketingSourceError as exc:
                source_status[name] = "failed"
                errors[name] = str(exc)
            except Exception:
                source_status[name] = "failed"
                errors[name] = f"{name} adapter failed unexpectedly"

        return {
            "period_start": since,
            "period_end": until,
            "source_status": source_status,
            "available_sources": [
                name for name, status in source_status.items() if status == "available"
            ],
            "missing_sources": [
                name for name, status in source_status.items() if status != "available"
            ],
            "source_errors": errors,
            "sources": sources,
        }

    async def _read_meta_ads(self, *, since: str, until: str) -> dict[str, object]:
        account_ids = tuple(
            dict.fromkeys(
                value.strip().removeprefix("act_")
                for value in self.settings.meta_ads_account_id.split(",")
                if value.strip()
            )
        )
        version = self.settings.meta_graph_version
        if not account_ids or any(not re.fullmatch(r"\d+", value) for value in account_ids):
            raise MarketingSourceError(
                "META_ADS_ACCOUNT_ID must contain one or more comma-separated numeric IDs"
            )
        if not re.fullmatch(r"v\d+\.\d+", version):
            raise MarketingSourceError("META_GRAPH_VERSION must be explicitly pinned, for example v23.0")

        params = {
            "level": "campaign",
            "fields": (
                "account_name,campaign_id,campaign_name,spend,impressions,clicks,"
                "actions,account_currency"
            ),
            "time_range": json.dumps({"since": since, "until": until}),
            "limit": "200",
        }
        headers = {"Authorization": f"Bearer {self.settings.meta_ads_access_token}"}

        async def fetch_account(
            client: httpx.AsyncClient, account_id: str
        ) -> tuple[str, dict[str, Any]]:
            url = f"https://graph.facebook.com/{version}/act_{account_id}/insights"
            try:
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise MarketingSourceError(
                    f"Meta Ads insights read failed for account {account_id}: {exc}"
                ) from exc
            try:
                payload = response.json()
            except ValueError as exc:
                raise MarketingSourceError(
                    f"Meta Ads returned invalid JSON for account {account_id}"
                ) from exc
            if not isinstance(payload, dict):
                raise MarketingSourceError(
                    f"Meta Ads returned a non-object response for account {account_id}"
                )
            return account_id, payload

        async with self._client() as client:
            account_payloads = await asyncio.gather(
                *(fetch_account(client, account_id) for account_id in account_ids)
            )

        campaigns = []
        currencies = set()
        coverage_complete = True
        for account_id, payload in account_payloads:
            raw_rows = payload.get("data")
            rows = [row for row in raw_rows or [] if isinstance(row, dict)]
            coverage_complete = coverage_complete and not bool(
                (payload.get("paging") or {}).get("next")
            )
            currencies.update(
                str(row.get("account_currency"))
                for row in rows
                if row.get("account_currency")
            )
            for row in rows:
                lead_actions = _reported_leads(row.get("actions"))
                campaigns.append(
                    {
                        "account_id": account_id,
                        "account_name": str(row.get("account_name") or f"act_{account_id}")[:200],
                        "campaign_id": str(row.get("campaign_id") or ""),
                        "campaign_name": str(row.get("campaign_name") or "Chưa xác định")[:200],
                        "spend": _number(row.get("spend")),
                        "impressions": _number(row.get("impressions")),
                        "clicks": _number(row.get("clicks")),
                        "reported_leads": _number(lead_actions),
                    }
                )
        spend = _sum_metric(campaigns, "spend")
        impressions = _sum_metric(campaigns, "impressions")
        clicks = _sum_metric(campaigns, "clicks")
        leads = _sum_metric(campaigns, "reported_leads")
        currency = next(iter(currencies)) if len(currencies) == 1 else ""
        return {
            "source": "Meta Ads Insights read-only",
            "period_start": since,
            "period_end": until,
            "account_ids": list(account_ids),
            "metrics": {
                "spend": spend,
                "impressions": impressions,
                "clicks": clicks,
                "reported_leads": leads,
                "ctr_pct": round(float(clicks) * 100 / float(impressions), 2) if impressions else 0,
                "cpc": round(float(spend) / float(clicks), 2) if clicks else 0,
                "reported_cpl": round(float(spend) / float(leads), 2) if leads else 0,
                "currency": currency,
            },
            "campaigns": campaigns,
            "coverage_complete": coverage_complete,
            "observed_at": datetime.now(timezone.utc).isoformat(),
        }

    def _ga4_token(self) -> str:
        if self.ga4_token_provider:
            token = self.ga4_token_provider()
            if token:
                return token
            raise MarketingSourceError("GA4 token provider returned an empty token")
        service_account_file = Path(self.settings.ga4_service_account_file)
        if not service_account_file.is_file():
            raise MarketingSourceError("GA4 service-account file is not available")
        try:
            from google.auth.transport.requests import Request
            from google.oauth2 import service_account

            credentials = service_account.Credentials.from_service_account_file(
                str(service_account_file), scopes=[ANALYTICS_READONLY_SCOPE]
            )
            credentials.refresh(Request())
        except Exception as exc:
            raise MarketingSourceError(f"GA4 read-only authentication failed: {exc}") from exc
        if not credentials.token:
            raise MarketingSourceError("GA4 authentication returned no access token")
        return credentials.token

    async def _read_ga4(self, *, since: str, until: str) -> dict[str, object]:
        if not re.fullmatch(r"\d+", self.settings.ga4_property_id):
            raise MarketingSourceError("GA4_PROPERTY_ID must contain digits only")
        token = await asyncio.to_thread(self._ga4_token)
        url = (
            "https://analyticsdata.googleapis.com/v1beta/properties/"
            f"{self.settings.ga4_property_id}:runReport"
        )
        body = {
            "dateRanges": [{"startDate": since, "endDate": until}],
            "dimensions": [{"name": "sessionDefaultChannelGroup"}],
            "metrics": [
                {"name": "sessions"},
                {"name": "totalUsers"},
                {"name": "keyEvents"},
                {"name": "totalRevenue"},
            ],
            "limit": "100",
        }
        async with self._client() as client:
            try:
                response = await client.post(
                    url,
                    json=body,
                    headers={"Authorization": f"Bearer {token}"},
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise MarketingSourceError(f"GA4 report read failed: {exc}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise MarketingSourceError("GA4 returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise MarketingSourceError("GA4 returned a non-object response")
        metric_names = [
            str(item.get("name") or "")
            for item in payload.get("metricHeaders") or []
            if isinstance(item, dict)
        ]
        channels = []
        for row in payload.get("rows") or []:
            if not isinstance(row, dict):
                continue
            dimensions = row.get("dimensionValues") or []
            values = row.get("metricValues") or []
            metrics = {
                name: _number(values[index].get("value"))
                for index, name in enumerate(metric_names)
                if index < len(values) and isinstance(values[index], dict)
            }
            channel = (
                str(dimensions[0].get("value") or "Chưa xác định")[:200]
                if dimensions and isinstance(dimensions[0], dict)
                else "Chưa xác định"
            )
            channels.append({"channel": channel, **metrics})
        return {
            "source": "Google Analytics Data API read-only",
            "period_start": since,
            "period_end": until,
            "metrics": {
                "sessions": _sum_metric(channels, "sessions"),
                "users": _sum_metric(channels, "totalUsers"),
                "key_events": _sum_metric(channels, "keyEvents"),
                "revenue": _sum_metric(channels, "totalRevenue"),
            },
            "channels": channels,
            "coverage_complete": int(payload.get("rowCount") or 0) <= len(channels),
            "observed_at": datetime.now(timezone.utc).isoformat(),
        }

    async def _read_social(self, *, since: str, until: str) -> dict[str, object]:
        if self.settings.social_meta_page_id:
            return await self._read_meta_page(since=since, until=until)

        url = _safe_https_url(self.settings.social_insights_url, name="SOCIAL_INSIGHTS_URL")
        headers = {}
        if self.settings.social_insights_token:
            headers["Authorization"] = f"Bearer {self.settings.social_insights_token}"
        async with self._client() as client:
            try:
                response = await client.get(
                    url, params={"since": since, "until": until}, headers=headers
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise MarketingSourceError(f"social insights read failed: {exc}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise MarketingSourceError("social insights returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise MarketingSourceError("social insights returned a non-object response")
        allowed_metrics = ("reach", "views", "engagements", "clicks", "conversions")
        raw_metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
        return {
            "source": "Configured social aggregate endpoint read-only",
            "period_start": since,
            "period_end": until,
            "metrics": {name: _number(raw_metrics.get(name)) for name in allowed_metrics},
            "coverage_complete": payload.get("coverage_complete") is not False,
            "observed_at": str(payload.get("observed_at") or datetime.now(timezone.utc).isoformat()),
        }

    async def _read_meta_page(self, *, since: str, until: str) -> dict[str, object]:
        page_id = self.settings.social_meta_page_id
        version = self.settings.social_meta_graph_version
        if not re.fullmatch(r"\d+", page_id):
            raise MarketingSourceError("SOCIAL_META_PAGE_ID must contain digits only")
        if not re.fullmatch(r"v\d+\.\d+", version):
            raise MarketingSourceError(
                "SOCIAL_META_GRAPH_VERSION must be explicitly pinned, for example v23.0"
            )

        base_url = f"https://graph.facebook.com/{version}/{page_id}"
        headers = {"Authorization": f"Bearer {self.settings.social_meta_access_token}"}
        async with self._client() as client:
            try:
                page_response, posts_response = await asyncio.gather(
                    client.get(
                        base_url,
                        params={"fields": "name,fan_count,followers_count"},
                        headers=headers,
                    ),
                    client.get(
                        f"{base_url}/posts",
                        params={
                            "fields": (
                                "created_time,shares,"
                                "comments.limit(0).summary(true),"
                                "reactions.limit(0).summary(true)"
                            ),
                            "since": since,
                            "until": until,
                            "limit": "100",
                        },
                        headers=headers,
                    ),
                )
                page_response.raise_for_status()
                posts_response.raise_for_status()
            except httpx.HTTPError as exc:
                raise MarketingSourceError(f"Meta Page aggregate read failed: {exc}") from exc

        try:
            page_payload = page_response.json()
            posts_payload = posts_response.json()
        except ValueError as exc:
            raise MarketingSourceError("Meta Page returned invalid JSON") from exc
        if not isinstance(page_payload, dict) or not isinstance(posts_payload, dict):
            raise MarketingSourceError("Meta Page returned a non-object response")

        posts = [item for item in posts_payload.get("data") or [] if isinstance(item, dict)]

        def summary_count(item: dict[str, Any], name: str) -> int | float:
            edge = item.get(name)
            summary = edge.get("summary") if isinstance(edge, dict) else None
            return _number(summary.get("total_count")) if isinstance(summary, dict) else 0

        reactions = _number(sum(float(summary_count(item, "reactions")) for item in posts))
        comments = _number(sum(float(summary_count(item, "comments")) for item in posts))
        shares = _number(
            sum(
                float(_number((item.get("shares") or {}).get("count")))
                for item in posts
                if isinstance(item.get("shares") or {}, dict)
            )
        )
        return {
            "source": "Meta Page aggregate read-only",
            "period_start": since,
            "period_end": until,
            "metrics": {
                "posts": len(posts),
                "reactions": reactions,
                "comments": comments,
                "shares": shares,
                "engagements": _number(float(reactions) + float(comments) + float(shares)),
                "followers": _number(page_payload.get("followers_count")),
                "fans": _number(page_payload.get("fan_count")),
            },
            "page_name": str(page_payload.get("name") or "")[:200],
            "metric_coverage": [
                "posts",
                "reactions",
                "comments",
                "shares",
                "engagements",
                "followers",
                "fans",
            ],
            "coverage_complete": not bool((posts_payload.get("paging") or {}).get("next")),
            "observed_at": datetime.now(timezone.utc).isoformat(),
        }
