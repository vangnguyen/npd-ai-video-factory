from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


BRIDGE_CONTRACT_VERSION = "agent-hub-bridge.v1"
BRIDGE_WEBHOOK_PATH = "/agent-hub/events/v1"
BRIDGE_BASE_PATH = "/api/v1/bridge"
IDEMPOTENCY_KEY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{15,199}$"

LIVE_INBOUND_ACTIONS = ("project.create_draft",)
LIVE_OUTBOUND_EVENTS = ("video.project.created",)
BRIDGE_ROLES = ("owner", "editor", "reviewer", "viewer", "service")
RESERVED_OUTBOUND_EVENTS = (
    "trend.opportunity.detected",
    "idea.shortlist.ready",
    "video.project.created",
    "video.analysis.completed",
    "video.preview.ready",
    "video.approval.required",
    "video.approved",
    "video.render.completed",
    "video.render.failed",
    "video.publish.completed",
    "video.publish.failed",
    "video.analytics.updated",
    "video.winner.detected",
)

_SECRET_FIELD_TERMS = (
    "secret",
    "token",
    "password",
    "credential",
    "cookie",
    "api_key",
    "apikey",
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include a timezone")
    return value.astimezone(timezone.utc)


ResourceId = Annotated[
    str,
    Field(min_length=3, max_length=120, pattern=r"^[A-Za-z][A-Za-z0-9_.:-]{2,119}$"),
]
BoundedRef = Annotated[str, Field(min_length=1, max_length=768)]
UtcDatetime = Annotated[datetime, AfterValidator(_as_utc)]


def assert_secret_free(value: object, *, path: str = "payload") -> None:
    """Reject secret-shaped keys and common raw credential value prefixes."""

    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower().replace("-", "_")
            if any(term in normalized for term in _SECRET_FIELD_TERMS):
                raise ValueError(f"secret-like field is not allowed at {path}")
            assert_secret_free(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_secret_free(child, path=f"{path}[{index}]")
    elif isinstance(value, str) and (
        value.startswith("Bearer ") or value.startswith("sk-")
    ):
        raise ValueError(f"secret-like value is not allowed at {path}")


class StrictDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    @model_validator(mode="after")
    def reject_raw_secrets(self) -> "StrictDTO":
        assert_secret_free(
            self.model_dump(mode="json"), path=self.__class__.__name__
        )
        return self


class BoundaryMode(StrEnum):
    DISABLED = "disabled"
    NOT_CONFIGURED = "not_configured"
    MOCK = "mock"


class CapabilityState(StrEnum):
    LIVE = "live"
    RESERVED = "reserved"
    UNSUPPORTED = "unsupported"
    NOT_CONFIGURED = "not_configured"


class EventType(StrEnum):
    TREND_OPPORTUNITY_DETECTED = "trend.opportunity.detected"
    IDEA_SHORTLIST_READY = "idea.shortlist.ready"
    VIDEO_PROJECT_CREATED = "video.project.created"
    VIDEO_ANALYSIS_COMPLETED = "video.analysis.completed"
    VIDEO_PREVIEW_READY = "video.preview.ready"
    VIDEO_APPROVAL_REQUIRED = "video.approval.required"
    VIDEO_APPROVED = "video.approved"
    VIDEO_RENDER_COMPLETED = "video.render.completed"
    VIDEO_RENDER_FAILED = "video.render.failed"
    VIDEO_PUBLISH_COMPLETED = "video.publish.completed"
    VIDEO_PUBLISH_FAILED = "video.publish.failed"
    VIDEO_ANALYTICS_UPDATED = "video.analytics.updated"
    VIDEO_WINNER_DETECTED = "video.winner.detected"


class BridgeProjectDraftRequest(StrictDTO):
    workspace_id: str | None = Field(
        default=None, pattern=r"^wsp_[A-Za-z0-9_-]{4,60}$"
    )
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,80}$")
    name: str = Field(min_length=1, max_length=240)
    niche: str = Field(default="custom", min_length=1, max_length=80)
    source_campaign_id: str | None = Field(default=None, max_length=160)
    brief: dict[str, Any] = Field(default_factory=dict)
    execution_mode: Literal["draft_only"] = "draft_only"
    start_pipeline: Literal[False] = False
    publish_requested: Literal[False] = False
    external_action_requested: Literal[False] = False

    @model_validator(mode="after")
    def secret_free(self) -> "BridgeProjectDraftRequest":
        assert_secret_free(self.model_dump(mode="json"), path="project_request")
        return self


class BridgeProjectRead(StrictDTO):
    project_id: ResourceId
    workspace_id: ResourceId
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,80}$")
    name: str = Field(min_length=1, max_length=240)
    niche: str = Field(min_length=1, max_length=80)
    status: str = Field(min_length=1, max_length=40)
    current_version_id: ResourceId | None
    version: int = Field(ge=1)
    provenance: dict[str, Any]
    created_at: UtcDatetime
    updated_at: UtcDatetime

    @model_validator(mode="after")
    def secret_free(self) -> "BridgeProjectRead":
        assert_secret_free(self.provenance, path="project.provenance")
        return self


class BridgeProjectVersionRead(StrictDTO):
    project_version_id: ResourceId
    workspace_id: ResourceId
    project_id: ResourceId
    ordinal: int = Field(ge=1)
    label: str = Field(min_length=1, max_length=120)
    snapshot: dict[str, Any]
    source_job_id: ResourceId | None
    version: int = Field(ge=1)
    provenance: dict[str, Any]
    created_at: UtcDatetime
    updated_at: UtcDatetime

    @model_validator(mode="after")
    def secret_free(self) -> "BridgeProjectVersionRead":
        assert_secret_free(self.snapshot, path="project_version.snapshot")
        assert_secret_free(self.provenance, path="project_version.provenance")
        return self


class BridgeProjectRequestRead(StrictDTO):
    request_id: ResourceId
    contract_version: Literal["agent-hub-bridge.v1"] = BRIDGE_CONTRACT_VERSION
    service_id: ResourceId
    workspace_id: ResourceId
    project_id: ResourceId | None
    project_version_id: ResourceId | None
    status: Literal["reserved", "succeeded", "failed"]
    request: dict[str, Any]
    result: dict[str, Any] | None
    failure_code: str | None = Field(default=None, max_length=120)
    failure_reason: str | None = Field(default=None, max_length=1000)
    execution_started: Literal[False] = False
    external_action: Literal[False] = False
    created_at: UtcDatetime
    updated_at: UtcDatetime

    @model_validator(mode="after")
    def secret_free(self) -> "BridgeProjectRequestRead":
        assert_secret_free(self.request, path="bridge_request.request")
        assert_secret_free(self.result, path="bridge_request.result")
        return self


class BridgeProjectCreatedResponse(StrictDTO):
    bridge_request: BridgeProjectRequestRead
    project: BridgeProjectRead
    project_version: BridgeProjectVersionRead
    idempotent_replay: bool


class BridgeProjectSummary(StrictDTO):
    contract_version: Literal["agent-hub-bridge.v1"] = BRIDGE_CONTRACT_VERSION
    project: BridgeProjectRead
    versions: int = Field(ge=0)
    assets: int = Field(ge=0)
    estimated_cost_vnd: str = Field(pattern=r"^[0-9]+(?:\.[0-9]+)?$", max_length=40)
    actual_cost_vnd: str = Field(pattern=r"^[0-9]+(?:\.[0-9]+)?$", max_length=40)
    publications: int = Field(ge=0)
    analytics_snapshots: int = Field(ge=0)
    execution_controlled_by_video_factory: Literal[True] = True
    external_action: Literal[False] = False


class BridgeContractRead(StrictDTO):
    contract_version: Literal["agent-hub-bridge.v1"] = BRIDGE_CONTRACT_VERSION
    api_version: Literal["v1"] = "v1"
    service_auth: Literal["hmac-sha256"] = "hmac-sha256"
    webhook_auth: Literal["hmac-sha256-keyring"] = "hmac-sha256-keyring"
    inbound_actions: list[str] = Field(min_length=1, max_length=20)
    outbound_events: list[str] = Field(min_length=1, max_length=50)
    roles: list[str] = Field(min_length=1, max_length=20)
    execution_boundary: Literal["draft_only"] = "draft_only"
    agent_hub_runtime_dependency: Literal[False] = False
    shared_database: Literal[False] = False
    shared_redis: Literal[False] = False
    production_deployed: bool = False

    @model_validator(mode="after")
    def pinned_v2_11_boundary(self) -> "BridgeContractRead":
        if tuple(self.inbound_actions) != LIVE_INBOUND_ACTIONS:
            raise ValueError("bridge action contract differs from the pinned V2-11 boundary")
        if tuple(self.outbound_events) != RESERVED_OUTBOUND_EVENTS:
            raise ValueError("bridge event vocabulary differs from the pinned V2-11 boundary")
        if tuple(self.roles) != BRIDGE_ROLES:
            raise ValueError("bridge role contract differs from the pinned V2-11 boundary")
        return self


class VideoFactoryProjectDTO(StrictDTO):
    contract_version: Literal["agent-hub-bridge.v1"] = BRIDGE_CONTRACT_VERSION
    project_id: ResourceId
    workspace_id: ResourceId
    project_version_id: ResourceId
    source_campaign_id: str | None = Field(default=None, max_length=160)
    name: str = Field(min_length=1, max_length=240)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,80}$")
    status: Literal["draft"] = "draft"
    execution_started: Literal[False] = False
    external_action: Literal[False] = False


class VideoFactoryStatusDTO(StrictDTO):
    contract_version: Literal["agent-hub-bridge.v1"] = BRIDGE_CONTRACT_VERSION
    request_id: ResourceId
    status: Literal["reserved", "succeeded", "failed"]
    project_id: ResourceId | None = None
    project_version_id: ResourceId | None = None
    failure_code: str | None = Field(default=None, max_length=120)
    failure_reason: str | None = Field(default=None, max_length=1000)
    execution_started: Literal[False] = False
    external_action: Literal[False] = False
    updated_at: UtcDatetime


class VideoFactoryAnalysisDTO(StrictDTO):
    contract_version: Literal["agent-hub-bridge.v1"] = BRIDGE_CONTRACT_VERSION
    capability_state: Literal["reserved"] = "reserved"
    analysis_id: ResourceId
    project_id: ResourceId
    status: Literal["queued", "running", "succeeded", "failed"]
    summary: dict[str, Any] = Field(default_factory=dict)
    source_media_mutated: Literal[False] = False
    publish_requested: Literal[False] = False
    paid_external_call: Literal[False] = False

    @field_validator("summary")
    @classmethod
    def analysis_summary_is_secret_free(cls, value: dict[str, Any]) -> dict[str, Any]:
        assert_secret_free(value, path="analysis.summary")
        return value


class VideoFactoryGenerationRequestDTO(StrictDTO):
    capability_state: Literal["reserved"] = "reserved"
    project_id: ResourceId
    project_version_id: ResourceId
    objective: str = Field(min_length=1, max_length=1000)
    constraints: dict[str, Any] = Field(default_factory=dict)
    execution_mode: Literal["draft_only"] = "draft_only"
    publish_requested: Literal[False] = False
    external_action_requested: Literal[False] = False

    @field_validator("constraints")
    @classmethod
    def generation_constraints_are_secret_free(
        cls, value: dict[str, Any]
    ) -> dict[str, Any]:
        assert_secret_free(value, path="generation.constraints")
        return value


class VideoFactoryAnalysisRequestDTO(StrictDTO):
    capability_state: Literal["reserved"] = "reserved"
    project_id: ResourceId
    source_asset_ref: BoundedRef
    idempotency_key_ref: str = Field(pattern=IDEMPOTENCY_KEY_PATTERN)
    source_media_mutated: Literal[False] = False
    publish_requested: Literal[False] = False
    paid_external_call: Literal[False] = False

    @field_validator("source_asset_ref", "idempotency_key_ref")
    @classmethod
    def analysis_refs_are_secret_free(cls, value: str) -> str:
        assert_secret_free(value, path="analysis_request.ref")
        return value


class VideoFactoryPreviewDTO(StrictDTO):
    contract_version: Literal["agent-hub-bridge.v1"] = BRIDGE_CONTRACT_VERSION
    capability_state: Literal["reserved"] = "reserved"
    preview_id: ResourceId
    project_id: ResourceId
    timeline_version: int = Field(ge=1)
    status: Literal["queued", "running", "ready", "stale", "cancelled", "failed"]
    artifact_ref: BoundedRef | None = None
    checksum_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    source_media_mutated: Literal[False] = False
    publish_requested: Literal[False] = False
    external_call: Literal[False] = False


class VideoFactoryPreviewRequestDTO(StrictDTO):
    capability_state: Literal["reserved"] = "reserved"
    project_id: ResourceId
    timeline_version: int = Field(ge=1)
    idempotency_key_ref: str = Field(pattern=IDEMPOTENCY_KEY_PATTERN)
    publish_requested: Literal[False] = False
    external_call: Literal[False] = False

    @field_validator("idempotency_key_ref")
    @classmethod
    def preview_ref_is_secret_free(cls, value: str) -> str:
        assert_secret_free(value, path="preview_request.idempotency_key_ref")
        return value


class VideoFactoryApprovalDTO(StrictDTO):
    contract_version: Literal["agent-hub-bridge.v1"] = BRIDGE_CONTRACT_VERSION
    capability_state: Literal["reserved"] = "reserved"
    approval_id: ResourceId
    project_id: ResourceId
    render_id: ResourceId
    status: Literal["awaiting_review", "approved", "changes_requested", "rejected"]
    reviewer_ref: str | None = Field(default=None, max_length=160)
    comment: str | None = Field(default=None, max_length=2000)


class VideoFactoryApprovalRequestDTO(StrictDTO):
    capability_state: Literal["reserved"] = "reserved"
    project_id: ResourceId
    render_id: ResourceId
    expected_project_version_id: ResourceId


class VideoFactoryApprovalDecisionDTO(StrictDTO):
    capability_state: Literal["reserved"] = "reserved"
    project_id: ResourceId
    approval_id: ResourceId
    decision: Literal["approved", "changes_requested", "rejected"]
    reviewer_ref: str = Field(min_length=1, max_length=160)
    comment: str | None = Field(default=None, max_length=2000)

    @field_validator("reviewer_ref", "comment")
    @classmethod
    def approval_text_is_secret_free(cls, value: str | None) -> str | None:
        assert_secret_free(value, path="approval_decision")
        return value


class VideoFactoryRenderDTO(StrictDTO):
    contract_version: Literal["agent-hub-bridge.v1"] = BRIDGE_CONTRACT_VERSION
    capability_state: Literal["reserved"] = "reserved"
    render_id: ResourceId
    project_id: ResourceId
    profile: Literal["review-540x960", "final"]
    status: Literal[
        "queued",
        "running",
        "awaiting_review",
        "ready",
        "cancelled",
        "failed",
        "failed_qc",
    ]
    qc_passed: bool | None = None
    artifact_ref: BoundedRef | None = None
    checksum_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    publishing_allowed: Literal[False] = False
    external_publish_requested: Literal[False] = False


class VideoFactoryRenderRequestDTO(StrictDTO):
    capability_state: Literal["reserved"] = "reserved"
    project_id: ResourceId
    project_version_id: ResourceId
    approval_id: ResourceId
    profile: Literal["review-540x960", "final"]
    idempotency_key_ref: str = Field(pattern=IDEMPOTENCY_KEY_PATTERN)
    publishing_allowed: Literal[False] = False
    external_publish_requested: Literal[False] = False

    @field_validator("idempotency_key_ref")
    @classmethod
    def render_ref_is_secret_free(cls, value: str) -> str:
        assert_secret_free(value, path="render_request.idempotency_key_ref")
        return value


class VideoFactoryPublicationDTO(StrictDTO):
    contract_version: Literal["agent-hub-bridge.v1"] = BRIDGE_CONTRACT_VERSION
    capability_state: Literal["reserved"] = "reserved"
    publication_id: ResourceId
    project_id: ResourceId
    render_id: ResourceId
    platform: Literal["youtube", "tiktok", "instagram_reels", "facebook"]
    mode: Literal["dry_run"] = "dry_run"
    status: Literal["reserved", "succeeded", "blocked", "failed"]
    receipt_ref: BoundedRef | None = None
    external_action: Literal[False] = False
    duplicate_post_created: Literal[False] = False


class VideoFactoryPublicationQueryDTO(StrictDTO):
    capability_state: Literal["reserved"] = "reserved"
    project_id: ResourceId
    limit: int = Field(default=100, ge=1, le=1000)


class VideoFactoryPublicationRequestDTO(StrictDTO):
    capability_state: Literal["reserved"] = "reserved"
    project_id: ResourceId
    render_id: ResourceId
    platform: Literal["youtube", "tiktok", "instagram_reels", "facebook"]
    mode: Literal["dry_run"] = "dry_run"
    metadata: dict[str, Any] = Field(default_factory=dict)
    idempotency_key_ref: str = Field(pattern=IDEMPOTENCY_KEY_PATTERN)
    external_action: Literal[False] = False
    duplicate_post_requested: Literal[False] = False


class AnalyticsMetricDTO(StrictDTO):
    value: int | float | None
    supported: bool


class VideoFactoryAnalyticsDTO(StrictDTO):
    contract_version: Literal["agent-hub-bridge.v1"] = BRIDGE_CONTRACT_VERSION
    capability_state: Literal["reserved"] = "reserved"
    project_id: ResourceId
    sync_id: ResourceId | None = None
    status: Literal["not_configured", "queued", "running", "succeeded", "failed"]
    currency: Literal["VND"] = "VND"
    metrics: dict[str, AnalyticsMetricDTO] = Field(default_factory=dict)
    external_call: Literal[False] = False
    automatic_action: Literal[False] = False


class VideoFactoryAnalyticsQueryDTO(StrictDTO):
    capability_state: Literal["reserved"] = "reserved"
    project_id: ResourceId
    include_history: bool = False


class VideoProjectCreatedPayload(StrictDTO):
    project_id: ResourceId
    project_version_id: ResourceId
    workspace_id: ResourceId
    source_campaign_id: str | None = Field(default=None, max_length=160)
    status: Literal["draft"] = "draft"
    execution_started: Literal[False] = False
    external_action: Literal[False] = False


class VideoFactoryEventEnvelope(StrictDTO):
    contract_version: Literal["agent-hub-bridge.v1"] = BRIDGE_CONTRACT_VERSION
    event_id: str = Field(pattern=r"^bevt_[A-Za-z0-9_-]{4,60}$")
    event_type: EventType
    occurred_at: UtcDatetime
    payload: dict[str, Any]

    @model_validator(mode="after")
    def validate_event_payload(self) -> "VideoFactoryEventEnvelope":
        assert_secret_free(self.payload, path="event.payload")
        if self.event_type == EventType.VIDEO_PROJECT_CREATED:
            VideoProjectCreatedPayload.model_validate(self.payload)
        return self


class WebhookVerificationReceipt(StrictDTO):
    key_id: ResourceId
    signed_at_unix: int
    body_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    signature_verified: Literal[True] = True


class PersistedVideoFactoryEvent(StrictDTO):
    event: VideoFactoryEventEnvelope
    verification: WebhookVerificationReceipt
    received_at: UtcDatetime = Field(default_factory=utc_now)


class WebhookOutcome(StrEnum):
    ACCEPTED = "accepted"
    IDEMPOTENT_REPLAY = "idempotent_replay"
    CONFLICT = "conflict"


class VideoFactoryAuditRecord(StrictDTO):
    audit_id: str = Field(default_factory=lambda: f"vfau_{uuid4().hex[:16]}")
    event_id: ResourceId
    outcome: WebhookOutcome
    key_id: ResourceId
    body_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    detail: str = Field(max_length=240)
    created_at: UtcDatetime = Field(default_factory=utc_now)


class WebhookAcceptedResponse(StrictDTO):
    contract_version: Literal["agent-hub-bridge.v1"] = BRIDGE_CONTRACT_VERSION
    event_id: ResourceId
    status: Literal["accepted", "idempotent_replay"]
    external_action: Literal[False] = False


class VideoFactoryIntegrationStatus(StrictDTO):
    contract_version: Literal["agent-hub-bridge.v1"] = BRIDGE_CONTRACT_VERSION
    mode: BoundaryMode
    configured: bool
    network_calls_enabled: Literal[False] = False
    external_actions_enabled: Literal[False] = False
    live_inbound_actions: tuple[str, ...] = LIVE_INBOUND_ACTIONS
    live_outbound_events: tuple[str, ...] = LIVE_OUTBOUND_EVENTS
    reserved_outbound_events: tuple[str, ...] = RESERVED_OUTBOUND_EVENTS
    non_bridge_routes_allowed: Literal[False] = False
    shared_database: Literal[False] = False
    shared_redis: Literal[False] = False
    shared_process_memory: Literal[False] = False
