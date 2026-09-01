from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .attribution_models import assert_no_raw_pii, assert_pseudonymous_reference
from .journey_models import JourneyState
from .next_best_action_models import RecommendedAction


RAW_CONTACT_PATTERN = re.compile(
    r"(?:[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|\+?\d[\d\s().-]{7,})"
)


class NBAReviewDisposition(str, Enum):
    RELEVANT = "relevant"
    NOT_RELEVANT = "not_relevant"
    NEEDS_MORE_CONTEXT = "needs_more_context"


class NBAReviewCreate(BaseModel):
    subject_ref: str = Field(min_length=3, max_length=120)
    disposition: NBAReviewDisposition
    note: str | None = Field(default=None, max_length=1000)
    as_of: datetime | None = None

    @field_validator("subject_ref")
    @classmethod
    def validate_subject_reference(cls, value: str) -> str:
        kind, separator, identifier = value.partition(":")
        if separator != ":" or kind not in {"lead", "opportunity"} or not identifier:
            raise ValueError("subject_ref must use lead:<id> or opportunity:<id>")
        assert_pseudonymous_reference(identifier)
        return value

    @field_validator("note")
    @classmethod
    def reject_raw_contact_in_note(cls, value: str | None) -> str | None:
        if value and RAW_CONTACT_PATTERN.search(value):
            raise ValueError("review note cannot contain raw contact data")
        return value


class NBAReviewRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    review_id: str = Field(
        default_factory=lambda: f"nbar_{uuid4().hex[:24]}",
        pattern=r"^nbar_[0-9a-f]{24}$",
    )
    subject_ref: str = Field(min_length=3, max_length=120)
    recommendation_version: str
    recommended_action: RecommendedAction
    recommendation_as_of: datetime
    journey_state: JourneyState
    lead_score: float = Field(ge=0, le=100)
    recommendation_confidence: float = Field(ge=0, le=1)
    evidence_refs: list[str] = Field(default_factory=list)
    disposition: NBAReviewDisposition
    false_positive: bool
    note: str | None = Field(default=None, max_length=1000)
    reviewer_role: str = Field(pattern=r"^(operator|owner)$")
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    shadow_mode: bool = True
    recommendation_executed: bool = False
    execution_enabled: bool = False
    external_writes_enabled: bool = False
    customer_contact_enabled: bool = False
    contains_raw_pii: bool = False

    @model_validator(mode="after")
    def validate_shadow_review(self) -> "NBAReviewRecord":
        if self.false_positive != (self.disposition == NBAReviewDisposition.NOT_RELEVANT):
            raise ValueError("false_positive must match not_relevant disposition")
        if (
            self.recommendation_executed
            or self.execution_enabled
            or self.external_writes_enabled
            or self.customer_contact_enabled
            or self.contains_raw_pii
        ):
            raise ValueError("NBA shadow review cannot execute or contact a customer")
        if self.note and RAW_CONTACT_PATTERN.search(self.note):
            raise ValueError("review note cannot contain raw contact data")
        assert_no_raw_pii(self.model_dump(mode="python"), path="nba_review")
        return self


class NBAReviewSummary(BaseModel):
    total_reviews: int = Field(ge=0)
    relevant: int = Field(ge=0)
    not_relevant: int = Field(ge=0)
    needs_more_context: int = Field(ge=0)
    false_positive_rate: float | None = Field(default=None, ge=0, le=1)
    latest_reviewed_at: datetime | None = None
    shadow_mode: bool = True
    execution_enabled: bool = False
    customer_contact_enabled: bool = False
