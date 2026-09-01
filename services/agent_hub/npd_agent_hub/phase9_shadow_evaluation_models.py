from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from .attribution_models import assert_no_raw_pii, assert_pseudonymous_reference
from .journey_models import JourneyState
from .next_best_action_models import RecommendationPriority, RecommendedAction


PHASE9_SHADOW_EVAL_VERSION = "phase-9a-shadow-eval-v1"


class Phase9ShadowEvaluationRequest(BaseModel):
    subject_refs: list[str] = Field(min_length=1, max_length=200)
    as_of: datetime

    @field_validator("subject_refs")
    @classmethod
    def validate_subject_refs(cls, values: list[str]) -> list[str]:
        for value in values:
            kind, separator, identifier = value.partition(":")
            if separator != ":" or kind not in {"lead", "opportunity"} or not identifier:
                raise ValueError("subject_refs must use lead:<id> or opportunity:<id>")
            assert_pseudonymous_reference(identifier)
        return values

    @field_validator("as_of")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        return value


class Phase9ReviewAggregate(BaseModel):
    total_reviews: int = Field(ge=0)
    relevant: int = Field(ge=0)
    not_relevant: int = Field(ge=0)
    needs_more_context: int = Field(ge=0)
    false_positive_rate: float | None = Field(default=None, ge=0, le=1)


class Phase9ShadowEvaluationReport(BaseModel):
    evaluation_version: str = PHASE9_SHADOW_EVAL_VERSION
    as_of: datetime
    requested_subject_count: int = Field(ge=1)
    unique_subject_count: int = Field(ge=1)
    duplicate_subject_count: int = Field(ge=0)
    evaluated_subject_count: int = Field(ge=0)
    failed_subject_count: int = Field(ge=0)
    failure_counts: dict[str, int] = Field(default_factory=dict)
    journey_state_counts: dict[JourneyState, int] = Field(default_factory=dict)
    score_band_counts: dict[str, int] = Field(default_factory=dict)
    average_lead_score: float | None = Field(default=None, ge=0, le=100)
    average_recommendation_confidence: float | None = Field(default=None, ge=0, le=1)
    recommendation_action_counts: dict[RecommendedAction, int] = Field(default_factory=dict)
    recommendation_priority_counts: dict[RecommendationPriority, int] = Field(default_factory=dict)
    missing_input_counts: dict[str, int] = Field(default_factory=dict)
    subjects_with_untrusted_evidence: int = Field(ge=0)
    review_aggregate: Phase9ReviewAggregate
    caveats: list[str] = Field(default_factory=list)
    aggregate_only: bool = True
    contains_subject_ids: bool = False
    persisted: bool = False
    shadow_mode: bool = True
    execution_enabled: bool = False
    external_writes_enabled: bool = False
    customer_contact_enabled: bool = False
    contains_raw_pii: bool = False

    @model_validator(mode="after")
    def validate_aggregate_and_safety(self) -> "Phase9ShadowEvaluationReport":
        if self.requested_subject_count != self.unique_subject_count + self.duplicate_subject_count:
            raise ValueError("requested subject count must equal unique plus duplicate count")
        if self.unique_subject_count != self.evaluated_subject_count + self.failed_subject_count:
            raise ValueError("unique subject count must equal evaluated plus failed count")
        if sum(self.failure_counts.values()) != self.failed_subject_count:
            raise ValueError("failure_counts must match failed_subject_count")
        if sum(self.journey_state_counts.values()) != self.evaluated_subject_count:
            raise ValueError("journey_state_counts must match evaluated_subject_count")
        if sum(self.score_band_counts.values()) != self.evaluated_subject_count:
            raise ValueError("score_band_counts must match evaluated_subject_count")
        if sum(self.recommendation_action_counts.values()) != self.evaluated_subject_count:
            raise ValueError("recommendation_action_counts must match evaluated_subject_count")
        if sum(self.recommendation_priority_counts.values()) != self.evaluated_subject_count:
            raise ValueError("recommendation_priority_counts must match evaluated_subject_count")
        if (
            not self.aggregate_only
            or self.contains_subject_ids
            or self.persisted
            or self.execution_enabled
            or self.external_writes_enabled
            or self.customer_contact_enabled
            or self.contains_raw_pii
        ):
            raise ValueError("Phase 9A shadow evaluation must remain aggregate-only and non-executing")
        assert_no_raw_pii(self.model_dump(mode="python"), path="phase9_shadow_evaluation")
        return self
