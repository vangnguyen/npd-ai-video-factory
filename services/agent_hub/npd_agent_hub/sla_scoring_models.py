from __future__ import annotations

from pydantic import BaseModel, ConfigDict, model_validator

from .attribution_models import assert_no_raw_pii
from .lead_scoring_models import ExplainableLeadScore
from .sales_intelligence_models import SalesIntelligenceSnapshot


class SalesAwareLeadScorePreview(BaseModel):
    model_config = ConfigDict(frozen=True)

    sales_intelligence: SalesIntelligenceSnapshot
    lead_score: ExplainableLeadScore
    persisted: bool = False
    shadow_mode: bool = True
    execution_enabled: bool = False
    external_writes_enabled: bool = False
    customer_contact_enabled: bool = False
    contains_raw_pii: bool = False

    @model_validator(mode="after")
    def validate_preview_boundary(self) -> "SalesAwareLeadScorePreview":
        if (
            self.persisted
            or self.execution_enabled
            or self.external_writes_enabled
            or self.customer_contact_enabled
            or self.contains_raw_pii
        ):
            raise ValueError(
                "SLA-aware lead score preview must remain non-persisting, shadow-only and PII-free"
            )
        if self.sales_intelligence.subject_ref != self.lead_score.subject_ref:
            raise ValueError("sales intelligence and lead score subjects must match")
        if self.sales_intelligence.as_of != self.lead_score.as_of:
            raise ValueError("sales intelligence and lead score as_of timestamps must match")
        assert_no_raw_pii(self.model_dump(mode="python"), path="sales_aware_lead_score")
        return self
