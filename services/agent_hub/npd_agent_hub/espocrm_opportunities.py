from __future__ import annotations

import re
from datetime import date, datetime, time, timezone
from typing import Any

import httpx

from .attribution_models import (
    OpportunityObservation,
    OpportunitySourceSnapshot,
    OpportunityStatus,
)
from .campaign_models import CAMPAIGN_ID_PATTERN
from .config import HubSettings, settings as default_settings
from .currency import normalize_vnd_currency


ESPO_OPPORTUNITY_SAFE_FIELDS = (
    "id",
    "stage",
    "amount",
    "amountCurrency",
    "closeDate",
    "leadSource",
    "campaignId",
    "createdAt",
    "modifiedAt",
)
ESPO_FIELD_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,79}$")


class EspoOpportunityError(RuntimeError):
    pass


class EspoOpportunityNotConfigured(EspoOpportunityError):
    pass


class EspoOpportunityReader:
    """Read a narrow, PII-free Opportunity projection from EspoCRM."""

    def __init__(
        self,
        settings: HubSettings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings or default_settings
        self.transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self.settings.request_timeout_seconds,
            transport=self.transport,
        )

    def _projection(self) -> tuple[str, ...]:
        extra = self.settings.espocrm_opportunity_campaign_field
        if extra and not ESPO_FIELD_PATTERN.fullmatch(extra):
            raise EspoOpportunityError(
                "ESPOCRM_OPPORTUNITY_CAMPAIGN_FIELD is not a valid EspoCRM field name"
            )
        return tuple(dict.fromkeys((*ESPO_OPPORTUNITY_SAFE_FIELDS, *((extra,) if extra else ()))))

    @staticmethod
    def _datetime(value: object, *, date_only: bool = False) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        raw = value.strip()
        if date_only:
            try:
                return datetime.combine(date.fromisoformat(raw), time.min, tzinfo=timezone.utc)
            except ValueError:
                return None
        normalized = raw.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _status(stage: object) -> OpportunityStatus:
        normalized = str(stage or "").strip().casefold()
        if normalized == "closed won":
            return OpportunityStatus.WON
        if normalized == "closed lost":
            return OpportunityStatus.LOST
        return OpportunityStatus.OPEN

    @staticmethod
    def _amount(value: object) -> float:
        try:
            return max(0.0, float(value or 0))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _currency(value: object) -> str:
        try:
            return normalize_vnd_currency(value)
        except ValueError as exc:
            raise EspoOpportunityError(
                "EspoCRM Opportunity currency is unsupported; only VND is accepted"
            ) from exc

    def _observation(self, record: dict[str, Any]) -> OpportunityObservation | None:
        opportunity_id = str(record.get("id") or "").strip()
        stage = str(record.get("stage") or "Unknown")[:120]
        if not opportunity_id:
            return None
        status = self._status(stage)
        close_date = self._datetime(record.get("closeDate"), date_only=True)
        observed_at = (
            self._datetime(record.get("modifiedAt"))
            or self._datetime(record.get("createdAt"))
            or datetime.now(timezone.utc)
        )
        campaign_hint = None
        campaign_field = self.settings.espocrm_opportunity_campaign_field
        if campaign_field:
            candidate = str(record.get(campaign_field) or "").strip()
            if CAMPAIGN_ID_PATTERN.fullmatch(candidate):
                campaign_hint = candidate
        metadata: dict[str, object] = {}
        if record.get("leadSource"):
            metadata["lead_source"] = str(record["leadSource"])[:120]
        if record.get("campaignId"):
            metadata["source_campaign_id"] = str(record["campaignId"])[:100]
        return OpportunityObservation(
            opportunity_id=opportunity_id,
            campaign_id_hint=campaign_hint,
            stage=stage,
            status=status,
            amount=self._amount(record.get("amount")),
            currency=self._currency(record.get("amountCurrency")),
            observed_at=observed_at,
            closed_at=close_date if status == OpportunityStatus.WON else None,
            source_system="EspoCRM Opportunity read-only",
            metadata=metadata,
        )

    async def read(self, *, limit: int = 200) -> OpportunitySourceSnapshot:
        if not self.settings.espocrm_url or not self.settings.espocrm_api_key:
            raise EspoOpportunityNotConfigured(
                "ESPOCRM_URL and ESPOCRM_API_KEY are required for Opportunity reads"
            )
        limit = max(1, min(int(limit), 500))
        projection = self._projection()
        headers = {"X-Api-Key": self.settings.espocrm_api_key}
        async with self._client() as client:
            try:
                response = await client.get(
                    f"{self.settings.espocrm_url}/api/v1/Opportunity",
                    params={
                        "maxSize": limit,
                        "orderBy": "modifiedAt",
                        "order": "desc",
                        "select": ",".join(projection),
                    },
                    headers=headers,
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise EspoOpportunityError(
                    f"EspoCRM Opportunity read failed: {exc}"
                ) from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise EspoOpportunityError(
                "EspoCRM Opportunity endpoint returned invalid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise EspoOpportunityError(
                "EspoCRM Opportunity endpoint returned a non-object response"
            )
        raw_records = payload.get("list")
        records = raw_records if isinstance(raw_records, list) else []
        observations = [
            observation
            for record in records
            if isinstance(record, dict)
            if (observation := self._observation(record)) is not None
        ]
        try:
            reported_total = max(0, int(payload.get("total", len(observations))))
        except (TypeError, ValueError):
            reported_total = len(observations)
        return OpportunitySourceSnapshot(
            status="available" if observations else "no_data",
            projection=list(projection),
            campaign_field=(
                self.settings.espocrm_opportunity_campaign_field or "not_configured"
            ),
            reported_total=reported_total,
            records_read=len(observations),
            observations=observations,
        )
