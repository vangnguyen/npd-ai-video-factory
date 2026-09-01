from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .attribution_models import assert_no_raw_pii
from .nba_review_models import NBAReviewDisposition, RAW_CONTACT_PATTERN
from .sales_intelligence_models import SalesIntelligencePreviewRequest


SALES_NBA_REVIEW_VERSION = "phase-9b-nba-v2"


class SalesNBAReviewCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    evaluation: SalesIntelligencePreviewRequest
    disposition: NBAReviewDisposition
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("note")
    @classmethod
    def reject_raw_contact_in_note(cls, value: str | None) -> str | None:
        if value and RAW_CONTACT_PATTERN.search(value):
            raise ValueError("review note cannot contain raw contact data")
        return value

    @model_validator(mode="after")
    def validate_review_request(self) -> "SalesNBAReviewCreate":
        assert_no_raw_pii(self.model_dump(mode="python"), path="sales_nba_review_request")
        return self
