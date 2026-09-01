from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .attribution_models import assert_no_raw_pii
from .journey_models import JourneyState


LEAD_SCORE_VERSION = "phase-9a-score-v1"


class ScoreFactorStatus(str, Enum):
    OBSERVED = "observed"
    MISSING = "missing"


class LeadScoreFactor(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=2, max_length=80)
    status: ScoreFactorStatus
    contribution: float | None = Field(default=None, ge=0)
    max_points: float = Field(gt=0)
    reason: str = Field(min_length=5, max_length=500)
    evidence_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_factor(self) -> "LeadScoreFactor":
        if self.status == ScoreFactorStatus.OBSERVED:
            if self.contribution is None:
                raise ValueError("observed score factor requires a contribution")
            if self.contribution > self.max_points:
                raise ValueError("score factor contribution cannot exceed max_points")
        elif self.contribution is not None:
            raise ValueError("missing score factor cannot carry a numeric contribution")
        assert_no_raw_pii(self.model_dump(mode="python"), path="lead_score_factor")
        return self


class ExplainableLeadScore(BaseModel):
    subject_ref: str = Field(min_length=3, max_length=120)
    methodology: str = "journey_momentum_v1"
    score_version: str = LEAD_SCORE_VERSION
    score: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    available_points: float = Field(gt=0)
    current_state: JourneyState
    as_of: datetime
    factors: list[LeadScoreFactor]
    missing_inputs: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    shadow_mode: bool = True
    execution_enabled: bool = False
    external_writes_enabled: bool = False
    contains_raw_pii: bool = False

    @model_validator(mode="after")
    def validate_explainability_and_safety(self) -> "ExplainableLeadScore":
        if self.execution_enabled or self.external_writes_enabled or self.contains_raw_pii:
            raise ValueError("Phase 9A lead score must remain read-only and PII-free")
        observed = [item for item in self.factors if item.status == ScoreFactorStatus.OBSERVED]
        calculated_available = sum(item.max_points for item in observed)
        calculated_raw = sum(item.contribution or 0 for item in observed)
        calculated_score = round(calculated_raw / calculated_available * 100, 2)
        if abs(self.available_points - calculated_available) > 1e-9:
            raise ValueError("available_points must equal observed factor capacity")
        if abs(self.score - calculated_score) > 1e-9:
            raise ValueError("score must be normalized only across observed factors")
        assert_no_raw_pii(self.model_dump(mode="python"), path="explainable_lead_score")
        return self
