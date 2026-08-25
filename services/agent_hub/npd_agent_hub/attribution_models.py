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
WRITE_FLAG_PATTERN = re.compile(
    r"(write|publish|send|execute|execution|mutate|mutation)", re.IGNORECASE
)


def assert_no_raw_pii(value: Any, *, path: str = "attribution") -> None:
    assert_no_secrets(value, path=path)
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = re.sub(
                r"(?<=[a-z0-9])(?=[A-Z])", "_", str(key)
            )
            if PII_KEY_PATTERN.search(normalized_key):
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


def assert_no_enabled_write_flags(value: Any, *, path: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if WRITE_FLAG_PATTERN.search(str(key)) and item not in (False, None, "disabled"):
                raise ValueError(f"Attribution source cannot enable writes: {path}.{key}")
            assert_no_enabled_write_flags(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            assert_no_enabled_write_flags(item, path=f"{path}[{index}]")


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


class IdentitySource(str, Enum):
    META_ADS = "meta_ads"
    GA4 = "ga4"
    ESPOCRM = "espocrm"
    UTM = "utm"


class IdentityResolutionState(str, Enum):
    RESOLVED = "resolved"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"
    DUPLICATE = "duplicate"


class FreshnessState(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    NO_DATA = "no_data"


class IntakeIssueStatus(str, Enum):
    PENDING = "pending"
    RESOLVED = "resolved"


class CampaignIdentityMappingCreate(BaseModel):
    source_system: IdentitySource
    source_account_id: str | None = Field(default=None, max_length=200)
    source_campaign_id: str | None = Field(default=None, max_length=200)
    source_adset_id: str | None = Field(default=None, max_length=200)
    source_ad_group_id: str | None = Field(default=None, max_length=200)
    source_ad_id: str | None = Field(default=None, max_length=200)
    utm_campaign: str | None = Field(default=None, max_length=200)
    campaign_id: str = Field(pattern=CAMPAIGN_ID_PATTERN.pattern)
    note: str = Field(min_length=5, max_length=1000)

    @model_validator(mode="after")
    def validate_external_identity(self) -> "CampaignIdentityMappingCreate":
        if not any(
            (
                self.source_campaign_id,
                self.source_adset_id,
                self.source_ad_group_id,
                self.source_ad_id,
                self.utm_campaign,
            )
        ):
            raise ValueError("identity mapping requires an external ID or utm_campaign")
        if self.source_system == IdentitySource.META_ADS and not self.source_campaign_id:
            raise ValueError("Meta Ads identity mapping requires source_campaign_id")
        assert_no_raw_pii(self.model_dump(mode="python"), path="identity_mapping")
        return self


class CampaignIdentityMapping(BaseModel):
    model_config = ConfigDict(frozen=True)

    mapping_id: str = Field(
        default_factory=lambda: f"cim_{uuid4().hex[:20]}",
        pattern=r"^cim_[0-9a-f]{20}$",
    )
    source_system: IdentitySource
    source_account_id: str | None = None
    source_campaign_id: str | None = None
    source_adset_id: str | None = None
    source_ad_group_id: str | None = None
    source_ad_id: str | None = None
    utm_campaign: str | None = None
    campaign_id: str = Field(pattern=CAMPAIGN_ID_PATTERN.pattern)
    project: str = Field(min_length=2, max_length=200)
    verification: str = "owner_verified"
    verified_by: str
    note: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    external_writes_enabled: bool = False

    @model_validator(mode="after")
    def validate_safe_mapping(self) -> "CampaignIdentityMapping":
        assert_no_raw_pii(self.model_dump(mode="python"), path="identity_mapping")
        if self.external_writes_enabled:
            raise ValueError("identity registry cannot enable external writes")
        return self


class SourceTouchpointEvent(BaseModel):
    source_event_id: str = Field(min_length=2, max_length=200)
    source_system: IdentitySource
    event_type: TouchpointType
    occurred_at: datetime
    channel: str = Field(min_length=2, max_length=80)
    canonical_campaign_id: str | None = Field(
        default=None, pattern=CAMPAIGN_ID_PATTERN.pattern
    )
    source_account_id: str | None = Field(default=None, max_length=200)
    source_campaign_id: str | None = Field(default=None, max_length=200)
    source_adset_id: str | None = Field(default=None, max_length=200)
    source_ad_group_id: str | None = Field(default=None, max_length=200)
    source_ad_id: str | None = Field(default=None, max_length=200)
    lead_id: str | None = Field(default=None, min_length=1, max_length=100)
    opportunity_id: str | None = Field(default=None, min_length=1, max_length=100)
    utm_source: str | None = Field(default=None, max_length=200)
    utm_medium: str | None = Field(default=None, max_length=200)
    utm_campaign: str | None = Field(default=None, max_length=200)
    utm_content: str | None = Field(default=None, max_length=200)
    landing_page: str | None = Field(default=None, max_length=1000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    _pseudonymous_ids = field_validator(
        "source_event_id", "lead_id", "opportunity_id"
    )(assert_pseudonymous_reference)

    @model_validator(mode="after")
    def validate_source_event(self) -> "SourceTouchpointEvent":
        if not self.lead_id and not self.opportunity_id:
            raise ValueError("source touchpoint requires lead_id or opportunity_id")
        if not any(
            (
                self.canonical_campaign_id,
                self.source_campaign_id,
                self.source_ad_id,
                self.utm_campaign,
            )
        ):
            raise ValueError("source touchpoint requires a canonical or external campaign identity")
        assert_no_raw_pii(self.metadata, path="source_touchpoint.metadata")
        assert_no_enabled_write_flags(self.metadata, path="source_touchpoint.metadata")
        return self


class SourceTouchpointIngestRequest(BaseModel):
    events: list[SourceTouchpointEvent] = Field(min_length=1, max_length=500)
    stale_after_hours: int = Field(default=72, ge=1, le=24 * 365)


class TouchpointIngestIssue(BaseModel):
    source_event_id: str
    state: IdentityResolutionState
    detail: str
    candidate_campaign_ids: list[str] = Field(default_factory=list)


class AttributionIntakeIssue(BaseModel):
    """Persisted, privacy-safe exception raised by source touchpoint ingestion."""

    issue_id: str = Field(pattern=r"^ati_[0-9a-f]{24}$")
    source_event: SourceTouchpointEvent
    state: IdentityResolutionState
    status: IntakeIssueStatus = IntakeIssueStatus.PENDING
    detail: str
    candidate_campaign_ids: list[str] = Field(default_factory=list)
    occurrence_count: int = Field(default=1, ge=1)
    first_seen_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_campaign_id: str | None = Field(
        default=None, pattern=CAMPAIGN_ID_PATTERN.pattern
    )
    resolution_methods: list[str] = Field(default_factory=list)
    mapping_ids: list[str] = Field(default_factory=list)
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    replay_snapshot_id: str | None = None
    shadow_mode: bool = True
    external_writes_enabled: bool = False

    @model_validator(mode="after")
    def validate_intake_issue(self) -> "AttributionIntakeIssue":
        if self.state not in {
            IdentityResolutionState.UNKNOWN,
            IdentityResolutionState.CONFLICT,
        }:
            raise ValueError("intake issue must represent unknown or conflict state")
        if self.external_writes_enabled:
            raise ValueError("intake issue cannot enable external writes")
        assert_no_raw_pii(self.model_dump(mode="python"), path="intake_issue")
        return self


class AttributionIntakePreview(BaseModel):
    issue_id: str
    state: str
    candidate_campaign_ids: list[str] = Field(default_factory=list)
    resolution_methods: list[str] = Field(default_factory=list)
    mapping_ids: list[str] = Field(default_factory=list)
    ledger_event_id: str
    would_insert: bool = False
    detail: str
    shadow_mode: bool = True
    external_writes_enabled: bool = False


class AttributionDataQualitySnapshot(BaseModel):
    snapshot_id: str = Field(
        default_factory=lambda: f"adq_{uuid4().hex[:20]}",
        pattern=r"^adq_[0-9a-f]{20}$",
    )
    received: int
    resolved: int
    inserted: int
    duplicates: int
    unknown: int
    conflicts: int
    coverage_rate: float
    mismatch_rate: float
    freshness_state: FreshnessState
    latest_occurred_at: datetime | None = None
    freshness_age_hours: float | None = None
    issues: list[TouchpointIngestIssue] = Field(default_factory=list)
    created_by: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    shadow_mode: bool = True
    external_writes_enabled: bool = False


class AttributionIdentityStatus(BaseModel):
    mode: str = "verified_identity_read_only"
    mapping_count: int
    touchpoint_count: int
    pending_intake_issues: int = 0
    latest_snapshot: AttributionDataQualitySnapshot | None = None
    production_write_enabled: bool = False


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
        assert_no_raw_pii(self.metadata, path="opportunity.metadata")
        return self


class TouchpointBackfillRequest(BaseModel):
    touchpoints: list[TouchpointEvent] = Field(min_length=1, max_length=500)


class ReconciliationRequest(BaseModel):
    observations: list[OpportunityObservation] = Field(min_length=1, max_length=500)


class OpportunitySourceSnapshot(BaseModel):
    source: str = "EspoCRM Opportunity read-only"
    status: str
    projection: list[str]
    campaign_field: str = "not_configured"
    reported_total: int
    records_read: int
    observations: list[OpportunityObservation] = Field(default_factory=list)
    contains_raw_pii: bool = False
    external_writes_enabled: bool = False


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
