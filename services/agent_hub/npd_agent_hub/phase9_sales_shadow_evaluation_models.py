from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field, model_validator

from .attribution_models import assert_no_raw_pii
from .journey_models import JourneyState
from .next_best_action_models import RecommendationPriority, RecommendedAction
from .phase9_shadow_evaluation_models import Phase9ReviewAggregate
from .sales_intelligence_models import SalesIntelligencePreviewRequest, SalesSLAStatus


PHASE9_SALES_SHADOW_EVAL_VERSION = "phase-9b-sales-shadow-eval-v2"


class Phase9SalesShadowEvaluationRequest(BaseModel):
    cases: list[SalesIntelligencePreviewRequest] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_comparable_cases(self) -> "Phase9SalesShadowEvaluationRequest":
        reference_as_of = self.cases[0].as_of.astimezone(timezone.utc)
        seen: dict[str, str] = {}
        for case in self.cases:
            if case.as_of.astimezone(timezone.utc) != reference_as_of:
                raise ValueError("all sales shadow-evaluation cases must use the same as_of timestamp")
            canonical = case.model_dump_json()
            previous = seen.get(case.subject_ref)
            if previous is not None and previous != canonical:
                raise ValueError("duplicate subject cases must be byte-identical")
            seen[case.subject_ref] = canonical
        assert_no_raw_pii(self.model_dump(mode="python"), path="phase9_sales_shadow_request")
        return self


class Phase9SalesShadowEvaluationReport(BaseModel):
    evaluation_version: str = PHASE9_SALES_SHADOW_EVAL_VERSION
    as_of: datetime
    requested_case_count: int = Field(ge=1)
    unique_subject_count: int = Field(ge=1)
    duplicate_case_count: int = Field(ge=0)
    evaluated_subject_count: int = Field(ge=0)
    failed_subject_count: int = Field(ge=0)
    failure_counts: dict[str, int] = Field(default_factory=dict)
    journey_state_counts: dict[JourneyState, int] = Field(default_factory=dict)
    first_response_sla_status_counts: dict[SalesSLAStatus, int] = Field(default_factory=dict)
    visit_booking_sla_status_counts: dict[SalesSLAStatus, int] = Field(default_factory=dict)
    completeness_verified_count: int = Field(ge=0)
    source_complete_count: int = Field(ge=0)
    verified_breach_subject_count: int = Field(ge=0)
    verified_late_subject_count: int = Field(ge=0)
    score_band_counts: dict[str, int] = Field(default_factory=dict)
    average_lead_score: float | None = Field(default=None, ge=0, le=100)
    average_recommendation_confidence: float | None = Field(default=None, ge=0, le=1)
    recommendation_action_counts: dict[RecommendedAction, int] = Field(default_factory=dict)
    recommendation_priority_counts: dict[RecommendationPriority, int] = Field(default_factory=dict)
    missing_input_counts: dict[str, int] = Field(default_factory=dict)
    subjects_with_untrusted_journey_evidence: int = Field(ge=0)
    cases_with_untrusted_sales_activity: int = Field(ge=0)
    reviewed_subject_count: int = Field(ge=0)
    review_aggregate: Phase9ReviewAggregate = Field(default_factory=Phase9ReviewAggregate)
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
    def validate_aggregate_and_safety(self) -> "Phase9SalesShadowEvaluationReport":
        if self.requested_case_count != self.unique_subject_count + self.duplicate_case_count:
            raise ValueError("requested case count must equal unique plus duplicate count")
        if self.unique_subject_count != self.evaluated_subject_count + self.failed_subject_count:
            raise ValueError("unique subject count must equal evaluated plus failed count")
        if sum(self.failure_counts.values()) != self.failed_subject_count:
            raise ValueError("failure_counts must match failed_subject_count")
        for counts, label in (
            (self.journey_state_counts, "journey_state_counts"),
            (self.first_response_sla_status_counts, "first_response_sla_status_counts"),
            (self.visit_booking_sla_status_counts, "visit_booking_sla_status_counts"),
            (self.score_band_counts, "score_band_counts"),
            (self.recommendation_action_counts, "recommendation_action_counts"),
            (self.recommendation_priority_counts, "recommendation_priority_counts"),
        ):
            if sum(counts.values()) != self.evaluated_subject_count:
                raise ValueError(f"{label} must match evaluated_subject_count")
        for count, label in (
            (self.completeness_verified_count, "completeness_verified_count"),
            (self.source_complete_count, "source_complete_count"),
            (self.verified_breach_subject_count, "verified_breach_subject_count"),
            (self.verified_late_subject_count, "verified_late_subject_count"),
            (self.subjects_with_untrusted_journey_evidence, "subjects_with_untrusted_journey_evidence"),
            (self.cases_with_untrusted_sales_activity, "cases_with_untrusted_sales_activity"),
            (self.reviewed_subject_count, "reviewed_subject_count"),
        ):
            if count > self.evaluated_subject_count:
                raise ValueError(f"{label} cannot exceed evaluated_subject_count")
        if self.source_complete_count > self.completeness_verified_count:
            raise ValueError("source_complete_count cannot exceed completeness_verified_count")
        if self.verified_breach_subject_count + self.verified_late_subject_count > self.completeness_verified_count:
            raise ValueError("verified SLA negative-signal counts cannot exceed completeness_verified_count")
        if self.review_aggregate.total_reviews < self.reviewed_subject_count:
            raise ValueError("review total cannot be lower than reviewed subject count")
        if (
            not self.aggregate_only
            or self.contains_subject_ids
            or self.persisted
            or self.execution_enabled
            or self.external_writes_enabled
            or self.customer_contact_enabled
            or self.contains_raw_pii
        ):
            raise ValueError("Phase 9B sales shadow evaluation must remain aggregate-only and non-executing")
        assert_no_raw_pii(self.model_dump(mode="python"), path="phase9_sales_shadow_report")
        return self
