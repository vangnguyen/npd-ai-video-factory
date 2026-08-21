from __future__ import annotations

import re
from datetime import datetime, timezone
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
    mode: str = "plan_preview"
    experiment_count: int
    awaiting_approval: int
    approved_plans: int
    previewed: int
    source_quality_required: bool = True
    production_execution_enabled: bool = False

