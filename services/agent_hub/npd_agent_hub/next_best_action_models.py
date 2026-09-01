from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .attribution_models import assert_no_raw_pii
from .journey_models import JourneyState


NBA_VERSION = "phase-9a-nba-v1"


class RecommendationPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RecommendationChannel(str, Enum):
    INTERNAL_REVIEW = "internal_review"
    SALES_TASK_REVIEW = "sales_task_review"


class RecommendedAction(str, Enum):
    COLLECT_MORE_EVIDENCE = "collect_more_evidence"
    REVIEW_SALES_FOLLOW_UP = "review_sales_follow_up"
    REVIEW_APPOINTMENT_PREPARATION = "review_appointment_preparation"
    REVIEW_POST_VISIT_FOLLOW_UP = "review_post_visit_follow_up"
    REVIEW_NEGOTIATION_NEXT_STEP = "review_negotiation_next_step"
    REVIEW_CUSTOMER_HANDOFF = "review_customer_handoff"
    REVIEW_CUSTOMER_CARE = "review_customer_care"
    REVIEW_LOST_REASON = "review_lost_reason"
    REVIEW_REENGAGEMENT = "review_reengagement"


class NextBestActionRecommendation(BaseModel):
    model_config = ConfigDict(frozen=True)

    subject_ref: str = Field(min_length=3, max_length=120)
    recommendation_version: str = NBA_VERSION
    recommended_action: RecommendedAction
    reason: str = Field(min_length=10, max_length=700)
    priority: RecommendationPriority
    sla_minutes: int = Field(ge=0, le=7 * 24 * 60)
    sla_scope: str = "internal_review_only"
    channel: RecommendationChannel
    campaign_id: str | None = Field(default=None, max_length=120)
    project: str | None = Field(default=None, max_length=200)
    journey_state: JourneyState
    lead_score: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    evidence_refs: list[str] = Field(default_factory=list)
    missing_context: list[str] = Field(default_factory=list)
    as_of: datetime
    shadow_mode: bool = True
    execution_enabled: bool = False
    external_writes_enabled: bool = False
    customer_contact_enabled: bool = False
    contains_raw_pii: bool = False

    @model_validator(mode="after")
    def validate_recommendation_only_boundary(self) -> "NextBestActionRecommendation":
        if (
            self.execution_enabled
            or self.external_writes_enabled
            or self.customer_contact_enabled
            or self.contains_raw_pii
        ):
            raise ValueError("Phase 9A Next Best Action must remain recommendation-only and PII-free")
        if self.sla_scope != "internal_review_only":
            raise ValueError("Phase 9A SLA can only describe internal review timing")
        assert_no_raw_pii(self.model_dump(mode="python"), path="next_best_action")
        return self
