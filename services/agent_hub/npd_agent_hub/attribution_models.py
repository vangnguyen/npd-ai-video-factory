from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .campaign_models import CAMPAIGN_ID_PATTERN, assert_no_secrets


PII_KEY_PATTERN = re.compile(
    r"(^|_)(email|phone|mobile|address|full_?name|first_?name|last_?name)(_|$)",
    re.IGNORECASE,
)


def assert_no_raw_pii(value: Any, *, path: str = "attribution") -> None:
    assert_no_secrets(value, path=path)
    if isinstance(value, dict):
        for key, item in value.items():
            if PII_KEY_PATTERN.search(str(key)):
                raise ValueError(f"Attribution object cannot store raw PII: {path}.{key}")
            assert_no_raw_pii(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            assert_no_raw_pii(item, path=f"{path}[{index}]")


def assert_pseudonymous_reference(value: str | None) -> str | None:
    if value is None:
        return None
    if "@" in value or re.fullmatch(r"\+?\d[\d\s().-]{7,}", value):
        raise ValueError("lead/opportunity references cannot contain raw contact data")
    return value


class TouchpointType(str, Enum):
    AD_CLICK = "ad_click"
    LANDING_VIEW = "landing_view"
    FORM_SUBMIT = "form_submit"
    LEAD_CREATED = "lead_created"
    OPPORTUNITY_CREATED = "opportunity_created"
    OPPORTUNITY_STAGE_CHANGED = "opportunity_stage_changed"
    SALE_CLOSED = "sale_closed"


class OpportunityStatus(str, Enum):
    OPEN = "open"
    WON = "won"
    LOST = "lost"


class AttributionModel(str, Enum):
    FIRST_TOUCH = "first_touch"
    LAST_TOUCH = "last_touch"
    LINEAR = "linear"


class TouchpointEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str = Field(
        default_factory=lambda: f"tpt_{uuid4().hex}",
        pattern=r"^tpt_[0-9a-f]{32}$",
    )
    campaign_id: str = Field(pattern=CAMPAIGN_ID_PATTERN.pattern)
    event_type: TouchpointType
    occurred_at: datetime
    source_system: str = Field(min_length=2, max_length=80)
    channel: str = Field(min_length=2, max_length=80)
    lead_id: str | None = Field(default=None, min_length=1, max_length=100)
    opportunity_id: str | None = Field(default=None, min_length=1, max_length=100)
    source_campaign_id: str | None = Field(default=None, max_length=200)
    source_adset_id: str | None = Field(default=None, max_length=200)
    source_ad_group_id: str | None = Field(default=None, max_length=200)
    source_ad_id: str | None = Field(default=None, max_length=200)
    utm_source: str | None = Field(default=None, max_length=200)
    utm_medium: str | None = Field(default=None, max_length=200)
    utm_campaign: str | None = Field(default=None, max_length=200)
    utm_content: str | None = Field(default=None, max_length=200)
    landing_page: str | None = Field(default=None, max_length=1000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    _pseudonymous_ids = field_validator("lead_id", "opportunity_id")(
        assert_pseudonymous_reference
    )

    @model_validator(mode="after")
    def validate_identity_and_payload(self) -> "TouchpointEvent":
        if not self.lead_id and not self.opportunity_id:
            raise ValueError("touchpoint requires lead_id or opportunity_id")
        assert_no_raw_pii(self.metadata, path="touchpoint.metadata")
        return self


class OpportunityObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    observation_id: str = Field(
        default_factory=lambda: f"rev_{uuid4().hex}",
        pattern=r"^rev_[0-9a-f]{32}$",
    )
    opportunity_id: str = Field(min_length=1, max_length=100)
    lead_id: str | None = Field(default=None, min_length=1, max_length=100)
    campaign_id_hint: str | None = Field(
        default=None, pattern=CAMPAIGN_ID_PATTERN.pattern
    )
    stage: str = Field(min_length=1, max_length=120)
    status: OpportunityStatus
    amount: float = Field(ge=0)
    currency: str = Field(default="VND", pattern=r"^[A-Z]{3}$")
    observed_at: datetime
    closed_at: datetime | None = None
    source_system: str = "EspoCRM"
    metadata: dict[str, Any] = Field(default_factory=dict)

    _pseudonymous_ids = field_validator("lead_id", "opportunity_id")(
        assert_pseudonymous_reference
    )

    @model_validator(mode="after")
    def validate_observation(self) -> "OpportunityObservation":
        if self.status == OpportunityStatus.WON and self.closed_at is None:
            raise ValueError("won opportunity requires closed_at")
        assert_no_raw_pii(self.metadata, path="opportunity.metadata")
        return self


class TouchpointBackfillRequest(BaseModel):
    touchpoints: list[TouchpointEvent] = Field(min_length=1, max_length=500)


class ReconciliationRequest(BaseModel):
    observations: list[OpportunityObservation] = Field(min_length=1, max_length=500)


class OpportunityMatch(BaseModel):
    opportunity_id: str
    campaign_ids: list[str] = Field(default_factory=list)
    touchpoint_event_ids: list[str] = Field(default_factory=list)
    match_method: str
    issues: list[str] = Field(default_factory=list)


class AttributionQuality(BaseModel):
    total_opportunities: int
    matched_opportunities: int
    unmatched_opportunities: int
    conflicting_opportunities: int
    won_opportunities: int
    won_revenue_covered: int
    match_rate: float
    conflict_rate: float
    won_revenue_coverage_rate: float
    eligible_for_acceptance: bool
    issues: list[str] = Field(default_factory=list)


class AttributionReconciliation(BaseModel):
    reconciliation_id: str = Field(
        default_factory=lambda: f"rec_{uuid4().hex[:20]}",
        pattern=r"^rec_[0-9a-f]{20}$",
    )
    ledger_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    observations: list[OpportunityObservation]
    matches: list[OpportunityMatch]
    quality: AttributionQuality
    state: str = "awaiting_quality_acceptance"
    accepted: bool = False
    accepted_by: str | None = None
    acceptance_note: str | None = None
    accepted_at: datetime | None = None
    shadow_mode: bool = True
    external_writes_enabled: bool = False
    created_by: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AttributionAcceptanceRequest(BaseModel):
    accepted: bool
    note: str | None = Field(default=None, max_length=1000)


class CampaignAttributionRow(BaseModel):
    campaign_id: str
    opportunity_credit: float
    attributed_pipeline: float
    attributed_revenue: float
    currency: str


class AttributionReport(BaseModel):
    reconciliation_id: str
    model: AttributionModel
    state: str
    shadow_mode: bool = True
    external_writes_enabled: bool = False
    attributed_opportunities: float | None = None
    attributed_pipeline: float | None = None
    attributed_revenue: float | None = None
    currency: str | None = None
    campaigns: list[CampaignAttributionRow] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)


class AttributionAuditEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: f"aaud_{uuid4().hex[:20]}")
    event_type: str
    actor: str
    reconciliation_id: str | None = None
    detail: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def validate_metadata(self) -> "AttributionAuditEvent":
        assert_no_raw_pii(self.metadata, path="attribution_audit.metadata")
        return self


class AttributionStatus(BaseModel):
    mode: str = "read_only_shadow"
    touchpoint_count: int
    reconciliation_count: int
    latest_reconciliation_id: str | None = None
    latest_state: str = "not_started"
    production_write_enabled: bool = False
