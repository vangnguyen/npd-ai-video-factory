from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .attribution_models import TouchpointType, assert_no_raw_pii, assert_pseudonymous_reference


JOURNEY_REPLAY_VERSION = "phase-9a-v1"
JOURNEY_SALES_EVIDENCE_VERSION = "phase-9a-sales-v1"


class JourneyState(str, Enum):
    ANONYMOUS = "anonymous"
    LEAD = "lead"
    ENGAGED = "engaged"
    MQL = "mql"
    SQL = "sql"
    APPOINTMENT = "appointment"
    SITE_VISIT = "site_visit"
    NEGOTIATION = "negotiation"
    WON = "won"
    CUSTOMER = "customer"
    LOST = "lost"
    REENGAGEMENT = "reengagement"


class JourneyEvidenceAuthority(str, Enum):
    NOT_REQUIRED = "not_required"
    ACCEPTED = "accepted"
    REJECTED_SOURCE = "rejected_source"
    INVALID_CONTRACT = "invalid_contract"


SALES_EVIDENCE_STATES = {
    JourneyState.MQL,
    JourneyState.APPOINTMENT,
    JourneyState.SITE_VISIT,
    JourneyState.LOST,
    JourneyState.CUSTOMER,
    JourneyState.REENGAGEMENT,
}


class JourneyStageEvidence(BaseModel):
    """Versioned PII-free stage declaration carried inside TouchpointEvent.metadata."""

    contract_version: str = Field(
        default=JOURNEY_SALES_EVIDENCE_VERSION,
        pattern=r"^phase-9a-sales-v1$",
    )
    state: JourneyState
    source_record_ref: str = Field(min_length=2, max_length=120)
    external_writes_enabled: bool = False

    @model_validator(mode="after")
    def validate_contract(self) -> "JourneyStageEvidence":
        if self.state not in SALES_EVIDENCE_STATES:
            raise ValueError("journey sales evidence state is not supported by this contract")
        assert_pseudonymous_reference(self.source_record_ref)
        if self.external_writes_enabled:
            raise ValueError("journey evidence contract cannot enable external writes")
        assert_no_raw_pii(self.model_dump(mode="python"), path="journey_stage_evidence")
        return self


class JourneyEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str
    event_type: TouchpointType
    occurred_at: datetime
    observed_at: datetime
    source_system: str
    channel: str
    campaign_id: str
    declared_state: JourneyState | None = None
    authority_status: JourneyEvidenceAuthority = JourneyEvidenceAuthority.NOT_REQUIRED
    authority_detail: str | None = Field(default=None, max_length=500)


class JourneyTransition(BaseModel):
    model_config = ConfigDict(frozen=True)

    previous_state: JourneyState
    new_state: JourneyState
    occurred_at: datetime
    observed_at: datetime
    evidence_event_id: str
    reason: str = Field(min_length=5, max_length=500)
    confidence: float = Field(ge=0, le=1)
    skipped_states: list[JourneyState] = Field(default_factory=list)
    rule_version: str = JOURNEY_REPLAY_VERSION


class JourneyProjection(BaseModel):
    subject_ref: str = Field(min_length=3, max_length=120)
    current_state: JourneyState
    evidence_count: int = Field(ge=0)
    transition_count: int = Field(ge=0)
    suppressed_transition_count: int = Field(ge=0)
    untrusted_evidence_count: int = Field(default=0, ge=0)
    evidence: list[JourneyEvidence] = Field(default_factory=list)
    transitions: list[JourneyTransition] = Field(default_factory=list)
    campaign_ids: list[str] = Field(default_factory=list)
    source_systems: list[str] = Field(default_factory=list)
    latest_event_at: datetime | None = None
    missing_signals: list[JourneyState] = Field(default_factory=list)
    data_quality: str = "observed_partial"
    replay_version: str = JOURNEY_REPLAY_VERSION
    shadow_mode: bool = True
    execution_enabled: bool = False
    external_writes_enabled: bool = False
    contains_raw_pii: bool = False

    @model_validator(mode="after")
    def validate_read_only_projection(self) -> "JourneyProjection":
        if self.execution_enabled or self.external_writes_enabled or self.contains_raw_pii:
            raise ValueError("Phase 9A journey projection must remain read-only and PII-free")
        if self.transition_count != len(self.transitions):
            raise ValueError("transition_count must match transitions")
        if self.evidence_count != len(self.evidence):
            raise ValueError("evidence_count must match evidence")
        counted_untrusted = sum(
            item.authority_status
            in {
                JourneyEvidenceAuthority.REJECTED_SOURCE,
                JourneyEvidenceAuthority.INVALID_CONTRACT,
            }
            for item in self.evidence
        )
        if self.untrusted_evidence_count != counted_untrusted:
            raise ValueError("untrusted_evidence_count must match rejected evidence")
        assert_no_raw_pii(self.model_dump(mode="python"), path="journey_projection")
        return self
