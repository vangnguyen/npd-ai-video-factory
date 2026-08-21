from __future__ import annotations

import re
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from .campaign_models import CAMPAIGN_ID_PATTERN, assert_no_secrets


EXPERIMENT_ID_PATTERN = re.compile(r"^EXP-[A-Z0-9]{2,12}-\d{6}-\d{3}$")
RECONCILIATION_ID_PATTERN = re.compile(r"^rec_[0-9a-f]{20}$")


class ExperimentType(str, Enum):
    CREATIVE = "creative"
    AUDIENCE = "audience"
    LANDING_PAGE = "landing_page"
    OFFER = "offer"
    MESSAGING = "messaging"


class ExperimentStatus(str, Enum):
    PLANNED = "planned"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    PREVIEWED = "previewed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class MetricDirection(str, Enum):
    INCREASE = "increase"
    DECREASE = "decrease"


class ObservationSource(str, Enum):
    GA4 = "ga4"
    META_ADS = "meta_ads"
    VERIFIED_IMPORT = "verified_import"


class ObservationState(str, Enum):
    VERIFIED_READ_ONLY = "verified_read_only"
    PARTIAL = "partial"


class ObservationQualityState(str, Enum):
    PENDING_OWNER = "pending_owner"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class RecommendationAction(str, Enum):
    INSUFFICIENT_DATA = "insufficient_data"
    CONTINUE = "continue"
    WINNER_CANDIDATE = "winner_candidate"
    STOP_AND_REVIEW = "stop_and_review"
    MANUAL_REVIEW = "manual_review"


class ExperimentMetric(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    unit: str = Field(min_length=1, max_length=40)
    direction: MetricDirection = MetricDirection.INCREASE
    source: str = Field(min_length=2, max_length=120)


class ExperimentVariant(BaseModel):
    variant_id: str = Field(pattern=r"^VAR-[A-Z0-9]{1,12}$")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=3, max_length=1000)
    allocation_percent: int = Field(ge=1, le=100)
    asset_ref: str | None = Field(default=None, max_length=300)


class ExperimentGuardrail(BaseModel):
    metric: str = Field(min_length=2, max_length=100)
    operator: str = Field(pattern=r"^(<=|>=|<|>)$")
    threshold: float
    unit: str = Field(min_length=1, max_length=40)
    action: str = Field(default="stop_and_review", pattern=r"^stop_and_review$")


class ExperimentStopCondition(BaseModel):
    condition: str = Field(min_length=3, max_length=500)
    reason: str = Field(min_length=3, max_length=500)
    automatic_execution: bool = False


class ExperimentCreate(BaseModel):
    campaign_id: str = Field(pattern=CAMPAIGN_ID_PATTERN.pattern)
    attribution_reconciliation_id: str = Field(pattern=RECONCILIATION_ID_PATTERN.pattern)
    name: str = Field(min_length=3, max_length=200)
    experiment_type: ExperimentType
    hypothesis: str = Field(min_length=10, max_length=2000)
    primary_metric: ExperimentMetric
    baseline_value: float = Field(ge=0)
    target_lift_percent: float = Field(gt=0, le=1000)
    variants: list[ExperimentVariant] = Field(min_length=2, max_length=10)
    guardrails: list[ExperimentGuardrail] = Field(min_length=1, max_length=20)
    stop_conditions: list[ExperimentStopCondition] = Field(min_length=1, max_length=20)
    evaluation_window_days: int = Field(ge=1, le=90)
    owner: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_plan(self) -> "ExperimentCreate":
        variant_ids = [item.variant_id for item in self.variants]
        if len(set(variant_ids)) != len(variant_ids):
            raise ValueError("variant_id values must be unique")
        if sum(item.allocation_percent for item in self.variants) != 100:
            raise ValueError("variant allocation_percent values must sum to 100")
        if any(item.automatic_execution for item in self.stop_conditions):
            raise ValueError("Phase 8 stop conditions cannot execute automatically")
        assert_no_secrets(self.model_dump(mode="python"), path="experiment")
        return self


class ExperimentDraftUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=200)
    hypothesis: str | None = Field(default=None, min_length=10, max_length=2000)
    primary_metric: ExperimentMetric | None = None
    baseline_value: float | None = Field(default=None, ge=0)
    target_lift_percent: float | None = Field(default=None, gt=0, le=1000)
    variants: list[ExperimentVariant] | None = Field(default=None, min_length=2, max_length=10)
    guardrails: list[ExperimentGuardrail] | None = Field(default=None, min_length=1, max_length=20)
    stop_conditions: list[ExperimentStopCondition] | None = Field(default=None, min_length=1, max_length=20)
    evaluation_window_days: int | None = Field(default=None, ge=1, le=90)

    @model_validator(mode="after")
    def validate_update(self) -> "ExperimentDraftUpdate":
        payload = self.model_dump(exclude_none=True, mode="python")
        variants = self.variants
        if variants is not None:
            if len({item.variant_id for item in variants}) != len(variants):
                raise ValueError("variant_id values must be unique")
            if sum(item.allocation_percent for item in variants) != 100:
                raise ValueError("variant allocation_percent values must sum to 100")
        if self.stop_conditions and any(item.automatic_execution for item in self.stop_conditions):
            raise ValueError("Phase 8 stop conditions cannot execute automatically")
        assert_no_secrets(payload, path="experiment_update")
        return self


class ExperimentApprovalRequest(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class ExperimentApprovalDecision(BaseModel):
    approved: bool
    note: str | None = Field(default=None, max_length=1000)


class ExperimentPreview(BaseModel):
    experiment_id: str = Field(pattern=EXPERIMENT_ID_PATTERN.pattern)
    mode: str = "plan_preview"
    hypothesis: str
    primary_metric: ExperimentMetric
    baseline_value: float
    target_value: float
    variants: list[ExperimentVariant]
    guardrails: list[ExperimentGuardrail]
    stop_conditions: list[ExperimentStopCondition]
    evaluation_window_days: int
    source_snapshot_state: str = "quality_accepted"
    external_writes_enabled: bool = False
    previewed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class VariantObservation(BaseModel):
    variant_id: str = Field(pattern=r"^VAR-[A-Z0-9]{1,12}$")
    sample_size: int = Field(ge=0)
    conversions: int | None = Field(default=None, ge=0)
    metric_value: float | None = Field(default=None, ge=0)
    guardrail_values: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_measurement(self) -> "VariantObservation":
        if self.conversions is not None and self.conversions > self.sample_size:
            raise ValueError("conversions cannot exceed sample_size")
        if self.conversions is None and self.metric_value is None:
            raise ValueError("conversions or metric_value is required")
        assert_no_secrets(self.model_dump(mode="python"), path="variant_observation")
        return self


class ExperimentObservationCreate(BaseModel):
    source_system: ObservationSource
    source_state: ObservationState
    source_snapshot_id: str = Field(min_length=3, max_length=200)
    window_start: datetime
    window_end: datetime
    collected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    variants: list[VariantObservation] = Field(min_length=1, max_length=10)
    note: str | None = Field(default=None, max_length=1000)
    contains_raw_pii: bool = False
    external_writes_enabled: bool = False

    @model_validator(mode="after")
    def validate_observation(self) -> "ExperimentObservationCreate":
        if self.window_end <= self.window_start:
            raise ValueError("window_end must be after window_start")
        if self.collected_at < self.window_end:
            raise ValueError("collected_at cannot be before window_end")
        if len({item.variant_id for item in self.variants}) != len(self.variants):
            raise ValueError("observed variant_id values must be unique")
        if self.contains_raw_pii:
            raise ValueError("experiment observations cannot contain raw PII")
        if self.external_writes_enabled:
            raise ValueError("experiment observations must remain read-only")
        assert_no_secrets(self.model_dump(mode="python"), path="experiment_observation")
        return self


class ExperimentObservation(ExperimentObservationCreate):
    observation_id: str = Field(default_factory=lambda: f"eobs_{uuid4().hex[:20]}")
    experiment_id: str = Field(pattern=EXPERIMENT_ID_PATTERN.pattern)
    ingested_by: str
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    quality_state: ObservationQualityState = ObservationQualityState.PENDING_OWNER
    quality_decided_by: str | None = None
    quality_decided_at: datetime | None = None
    quality_note: str | None = Field(default=None, max_length=1000)


class ExperimentObservationQualityDecision(BaseModel):
    accepted: bool
    note: str = Field(min_length=3, max_length=1000)


class ExperimentSourceReadRequest(BaseModel):
    source_system: ObservationSource
    window_start: date
    window_end: date

    @model_validator(mode="after")
    def validate_window(self) -> "ExperimentSourceReadRequest":
        if self.source_system == ObservationSource.VERIFIED_IMPORT:
            raise ValueError("verified_import cannot be read from a live adapter")
        if self.window_end < self.window_start:
            raise ValueError("window_end must not be before window_start")
        if self.window_end > date.today():
            raise ValueError("window_end cannot be in the future")
        if (self.window_end - self.window_start).days > 90:
            raise ValueError("direct source-read window cannot exceed 90 days")
        return self


class ExperimentTrackingValidation(BaseModel):
    experiment_id: str = Field(pattern=EXPERIMENT_ID_PATTERN.pattern)
    campaign_id: str = Field(pattern=CAMPAIGN_ID_PATTERN.pattern)
    source_system: ObservationSource
    state: str = Field(pattern=r"^(ready|partial|not_configured)$")
    issues: list[str] = Field(default_factory=list)
    campaign_key: str | None = None
    variant_keys: dict[str, str] = Field(default_factory=dict)
    tracked_urls: dict[str, str] = Field(default_factory=dict)
    read_only: bool = True


class ExperimentMetaTrackingMappingUpdate(BaseModel):
    meta_ads_campaign_id: str = Field(pattern=r"^\d+$", max_length=40)
    variant_meta_ad_ids: dict[str, str] = Field(min_length=2, max_length=10)
    note: str = Field(min_length=5, max_length=1000)

    @model_validator(mode="after")
    def validate_mapping(self) -> "ExperimentMetaTrackingMappingUpdate":
        if any(
            not re.fullmatch(r"VAR-[A-Z0-9]{1,12}", key)
            for key in self.variant_meta_ad_ids
        ):
            raise ValueError("variant mapping keys must be canonical VAR-* IDs")
        if any(
            not re.fullmatch(r"\d+", value)
            for value in self.variant_meta_ad_ids.values()
        ):
            raise ValueError("Meta ad IDs must contain digits only")
        if len(set(self.variant_meta_ad_ids.values())) != len(
            self.variant_meta_ad_ids
        ):
            raise ValueError("each experiment variant must map to a distinct Meta ad ID")
        assert_no_secrets(
            self.model_dump(mode="python"), path="experiment_tracking_mapping"
        )
        return self


class ExperimentSourceReadResult(BaseModel):
    experiment_id: str = Field(pattern=EXPERIMENT_ID_PATTERN.pattern)
    source_system: ObservationSource
    state: str = Field(pattern=r"^(observed|partial|no_data|not_configured)$")
    tracking: ExperimentTrackingValidation
    observation: ExperimentObservation | None = None
    message: str
    external_writes_enabled: bool = False


class ExperimentEvaluationRequest(BaseModel):
    observation_id: str | None = Field(default=None, pattern=r"^eobs_[0-9a-f]{20}$")
    min_sample_per_variant: int = Field(default=100, ge=20, le=1_000_000)
    max_source_age_hours: int = Field(default=72, ge=1, le=24 * 90)
    confidence_level: float = Field(default=0.95, ge=0.8, le=0.99)


class ExperimentEvaluation(BaseModel):
    evaluation_id: str = Field(default_factory=lambda: f"eeval_{uuid4().hex[:20]}")
    experiment_id: str = Field(pattern=EXPERIMENT_ID_PATTERN.pattern)
    observation_id: str = Field(pattern=r"^eobs_[0-9a-f]{20}$")
    recommendation: RecommendationAction
    sample_sufficient: bool
    source_fresh: bool
    source_state: ObservationState
    control_variant_id: str
    compared_variant_id: str | None = None
    winner_candidate_variant_id: str | None = None
    control_value: float | None = None
    compared_value: float | None = None
    observed_lift_percent: float | None = None
    p_value: float | None = Field(default=None, ge=0, le=1)
    confidence_level: float
    guardrail_breaches: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    evaluated_by: str
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    external_writes_enabled: bool = False
    automatic_decision_enabled: bool = False


class Experiment(BaseModel):
    experiment_id: str = Field(pattern=EXPERIMENT_ID_PATTERN.pattern)
    campaign_id: str = Field(pattern=CAMPAIGN_ID_PATTERN.pattern)
    attribution_reconciliation_id: str = Field(pattern=RECONCILIATION_ID_PATTERN.pattern)
    name: str
    experiment_type: ExperimentType
    hypothesis: str
    primary_metric: ExperimentMetric
    baseline_value: float
    target_lift_percent: float
    variants: list[ExperimentVariant]
    guardrails: list[ExperimentGuardrail]
    stop_conditions: list[ExperimentStopCondition]
    evaluation_window_days: int
    owner: str
    status: ExperimentStatus = ExperimentStatus.PLANNED
    approval_note: str | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    last_preview: ExperimentPreview | None = None
    observations: list[ExperimentObservation] = Field(default_factory=list, max_length=100)
    last_evaluation: ExperimentEvaluation | None = None
    execution_enabled: bool = False
    external_writes_enabled: bool = False
    created_by: str
    updated_by: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def validate_safety(self) -> "Experiment":
        if self.execution_enabled or self.external_writes_enabled:
            raise ValueError("Phase 8 experiment execution must remain disabled")
        assert_no_secrets(self.model_dump(mode="python"), path="experiment")
        return self


class ExperimentAuditEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: f"eaud_{uuid4().hex[:20]}")
    experiment_id: str = Field(pattern=EXPERIMENT_ID_PATTERN.pattern)
    event_type: str
    actor: str
    detail: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def validate_metadata(self) -> "ExperimentAuditEvent":
        assert_no_secrets(self.metadata, path="experiment_audit.metadata")
        return self


class ExperimentOSStatus(BaseModel):
    mode: str = "plan_preview_direct_read_owner_gate"
    experiment_count: int
    awaiting_approval: int
    approved_plans: int
    previewed: int
    observation_count: int = 0
    observations_pending_owner: int = 0
    observations_quality_accepted: int = 0
    ga4_tracking_ready: int = 0
    meta_tracking_ready: int = 0
    evaluated: int = 0
    awaiting_observation: int = 0
    observation_sources: dict[str, str] = Field(default_factory=dict)
    source_quality_required: bool = True
    production_execution_enabled: bool = False
    automatic_decision_enabled: bool = False
