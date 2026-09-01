from __future__ import annotations

from pydantic import BaseModel, ConfigDict, model_validator

from .attribution_models import assert_no_raw_pii
from .lead_scoring_models import ExplainableLeadScore
from .next_best_action_models import NextBestActionRecommendation
from .sales_intelligence_models import SalesIntelligenceSnapshot


class SalesAwareNextBestActionPreview(BaseModel):
    model_config = ConfigDict(frozen=True)

    sales_intelligence: SalesIntelligenceSnapshot
    lead_score: ExplainableLeadScore
    recommendation: NextBestActionRecommendation
    persisted: bool = False
    shadow_mode: bool = True
    execution_enabled: bool = False
    external_writes_enabled: bool = False
    customer_contact_enabled: bool = False
    contains_raw_pii: bool = False

    @model_validator(mode="after")
    def validate_preview_boundary(self) -> "SalesAwareNextBestActionPreview":
        if (
            self.persisted
            or self.execution_enabled
            or self.external_writes_enabled
            or self.customer_contact_enabled
            or self.contains_raw_pii
        ):
            raise ValueError(
                "SLA-aware NBA preview must remain non-persisting, recommendation-only and PII-free"
            )
        refs = {
            self.sales_intelligence.subject_ref,
            self.lead_score.subject_ref,
            self.recommendation.subject_ref,
        }
        if len(refs) != 1:
            raise ValueError("Sales Intelligence, Lead Score and NBA subjects must match")
        if not (
            self.sales_intelligence.as_of
            == self.lead_score.as_of
            == self.recommendation.as_of
        ):
            raise ValueError("Sales Intelligence, Lead Score and NBA as_of timestamps must match")
        if self.recommendation.recommendation_version != "phase-9b-nba-v2":
            raise ValueError("SLA-aware NBA preview requires Phase 9B recommendation v2")
        assert_no_raw_pii(self.model_dump(mode="python"), path="sales_aware_nba")
        return self
