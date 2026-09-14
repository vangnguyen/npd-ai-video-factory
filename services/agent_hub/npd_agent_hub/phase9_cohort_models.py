"""One explicitly approved internal cohort; never inferred from campaign names."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Phase9ReportingExclusions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    commercial_leads: Literal[True] = True
    sales_revenue_attribution: Literal[True] = True
    customer_sla_metrics: Literal[True] = True
    provider_spend: Literal[True] = True
    external_notifications: Literal[True] = True


class Phase9InternalCohort(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    classification: Literal["phase9_internal_non_customer"]
    canonical_campaign_id: str = Field(min_length=1)
    subject_ref: str = Field(pattern=r"^lead:[A-Za-z0-9_-]{1,100}$")
    owner_id: str = Field(min_length=1, max_length=200)
    owner_approval_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    non_customer_proof_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scope: Literal["phase9_one_internal_task_report_audit_one_nba_review"]
    customer_contact: Literal[False] = False
    commercial_attribution: Literal[False] = False
    automation_enabled: Literal[False] = False
    reporting_exclusions: Phase9ReportingExclusions = Field(
        default_factory=Phase9ReportingExclusions
    )


class Phase9InternalDeliveryBinding(BaseModel):
    """Server-owned, one-delivery allowlist. No default production enrollment."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    cohort: Phase9InternalCohort
    delivery_id: str = Field(min_length=3, max_length=120)
    source_event_id: str = Field(min_length=2, max_length=200)
    occurred_at: datetime
    source_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_audit_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    delivery_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("occurred_at")
    @classmethod
    def aware_clock(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("internal clock must retain a timezone-aware source timestamp")
        return value
