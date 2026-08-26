from __future__ import annotations

from datetime import datetime
from typing import Protocol

from ..attribution_models import (
    AttributionAuditEvent,
    AttributionDataQualitySnapshot,
    AttributionIntakeIssue,
    AttributionReconciliation,
    CampaignIdentityMapping,
    IdentitySource,
    TouchpointEvent,
)
from ..campaign_models import Campaign, CampaignAuditEvent, CampaignStatus
from ..delivery_models import (
    AttributionDeadLetter,
    AttributionDeliveryReceipt,
    AttributionHeartbeatReceipt,
)
from ..experiment_models import Experiment, ExperimentAuditEvent, ExperimentStatus
from ..models import AgentTask, AuditEvent, CommandCenterReport, ToolExecutionResult
from ..provider_health_models import (
    ProviderHealthAlert,
    ProviderHealthSchedulerStatus,
    ProviderHealthSnapshot,
)


class HubStore(Protocol):
    backend_name: str

    def health(self) -> bool: ...

    def save_task(self, task: AgentTask) -> None: ...

    def get_task(self, task_id: str) -> AgentTask | None: ...

    def save_report(self, report: CommandCenterReport) -> None: ...

    def get_report(self, task_id: str) -> CommandCenterReport | None: ...

    def append_execution(self, result: ToolExecutionResult) -> None: ...

    def list_executions(
        self, task_id: str, limit: int = 100
    ) -> list[ToolExecutionResult]: ...

    def append_audit(self, event: AuditEvent) -> None: ...

    def list_audit(self, task_id: str, limit: int = 100) -> list[AuditEvent]: ...

    def list_recent_audit(self, limit: int = 100) -> list[AuditEvent]: ...

    def list_recent_tasks(self, limit: int = 50) -> list[tuple[str, datetime]]: ...

    def save_campaign(self, campaign: Campaign) -> None: ...

    def get_campaign(self, campaign_id: str) -> Campaign | None: ...

    def list_campaigns(
        self, limit: int = 50, status: CampaignStatus | None = None
    ) -> list[Campaign]: ...

    def append_campaign_audit(self, event: CampaignAuditEvent) -> None: ...

    def list_campaign_audit(
        self, campaign_id: str, limit: int = 100
    ) -> list[CampaignAuditEvent]: ...

    def append_touchpoint(self, event: TouchpointEvent) -> None: ...

    def save_identity_mapping(self, mapping: CampaignIdentityMapping) -> None: ...

    def get_identity_mapping(
        self, mapping_id: str
    ) -> CampaignIdentityMapping | None: ...

    def list_identity_mappings(
        self,
        *,
        source_system: IdentitySource | None = None,
        campaign_id: str | None = None,
        limit: int = 1000,
    ) -> list[CampaignIdentityMapping]: ...

    def save_attribution_quality_snapshot(
        self, snapshot: AttributionDataQualitySnapshot
    ) -> None: ...

    def list_attribution_quality_snapshots(
        self, limit: int = 50
    ) -> list[AttributionDataQualitySnapshot]: ...

    def save_attribution_intake_issue(self, issue: AttributionIntakeIssue) -> None: ...

    def get_attribution_intake_issue(
        self, issue_id: str
    ) -> AttributionIntakeIssue | None: ...

    def list_attribution_intake_issues(
        self, *, status: str | None = None, limit: int = 100
    ) -> list[AttributionIntakeIssue]: ...

    def save_attribution_delivery_receipt(
        self, receipt: AttributionDeliveryReceipt
    ) -> None: ...

    def get_attribution_delivery_receipt(
        self, receipt_id: str
    ) -> AttributionDeliveryReceipt | None: ...

    def list_attribution_delivery_receipts(
        self, *, producer: str | None = None, limit: int = 1000
    ) -> list[AttributionDeliveryReceipt]: ...

    def save_attribution_heartbeat_receipt(
        self, receipt: AttributionHeartbeatReceipt
    ) -> None: ...

    def get_attribution_heartbeat_receipt(
        self, receipt_id: str
    ) -> AttributionHeartbeatReceipt | None: ...

    def list_attribution_heartbeat_receipts(
        self, *, producer: str | None = None, limit: int = 1000
    ) -> list[AttributionHeartbeatReceipt]: ...

    def save_attribution_dead_letter(self, item: AttributionDeadLetter) -> None: ...

    def list_attribution_dead_letters(
        self, *, producer: str | None = None, limit: int = 1000
    ) -> list[AttributionDeadLetter]: ...

    def save_provider_health_snapshot(self, snapshot: ProviderHealthSnapshot) -> None: ...

    def list_provider_health_snapshots(
        self, limit: int = 50
    ) -> list[ProviderHealthSnapshot]: ...

    def save_provider_alert(self, alert: ProviderHealthAlert) -> None: ...

    def get_provider_alert(self, alert_id: str) -> ProviderHealthAlert | None: ...

    def list_provider_alerts(self, limit: int = 100) -> list[ProviderHealthAlert]: ...

    def save_provider_health_scheduler_status(
        self, status: ProviderHealthSchedulerStatus
    ) -> None: ...

    def get_provider_health_scheduler_status(
        self,
    ) -> ProviderHealthSchedulerStatus | None: ...

    def acquire_provider_health_scheduler_lease(
        self, owner: str, ttl_seconds: int
    ) -> bool: ...

    def release_provider_health_scheduler_lease(self, owner: str) -> None: ...

    def get_touchpoint(self, event_id: str) -> TouchpointEvent | None: ...

    def list_touchpoints(
        self,
        *,
        campaign_id: str | None = None,
        opportunity_id: str | None = None,
        lead_id: str | None = None,
        limit: int = 200,
    ) -> list[TouchpointEvent]: ...

    def save_attribution_reconciliation(
        self, reconciliation: AttributionReconciliation
    ) -> None: ...

    def get_attribution_reconciliation(
        self, reconciliation_id: str
    ) -> AttributionReconciliation | None: ...

    def list_attribution_reconciliations(
        self, limit: int = 50
    ) -> list[AttributionReconciliation]: ...

    def count_attribution_reconciliations(self) -> int: ...

    def append_attribution_audit(self, event: AttributionAuditEvent) -> None: ...

    def list_attribution_audit(
        self, limit: int = 100
    ) -> list[AttributionAuditEvent]: ...

    def save_experiment(self, experiment: Experiment) -> None: ...

    def get_experiment(self, experiment_id: str) -> Experiment | None: ...

    def list_experiments(
        self,
        limit: int = 50,
        campaign_id: str | None = None,
        status: ExperimentStatus | None = None,
    ) -> list[Experiment]: ...

    def append_experiment_audit(self, event: ExperimentAuditEvent) -> None: ...

    def list_experiment_audit(
        self, experiment_id: str, limit: int = 100
    ) -> list[ExperimentAuditEvent]: ...
