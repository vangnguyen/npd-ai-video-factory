from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProviderHealthState(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    STALE = "stale"
    NO_DATA = "no_data"
    NOT_CONFIGURED = "not_configured"
    FAILED = "failed"


class ProviderAlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class ProviderAlertStatus(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class ProviderHealthSchedulerState(str, Enum):
    DISABLED = "disabled"
    IDLE = "idle"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ProviderHealthObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,79}$")
    state: ProviderHealthState
    configuration_state: str = Field(
        pattern=r"^(configured|incomplete|not_configured|internal)$"
    )
    probe_state: str = Field(
        pattern=r"^(available|failed|not_configured|not_applicable)$"
    )
    freshness_state: str | None = Field(
        default=None, pattern=r"^(fresh|stale|no_data)$"
    )
    freshness_evidence: str | None = Field(
        default=None, pattern=r"^(heartbeat|delivery_fallback|none)$"
    )
    target_minutes: int | None = Field(default=None, ge=1, le=43200)
    age_minutes: float | None = Field(default=None, ge=0)
    activity_age_minutes: float | None = Field(default=None, ge=0)
    heartbeat_age_minutes: float | None = Field(default=None, ge=0)
    last_success_at: datetime | None = None
    last_receipt_id: str | None = None
    detail: str = Field(max_length=500)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    read_only: bool = True
    external_writes_enabled: bool = False

    @model_validator(mode="after")
    def no_write_state(self) -> "ProviderHealthObservation":
        if not self.read_only or self.external_writes_enabled:
            raise ValueError("provider-health observations must remain read-only")
        return self


class ProviderHealthSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot_id: str = Field(pattern=r"^phs_[0-9a-f]{24}$")
    observed_at: datetime
    providers: list[ProviderHealthObservation] = Field(default_factory=list)
    healthy: int = 0
    degraded: int = 0
    failed: int = 0
    stale: int = 0
    no_data: int = 0
    not_configured: int = 0
    production_write_enabled: bool = False
    external_notifications_enabled: bool = False

    @model_validator(mode="after")
    def no_external_effects(self) -> "ProviderHealthSnapshot":
        if self.production_write_enabled or self.external_notifications_enabled:
            raise ValueError("provider-health snapshots cannot enable external effects")
        return self


class ProviderHealthAlert(BaseModel):
    alert_id: str = Field(pattern=r"^pha_[0-9a-f]{24}$")
    dedupe_key: str = Field(pattern=r"^[a-z][a-z0-9_.:-]{2,159}$")
    provider: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,79}$")
    alert_type: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,79}$")
    severity: ProviderAlertSeverity
    status: ProviderAlertStatus = ProviderAlertStatus.OPEN
    detail: str = Field(max_length=500)
    first_detected_at: datetime
    last_detected_at: datetime
    occurrence_count: int = Field(default=1, ge=1)
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = Field(default=None, max_length=200)
    resolved_at: datetime | None = None
    routing_targets: list[str] = Field(default_factory=lambda: ["command_center", "audit"])
    external_notifications_enabled: bool = False
    external_writes_enabled: bool = False

    @model_validator(mode="after")
    def internal_only(self) -> "ProviderHealthAlert":
        if set(self.routing_targets) - {"command_center", "audit"}:
            raise ValueError("provider alerts may route only to internal targets")
        if self.external_notifications_enabled or self.external_writes_enabled:
            raise ValueError("provider alerts cannot enable external effects")
        return self


class ProviderHealthStatus(BaseModel):
    mode: str = "read_only_provider_health_internal_alerting"
    latest_snapshot: ProviderHealthSnapshot | None = None
    alerts: list[ProviderHealthAlert] = Field(default_factory=list)
    open_alerts: int = 0
    acknowledged_alerts: int = 0
    critical_alerts: int = 0
    routing_targets: list[str] = Field(default_factory=lambda: ["command_center", "audit"])
    external_notifications_enabled: bool = False
    production_write_enabled: bool = False


class ProviderHealthSchedulerStatus(BaseModel):
    mode: str = "scheduled_internal_health_evaluation"
    enabled: bool = False
    interval_seconds: int = Field(default=300, ge=60, le=86400)
    state: ProviderHealthSchedulerState = ProviderHealthSchedulerState.DISABLED
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    next_run_at: datetime | None = None
    last_snapshot_id: str | None = None
    run_count: int = Field(default=0, ge=0)
    skipped_lease_count: int = Field(default=0, ge=0)
    last_error_code: str | None = Field(
        default=None, pattern=r"^[a-z][a-z0-9_.-]{1,79}$"
    )
    evaluates_cached_state_only: bool = True
    external_provider_probes_enabled: bool = False
    external_notifications_enabled: bool = False
    production_write_enabled: bool = False

    @model_validator(mode="after")
    def internal_only(self) -> "ProviderHealthSchedulerStatus":
        if (
            not self.evaluates_cached_state_only
            or self.external_provider_probes_enabled
            or self.external_notifications_enabled
            or self.production_write_enabled
        ):
            raise ValueError("provider-health scheduler must remain internal-only")
        return self


class ProviderAlertAcknowledgeRequest(BaseModel):
    expected_status: ProviderAlertStatus = ProviderAlertStatus.OPEN
