from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


CAMPAIGN_ID_PATTERN = re.compile(
    r"^CMP-[A-Z0-9]{2,12}-[A-Z0-9]{2,20}-\d{6}-\d{2}$"
)
SECRET_KEY_PATTERN = re.compile(
    r"(^|_)(secret|token|password|api_?key|credential)(_|$)", re.IGNORECASE
)


def slug_token(value: str, *, max_length: int) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    token = re.sub(r"[^A-Za-z0-9]+", "", ascii_text).upper()
    return token[:max_length] or "CAMPAIGN"


def build_campaign_id(
    *, project_code: str, campaign_name: str, start_date: date, sequence: int
) -> str:
    candidate = (
        f"CMP-{slug_token(project_code, max_length=12)}-"
        f"{slug_token(campaign_name, max_length=20)}-{start_date:%Y%m}-{sequence:02d}"
    )
    if not CAMPAIGN_ID_PATTERN.fullmatch(candidate):
        raise ValueError("generated campaign_id does not match the Campaign OS contract")
    return candidate


def assert_no_secrets(value: Any, *, path: str = "campaign") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if SECRET_KEY_PATTERN.search(str(key)):
                raise ValueError(f"Campaign object cannot store secrets: {path}.{key}")
            assert_no_secrets(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            assert_no_secrets(item, path=f"{path}[{index}]")


class CampaignStatus(str, Enum):
    DRAFT = "draft"
    PLANNED = "planned"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    READY_TO_EXECUTE = "ready_to_execute"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class PlanningStage(str, Enum):
    RESEARCH = "research"
    PLAN = "plan"
    DRAFT = "draft"
    PREVIEW = "preview"


class ProviderStatus(str, Enum):
    READ_ONLY = "read_only"
    CONTRACT_ONLY = "contract_only"
    NOT_CONFIGURED = "not_configured"
    PARTIAL = "partial"


class ApprovalState(str, Enum):
    NOT_REQUESTED = "not_requested"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"


class CampaignChannel(str, Enum):
    META_ADS = "meta_ads"
    GOOGLE_ADS = "google_ads"
    EMAIL = "email"
    ZALO_ZBS = "zalo_zbs"
    WEB_LANDING = "web_landing"


class CampaignBudget(BaseModel):
    amount: int = Field(gt=0)
    currency: str = Field(default="VND", pattern=r"^[A-Z]{3}$")


class KPITarget(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    target: float = Field(gt=0)
    unit: str = Field(min_length=1, max_length=40)
    funnel_stage: str = Field(min_length=2, max_length=60)


class TrackingContract(BaseModel):
    campaign_id: str
    utm_source: str = "{{channel}}"
    utm_medium: str = "{{medium}}"
    utm_campaign: str
    utm_content: str = "{{creative_id}}"
    source_campaign_id: str = "{{source_campaign_id}}"
    source_adset_id: str | None = "{{source_adset_id}}"
    source_ad_group_id: str | None = "{{source_ad_group_id}}"
    source_ad_id: str = "{{source_ad_id}}"
    landing_page: str = "{{landing_page_url}}"
    first_touch: str = "{{first_touch_json}}"
    last_touch: str = "{{last_touch_json}}"
    lead_id: str = "{{lead_id}}"
    opportunity_id: str = "{{opportunity_id}}"
    propagation_targets: list[str] = Field(
        default_factory=lambda: [
            "landing_page_form",
            "EspoCRM Lead",
            "EspoCRM Opportunity",
            "Sales Hub",
            "GA4 events",
            "channel reporting",
        ]
    )


class ChannelPlan(BaseModel):
    plan_id: str = Field(default_factory=lambda: f"cpl_{uuid4().hex[:12]}")
    channel: CampaignChannel
    specialist_agent: str
    stage: PlanningStage = PlanningStage.DRAFT
    provider_status: ProviderStatus
    approval_state: ApprovalState = ApprovalState.NOT_REQUESTED
    objective: str
    audience: list[str] = Field(default_factory=list)
    proposed_budget: CampaignBudget | None = None
    deliverables: list[str] = Field(default_factory=list)
    structure: dict[str, Any] = Field(default_factory=dict)
    validation: list[str] = Field(default_factory=list)
    execution_enabled: bool = False
    requires_approval_for_execution: bool = True


class CreativeBrief(BaseModel):
    creative_id: str = Field(default_factory=lambda: f"crt_{uuid4().hex[:12]}")
    name: str
    format: str
    hook: str
    message: str
    cta: str
    variants: list[str] = Field(default_factory=list)
    stage: PlanningStage = PlanningStage.DRAFT


class LandingPageDraft(BaseModel):
    landing_page_id: str = Field(default_factory=lambda: f"lp_{uuid4().hex[:12]}")
    title: str
    target_system: str = "WordPress/Sales Hub"
    target_path: str
    sections: list[str]
    cta: str
    form_fields: list[str]
    tracking_fields: list[str]
    environment: str = "staging"
    stage: PlanningStage = PlanningStage.PREVIEW
    production_publish_enabled: bool = False


class SequenceDraft(BaseModel):
    sequence_id: str = Field(default_factory=lambda: f"seq_{uuid4().hex[:12]}")
    channel: str
    provider_status: ProviderStatus
    segment: str
    steps: list[dict[str, str]]
    consent_required: bool = True
    frequency_guardrail: str
    tracking_fields: list[str]
    stage: PlanningStage = PlanningStage.DRAFT
    live_send_enabled: bool = False


class SalesHandoff(BaseModel):
    lead_stage: str = "Marketing Qualified Lead"
    owner_rule: str = "Assign through existing EspoCRM/Sales Hub routing"
    first_response_sla_minutes: int = 15
    visit_booking_sla_hours: int = 24
    required_context: list[str] = Field(
        default_factory=lambda: [
            "campaign_id",
            "project",
            "audience segment",
            "first_touch",
            "last_touch",
            "lead consent",
        ]
    )


class ApprovalRequirement(BaseModel):
    scope: str
    action: str
    target_system: str
    required_role: str = "owner"
    approved: bool = False
    execution_enabled: bool = False
    reason: str


class AuditMetadata(BaseModel):
    created_by: str
    updated_by: str
    owner: str
    version: int = 1
    source_request: str | None = None


class Campaign(BaseModel):
    campaign_id: str = Field(pattern=CAMPAIGN_ID_PATTERN.pattern)
    name: str = Field(min_length=3, max_length=200)
    project: str = Field(min_length=2, max_length=200)
    project_code: str = Field(min_length=2, max_length=20)
    objective: str = Field(min_length=3, max_length=2000)
    audience: list[str] = Field(min_length=1)
    budget: CampaignBudget
    start_date: date
    end_date: date
    kpi_targets: list[KPITarget] = Field(min_length=1)
    status: CampaignStatus = CampaignStatus.DRAFT
    channel_plans: list[ChannelPlan] = Field(default_factory=list)
    creatives: list[CreativeBrief] = Field(default_factory=list)
    landing_pages: list[LandingPageDraft] = Field(default_factory=list)
    email_sequence_refs: list[SequenceDraft] = Field(default_factory=list)
    zalo_zbs_sequence_refs: list[SequenceDraft] = Field(default_factory=list)
    crm_source_refs: dict[str, str] = Field(default_factory=dict)
    attribution_refs: dict[str, str] = Field(default_factory=dict)
    tracking: TrackingContract
    sales_handoff: SalesHandoff = Field(default_factory=SalesHandoff)
    approval_package: list[ApprovalRequirement] = Field(default_factory=list)
    audit_metadata: AuditMetadata
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def validate_campaign(self) -> "Campaign":
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        if self.tracking.campaign_id != self.campaign_id:
            raise ValueError("tracking campaign_id must match Campaign campaign_id")
        assert_no_secrets(self.model_dump(mode="python"))
        return self


class CampaignCreate(BaseModel):
    name: str = Field(min_length=3, max_length=200)
    project: str = Field(min_length=2, max_length=200)
    project_code: str = Field(min_length=2, max_length=20)
    objective: str = Field(min_length=3, max_length=2000)
    audience: list[str] = Field(min_length=1)
    budget: CampaignBudget
    start_date: date
    end_date: date
    kpi_targets: list[KPITarget] = Field(min_length=1)
    owner: str = Field(min_length=1, max_length=200)
    crm_source_refs: dict[str, str] = Field(default_factory=dict)
    attribution_refs: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def reject_secret_fields(self) -> "CampaignCreate":
        assert_no_secrets(self.model_dump(mode="python"))
        return self


class CampaignDraftUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=200)
    objective: str | None = Field(default=None, min_length=3, max_length=2000)
    audience: list[str] | None = None
    budget: CampaignBudget | None = None
    start_date: date | None = None
    end_date: date | None = None
    kpi_targets: list[KPITarget] | None = None
    owner: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def reject_secret_fields(self) -> "CampaignDraftUpdate":
        assert_no_secrets(self.model_dump(exclude_none=True, mode="python"))
        return self


class CampaignBriefRequest(BaseModel):
    request: str = Field(min_length=10, max_length=4000)
    owner: str | None = Field(default=None, max_length=200)


class CampaignApprovalRequest(BaseModel):
    scope: str = Field(default="campaign", min_length=2, max_length=100)
    note: str | None = Field(default=None, max_length=1000)


class CampaignApprovalDecision(BaseModel):
    approved: bool
    note: str | None = Field(default=None, max_length=1000)


class CampaignTransitionRequest(BaseModel):
    target_status: CampaignStatus
    note: str | None = Field(default=None, max_length=1000)


class CampaignAuditEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: f"caud_{uuid4().hex[:16]}")
    campaign_id: str
    event_type: str
    actor: str
    from_status: CampaignStatus | None = None
    to_status: CampaignStatus | None = None
    scope: str | None = None
    detail: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def reject_secret_fields(self) -> "CampaignAuditEvent":
        assert_no_secrets(self.metadata, path="campaign_audit.metadata")
        return self


class CampaignSummary(BaseModel):
    campaign_id: str
    name: str
    project: str
    status: CampaignStatus
    budget: CampaignBudget
    kpi_targets: list[KPITarget]
    channel_status: dict[str, str]
    approvals_pending: int
    execution_enabled: bool
    updated_at: datetime
