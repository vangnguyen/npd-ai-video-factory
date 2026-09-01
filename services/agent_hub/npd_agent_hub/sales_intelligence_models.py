from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .attribution_models import assert_no_raw_pii, assert_pseudonymous_reference
from .campaign_models import CAMPAIGN_ID_PATTERN


SALES_ACTIVITY_CONTRACT_VERSION = "phase-9b-sales-activity-v1"
SALES_INTELLIGENCE_VERSION = "phase-9b-sales-intelligence-v1"


class SalesActivityType(str, Enum):
    FIRST_RESPONSE = "first_response"
    APPOINTMENT_BOOKED = "appointment_booked"
    SITE_VISIT_COMPLETED = "site_visit_completed"


class SalesSLAStatus(str, Enum):
    MET = "met"
    LATE = "late"
    PENDING = "pending"
    OVERDUE_MISSING_EVIDENCE = "overdue_missing_evidence"
    NOT_EVALUABLE = "not_evaluable"


class SalesActivityObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    activity_id: str = Field(min_length=2, max_length=120)
    contract_version: str = Field(
        default=SALES_ACTIVITY_CONTRACT_VERSION,
        pattern=r"^phase-9b-sales-activity-v1$",
    )
    activity_type: SalesActivityType
    occurred_at: datetime
    source_system: str = Field(min_length=2, max_length=80)
    source_record_ref: str = Field(min_length=2, max_length=120)
    campaign_id: str = Field(pattern=CAMPAIGN_ID_PATTERN.pattern)
    lead_id: str | None = Field(default=None, min_length=1, max_length=100)
    opportunity_id: str | None = Field(default=None, min_length=1, max_length=100)
    external_writes_enabled: bool = False

    _pseudonymous_refs = field_validator(
        "activity_id", "source_record_ref", "lead_id", "opportunity_id"
    )(assert_pseudonymous_reference)

    @model_validator(mode="after")
    def validate_activity(self) -> "SalesActivityObservation":
        if not self.lead_id and not self.opportunity_id:
            raise ValueError("sales activity requires lead_id or opportunity_id")
        if self.occurred_at.tzinfo is None:
            raise ValueError("sales activity occurred_at must be timezone-aware")
        if self.external_writes_enabled:
            raise ValueError("sales activity evidence cannot enable external writes")
        assert_no_raw_pii(self.model_dump(mode="python"), path="sales_activity")
        return self


class SalesIntelligencePreviewRequest(BaseModel):
    subject_ref: str = Field(min_length=3, max_length=120)
    observations: list[SalesActivityObservation] = Field(default_factory=list, max_length=500)
    as_of: datetime

    @model_validator(mode="after")
    def validate_request(self) -> "SalesIntelligencePreviewRequest":
        if self.as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        assert_no_raw_pii(self.model_dump(mode="python"), path="sales_intelligence_request")
        return self


class SalesSLAWindow(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    target_minutes: int | None = Field(default=None, ge=1)
    status: SalesSLAStatus
    clock_start_at: datetime | None = None
    deadline_at: datetime | None = None
    observed_at: datetime | None = None
    elapsed_minutes: float | None = Field(default=None, ge=0)
    evidence_refs: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)


class SalesFunnelEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    first_response_at: datetime | None = None
    appointment_booked_at: datetime | None = None
    site_visit_completed_at: datetime | None = None
    first_response_refs: list[str] = Field(default_factory=list)
    appointment_refs: list[str] = Field(default_factory=list)
    site_visit_refs: list[str] = Field(default_factory=list)


class SalesIntelligenceSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot_version: str = SALES_INTELLIGENCE_VERSION
    subject_ref: str = Field(min_length=3, max_length=120)
    as_of: datetime
    campaign_id: str | None = None
    project: str | None = Field(default=None, max_length=200)
    policy_source: str = "campaign_os_sales_handoff"
    lead_start_at: datetime | None = None
    lead_start_basis: str | None = None
    first_response_sla: SalesSLAWindow
    visit_booking_sla: SalesSLAWindow
    funnel: SalesFunnelEvidence
    accepted_activity_count: int = Field(ge=0)
    duplicate_activity_count: int = Field(ge=0)
    untrusted_activity_count: int = Field(ge=0)
    missing_inputs: list[str] = Field(default_factory=list)
    source_complete: bool = False
    persisted: bool = False
    shadow_mode: bool = True
    execution_enabled: bool = False
    external_writes_enabled: bool = False
    customer_contact_enabled: bool = False
    contains_raw_pii: bool = False

    @model_validator(mode="after")
    def validate_shadow_boundary(self) -> "SalesIntelligenceSnapshot":
        if (
            self.source_complete
            or self.persisted
            or self.execution_enabled
            or self.external_writes_enabled
            or self.customer_contact_enabled
            or self.contains_raw_pii
        ):
            raise ValueError(
                "Phase 9B sales intelligence preview must remain incomplete-source, non-persisting, read-only and PII-free"
            )
        assert_no_raw_pii(self.model_dump(mode="python"), path="sales_intelligence_snapshot")
        return self
