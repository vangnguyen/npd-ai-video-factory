from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from redis import Redis

from .attribution_models import (
    AttributionIntakeIssue,
    AttributionAuditEvent,
    AttributionDataQualitySnapshot,
    AttributionReconciliation,
    CampaignIdentityMapping,
    IdentitySource,
    TouchpointEvent,
)
from .campaign_models import Campaign, CampaignAuditEvent, CampaignStatus
from .config import HubSettings, settings as default_settings
from .experiment_models import Experiment, ExperimentAuditEvent, ExperimentStatus
from .models import AgentTask, AuditEvent, CommandCenterReport, ToolExecutionResult


class HubStore(Protocol):
    backend_name: str

    def health(self) -> bool: ...

    def save_task(self, task: AgentTask) -> None: ...

    def get_task(self, task_id: str) -> AgentTask | None: ...

    def save_report(self, report: CommandCenterReport) -> None: ...

    def get_report(self, task_id: str) -> CommandCenterReport | None: ...

    def append_execution(self, result: ToolExecutionResult) -> None: ...

    def list_executions(self, task_id: str, limit: int = 100) -> list[ToolExecutionResult]: ...

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

    def list_attribution_audit(self, limit: int = 100) -> list[AttributionAuditEvent]: ...

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


@dataclass
class MemoryHubStore:
    backend_name: str = "memory"
    tasks: dict[str, AgentTask] = field(default_factory=dict)
    reports: dict[str, CommandCenterReport] = field(default_factory=dict)
    executions: dict[str, list[ToolExecutionResult]] = field(default_factory=dict)
    audit: dict[str, list[AuditEvent]] = field(default_factory=dict)
    global_audit: list[AuditEvent] = field(default_factory=list)
    updated_at: dict[str, datetime] = field(default_factory=dict)
    campaigns: dict[str, Campaign] = field(default_factory=dict)
    campaign_updated_at: dict[str, datetime] = field(default_factory=dict)
    campaign_audit: dict[str, list[CampaignAuditEvent]] = field(default_factory=dict)
    touchpoints: dict[str, TouchpointEvent] = field(default_factory=dict)
    identity_mappings: dict[str, CampaignIdentityMapping] = field(default_factory=dict)
    attribution_quality_snapshots: dict[str, AttributionDataQualitySnapshot] = field(
        default_factory=dict
    )
    attribution_intake_issues: dict[str, AttributionIntakeIssue] = field(
        default_factory=dict
    )
    attribution_reconciliations: dict[str, AttributionReconciliation] = field(
        default_factory=dict
    )
    attribution_audit: list[AttributionAuditEvent] = field(default_factory=list)
    experiments: dict[str, Experiment] = field(default_factory=dict)
    experiment_updated_at: dict[str, datetime] = field(default_factory=dict)
    experiment_audit: dict[str, list[ExperimentAuditEvent]] = field(default_factory=dict)

    def _touch(self, task_id: str) -> None:
        self.updated_at[task_id] = datetime.now(timezone.utc)

    def health(self) -> bool:
        return True

    def save_task(self, task: AgentTask) -> None:
        self.tasks[task.task_id] = task.model_copy(deep=True)
        self._touch(task.task_id)

    def get_task(self, task_id: str) -> AgentTask | None:
        task = self.tasks.get(task_id)
        return task.model_copy(deep=True) if task is not None else None

    def save_report(self, report: CommandCenterReport) -> None:
        self.reports[report.task_id] = report.model_copy(deep=True)
        self._touch(report.task_id)

    def get_report(self, task_id: str) -> CommandCenterReport | None:
        report = self.reports.get(task_id)
        return report.model_copy(deep=True) if report is not None else None

    def append_execution(self, result: ToolExecutionResult) -> None:
        bucket = self.executions.setdefault(result.task_id, [])
        bucket.append(result.model_copy(deep=True))
        del bucket[:-1000]
        self._touch(result.task_id)

    def list_executions(self, task_id: str, limit: int = 100) -> list[ToolExecutionResult]:
        limit = max(1, min(limit, 1000))
        return [item.model_copy(deep=True) for item in self.executions.get(task_id, [])[-limit:]][::-1]

    def append_audit(self, event: AuditEvent) -> None:
        task_bucket = self.audit.setdefault(event.task_id, [])
        task_bucket.append(event.model_copy(deep=True))
        del task_bucket[:-2000]
        self.global_audit.append(event.model_copy(deep=True))
        del self.global_audit[:-5000]
        self._touch(event.task_id)

    def list_audit(self, task_id: str, limit: int = 100) -> list[AuditEvent]:
        limit = max(1, min(limit, 1000))
        return [item.model_copy(deep=True) for item in self.audit.get(task_id, [])[-limit:]][::-1]

    def list_recent_audit(self, limit: int = 100) -> list[AuditEvent]:
        limit = max(1, min(limit, 1000))
        return [item.model_copy(deep=True) for item in self.global_audit[-limit:]][::-1]

    def list_recent_tasks(self, limit: int = 50) -> list[tuple[str, datetime]]:
        limit = max(1, min(limit, 200))
        items = sorted(self.updated_at.items(), key=lambda item: item[1], reverse=True)
        return items[:limit]

    def save_campaign(self, campaign: Campaign) -> None:
        self.campaigns[campaign.campaign_id] = campaign.model_copy(deep=True)
        self.campaign_updated_at[campaign.campaign_id] = campaign.updated_at

    def get_campaign(self, campaign_id: str) -> Campaign | None:
        campaign = self.campaigns.get(campaign_id)
        return campaign.model_copy(deep=True) if campaign is not None else None

    def list_campaigns(
        self, limit: int = 50, status: CampaignStatus | None = None
    ) -> list[Campaign]:
        limit = max(1, min(limit, 1000))
        campaign_ids = sorted(
            self.campaign_updated_at,
            key=self.campaign_updated_at.__getitem__,
            reverse=True,
        )
        rows = [self.campaigns[campaign_id] for campaign_id in campaign_ids]
        if status is not None:
            rows = [campaign for campaign in rows if campaign.status == status]
        return [campaign.model_copy(deep=True) for campaign in rows[:limit]]

    def append_campaign_audit(self, event: CampaignAuditEvent) -> None:
        bucket = self.campaign_audit.setdefault(event.campaign_id, [])
        bucket.append(event.model_copy(deep=True))
        del bucket[:-2000]

    def list_campaign_audit(
        self, campaign_id: str, limit: int = 100
    ) -> list[CampaignAuditEvent]:
        limit = max(1, min(limit, 1000))
        return [
            event.model_copy(deep=True)
            for event in self.campaign_audit.get(campaign_id, [])[-limit:]
        ][::-1]

    def append_touchpoint(self, event: TouchpointEvent) -> None:
        if event.event_id in self.touchpoints:
            raise ValueError("touchpoint event_id already exists")
        self.touchpoints[event.event_id] = event.model_copy(deep=True)

    def save_identity_mapping(self, mapping: CampaignIdentityMapping) -> None:
        if mapping.mapping_id in self.identity_mappings:
            raise ValueError("identity mapping_id already exists")
        self.identity_mappings[mapping.mapping_id] = mapping.model_copy(deep=True)

    def get_identity_mapping(
        self, mapping_id: str
    ) -> CampaignIdentityMapping | None:
        row = self.identity_mappings.get(mapping_id)
        return row.model_copy(deep=True) if row is not None else None

    def list_identity_mappings(
        self,
        *,
        source_system: IdentitySource | None = None,
        campaign_id: str | None = None,
        limit: int = 1000,
    ) -> list[CampaignIdentityMapping]:
        limit = max(1, min(limit, 5000))
        rows = sorted(
            self.identity_mappings.values(), key=lambda item: item.created_at, reverse=True
        )
        if source_system is not None:
            rows = [item for item in rows if item.source_system == source_system]
        if campaign_id is not None:
            rows = [item for item in rows if item.campaign_id == campaign_id]
        return [item.model_copy(deep=True) for item in rows[:limit]]

    def save_attribution_quality_snapshot(
        self, snapshot: AttributionDataQualitySnapshot
    ) -> None:
        self.attribution_quality_snapshots[snapshot.snapshot_id] = snapshot.model_copy(
            deep=True
        )

    def list_attribution_quality_snapshots(
        self, limit: int = 50
    ) -> list[AttributionDataQualitySnapshot]:
        limit = max(1, min(limit, 1000))
        rows = sorted(
            self.attribution_quality_snapshots.values(),
            key=lambda item: item.created_at,
            reverse=True,
        )
        return [item.model_copy(deep=True) for item in rows[:limit]]

    def save_attribution_intake_issue(self, issue: AttributionIntakeIssue) -> None:
        self.attribution_intake_issues[issue.issue_id] = issue.model_copy(deep=True)

    def get_attribution_intake_issue(
        self, issue_id: str
    ) -> AttributionIntakeIssue | None:
        issue = self.attribution_intake_issues.get(issue_id)
        return issue.model_copy(deep=True) if issue is not None else None

    def list_attribution_intake_issues(
        self, *, status: str | None = None, limit: int = 100
    ) -> list[AttributionIntakeIssue]:
        limit = max(1, min(limit, 1000))
        rows = sorted(
            self.attribution_intake_issues.values(),
            key=lambda item: item.last_seen_at,
            reverse=True,
        )
        if status is not None:
            rows = [item for item in rows if item.status.value == status]
        return [item.model_copy(deep=True) for item in rows[:limit]]

    def get_touchpoint(self, event_id: str) -> TouchpointEvent | None:
        event = self.touchpoints.get(event_id)
        return event.model_copy(deep=True) if event is not None else None

    def list_touchpoints(
        self,
        *,
        campaign_id: str | None = None,
        opportunity_id: str | None = None,
        lead_id: str | None = None,
        limit: int = 200,
    ) -> list[TouchpointEvent]:
        limit = max(1, min(limit, 5000))
        rows = list(self.touchpoints.values())
        if campaign_id is not None:
            rows = [item for item in rows if item.campaign_id == campaign_id]
        if opportunity_id is not None:
            rows = [item for item in rows if item.opportunity_id == opportunity_id]
        if lead_id is not None:
            rows = [item for item in rows if item.lead_id == lead_id]
        rows.sort(key=lambda item: (item.occurred_at, item.event_id), reverse=True)
        return [item.model_copy(deep=True) for item in rows[:limit]]

    def save_attribution_reconciliation(
        self, reconciliation: AttributionReconciliation
    ) -> None:
        self.attribution_reconciliations[reconciliation.reconciliation_id] = (
            reconciliation.model_copy(deep=True)
        )

    def get_attribution_reconciliation(
        self, reconciliation_id: str
    ) -> AttributionReconciliation | None:
        row = self.attribution_reconciliations.get(reconciliation_id)
        return row.model_copy(deep=True) if row is not None else None

    def list_attribution_reconciliations(
        self, limit: int = 50
    ) -> list[AttributionReconciliation]:
        limit = max(1, min(limit, 1000))
        rows = sorted(
            self.attribution_reconciliations.values(),
            key=lambda item: item.created_at,
            reverse=True,
        )
        return [item.model_copy(deep=True) for item in rows[:limit]]

    def count_attribution_reconciliations(self) -> int:
        return len(self.attribution_reconciliations)

    def append_attribution_audit(self, event: AttributionAuditEvent) -> None:
        self.attribution_audit.append(event.model_copy(deep=True))
        del self.attribution_audit[:-5000]

    def list_attribution_audit(self, limit: int = 100) -> list[AttributionAuditEvent]:
        limit = max(1, min(limit, 1000))
        return [item.model_copy(deep=True) for item in self.attribution_audit[-limit:]][::-1]

    def save_experiment(self, experiment: Experiment) -> None:
        self.experiments[experiment.experiment_id] = experiment.model_copy(deep=True)
        self.experiment_updated_at[experiment.experiment_id] = experiment.updated_at

    def get_experiment(self, experiment_id: str) -> Experiment | None:
        experiment = self.experiments.get(experiment_id)
        return experiment.model_copy(deep=True) if experiment is not None else None

    def list_experiments(
        self,
        limit: int = 50,
        campaign_id: str | None = None,
        status: ExperimentStatus | None = None,
    ) -> list[Experiment]:
        limit = max(1, min(limit, 1000))
        ids = sorted(
            self.experiment_updated_at,
            key=self.experiment_updated_at.__getitem__,
            reverse=True,
        )
        rows = [self.experiments[item] for item in ids]
        if campaign_id is not None:
            rows = [item for item in rows if item.campaign_id == campaign_id]
        if status is not None:
            rows = [item for item in rows if item.status == status]
        return [item.model_copy(deep=True) for item in rows[:limit]]

    def append_experiment_audit(self, event: ExperimentAuditEvent) -> None:
        bucket = self.experiment_audit.setdefault(event.experiment_id, [])
        bucket.append(event.model_copy(deep=True))
        del bucket[:-2000]

    def list_experiment_audit(
        self, experiment_id: str, limit: int = 100
    ) -> list[ExperimentAuditEvent]:
        limit = max(1, min(limit, 1000))
        return [
            item.model_copy(deep=True)
            for item in self.experiment_audit.get(experiment_id, [])[-limit:]
        ][::-1]


class RedisHubStore:
    backend_name = "redis"

    def __init__(
        self,
        *,
        redis_url: str | None = None,
        namespace: str | None = None,
        client: Redis | None = None,
    ) -> None:
        self.namespace = (namespace or default_settings.store_namespace).strip(":")
        self.redis = client or Redis.from_url(
            redis_url or default_settings.agent_redis_url,
            decode_responses=True,
        )

    def _key(self, *parts: str) -> str:
        return ":".join((self.namespace, *parts))

    def _touch(self, task_id: str) -> None:
        self.redis.zadd(
            self._key("tasks"),
            {task_id: datetime.now(timezone.utc).timestamp()},
        )

    def health(self) -> bool:
        return bool(self.redis.ping())

    def save_task(self, task: AgentTask) -> None:
        pipe = self.redis.pipeline()
        pipe.set(self._key("task", task.task_id), task.model_dump_json())
        pipe.zadd(self._key("tasks"), {task.task_id: datetime.now(timezone.utc).timestamp()})
        pipe.execute()

    def get_task(self, task_id: str) -> AgentTask | None:
        raw = self.redis.get(self._key("task", task_id))
        return AgentTask.model_validate_json(raw) if raw else None

    def save_report(self, report: CommandCenterReport) -> None:
        pipe = self.redis.pipeline()
        pipe.set(self._key("report", report.task_id), report.model_dump_json())
        pipe.zadd(self._key("tasks"), {report.task_id: datetime.now(timezone.utc).timestamp()})
        pipe.execute()

    def get_report(self, task_id: str) -> CommandCenterReport | None:
        raw = self.redis.get(self._key("report", task_id))
        return CommandCenterReport.model_validate_json(raw) if raw else None

    def append_execution(self, result: ToolExecutionResult) -> None:
        key = self._key("executions", result.task_id)
        pipe = self.redis.pipeline()
        pipe.rpush(key, result.model_dump_json())
        pipe.ltrim(key, -1000, -1)
        pipe.zadd(self._key("tasks"), {result.task_id: datetime.now(timezone.utc).timestamp()})
        pipe.execute()

    def list_executions(self, task_id: str, limit: int = 100) -> list[ToolExecutionResult]:
        limit = max(1, min(limit, 1000))
        rows = self.redis.lrange(self._key("executions", task_id), -limit, -1)
        return [ToolExecutionResult.model_validate_json(raw) for raw in reversed(rows)]

    def append_audit(self, event: AuditEvent) -> None:
        raw = event.model_dump_json()
        task_key = self._key("audit", event.task_id)
        global_key = self._key("audit", "global")
        pipe = self.redis.pipeline()
        pipe.rpush(task_key, raw)
        pipe.ltrim(task_key, -2000, -1)
        pipe.rpush(global_key, raw)
        pipe.ltrim(global_key, -5000, -1)
        pipe.zadd(self._key("tasks"), {event.task_id: event.created_at.timestamp()})
        pipe.execute()

    def list_audit(self, task_id: str, limit: int = 100) -> list[AuditEvent]:
        limit = max(1, min(limit, 1000))
        rows = self.redis.lrange(self._key("audit", task_id), -limit, -1)
        return [AuditEvent.model_validate_json(raw) for raw in reversed(rows)]

    def list_recent_audit(self, limit: int = 100) -> list[AuditEvent]:
        limit = max(1, min(limit, 1000))
        rows = self.redis.lrange(self._key("audit", "global"), -limit, -1)
        return [AuditEvent.model_validate_json(raw) for raw in reversed(rows)]

    def list_recent_tasks(self, limit: int = 50) -> list[tuple[str, datetime]]:
        limit = max(1, min(limit, 200))
        rows = self.redis.zrevrange(self._key("tasks"), 0, limit - 1, withscores=True)
        return [
            (str(task_id), datetime.fromtimestamp(float(score), tz=timezone.utc))
            for task_id, score in rows
        ]

    def save_campaign(self, campaign: Campaign) -> None:
        pipe = self.redis.pipeline()
        pipe.set(
            self._key("campaign-os", "campaign", campaign.campaign_id),
            campaign.model_dump_json(),
        )
        pipe.zadd(
            self._key("campaign-os", "campaigns"),
            {campaign.campaign_id: campaign.updated_at.timestamp()},
        )
        pipe.execute()

    def get_campaign(self, campaign_id: str) -> Campaign | None:
        raw = self.redis.get(self._key("campaign-os", "campaign", campaign_id))
        return Campaign.model_validate_json(raw) if raw else None

    def list_campaigns(
        self, limit: int = 50, status: CampaignStatus | None = None
    ) -> list[Campaign]:
        limit = max(1, min(limit, 1000))
        # Read a bounded superset so a status filter remains useful without a
        # second global index. Campaign OS stays in its own Redis subnamespace.
        rows = self.redis.zrevrange(
            self._key("campaign-os", "campaigns"), 0, max(limit * 5, limit) - 1
        )
        campaigns = [self.get_campaign(str(campaign_id)) for campaign_id in rows]
        filtered = [campaign for campaign in campaigns if campaign is not None]
        if status is not None:
            filtered = [campaign for campaign in filtered if campaign.status == status]
        return filtered[:limit]

    def append_campaign_audit(self, event: CampaignAuditEvent) -> None:
        key = self._key("campaign-os", "audit", event.campaign_id)
        pipe = self.redis.pipeline()
        pipe.rpush(key, event.model_dump_json())
        pipe.ltrim(key, -2000, -1)
        pipe.execute()

    def list_campaign_audit(
        self, campaign_id: str, limit: int = 100
    ) -> list[CampaignAuditEvent]:
        limit = max(1, min(limit, 1000))
        rows = self.redis.lrange(
            self._key("campaign-os", "audit", campaign_id), -limit, -1
        )
        return [CampaignAuditEvent.model_validate_json(raw) for raw in reversed(rows)]

    def append_touchpoint(self, event: TouchpointEvent) -> None:
        event_key = self._key("attribution-os", "touchpoint", event.event_id)
        if not self.redis.set(event_key, event.model_dump_json(), nx=True):
            raise ValueError("touchpoint event_id already exists")
        score = event.occurred_at.timestamp()
        pipe = self.redis.pipeline()
        pipe.zadd(self._key("attribution-os", "touchpoints"), {event.event_id: score})
        pipe.zadd(
            self._key("attribution-os", "campaign", event.campaign_id, "touchpoints"),
            {event.event_id: score},
        )
        if event.opportunity_id:
            pipe.zadd(
                self._key(
                    "attribution-os", "opportunity", event.opportunity_id, "touchpoints"
                ),
                {event.event_id: score},
            )
        if event.lead_id:
            pipe.zadd(
                self._key("attribution-os", "lead", event.lead_id, "touchpoints"),
                {event.event_id: score},
            )
        pipe.execute()

    def save_identity_mapping(self, mapping: CampaignIdentityMapping) -> None:
        mapping_key = self._key(
            "attribution-os", "identity-mapping", mapping.mapping_id
        )
        if not self.redis.set(mapping_key, mapping.model_dump_json(), nx=True):
            raise ValueError("identity mapping_id already exists")
        self.redis.zadd(
            self._key("attribution-os", "identity-mappings"),
            {mapping.mapping_id: mapping.created_at.timestamp()},
        )

    def get_identity_mapping(
        self, mapping_id: str
    ) -> CampaignIdentityMapping | None:
        raw = self.redis.get(
            self._key("attribution-os", "identity-mapping", mapping_id)
        )
        return CampaignIdentityMapping.model_validate_json(raw) if raw else None

    def list_identity_mappings(
        self,
        *,
        source_system: IdentitySource | None = None,
        campaign_id: str | None = None,
        limit: int = 1000,
    ) -> list[CampaignIdentityMapping]:
        limit = max(1, min(limit, 5000))
        ids = self.redis.zrevrange(
            self._key("attribution-os", "identity-mappings"), 0, 4999
        )
        rows = [self.get_identity_mapping(str(item)) for item in ids]
        filtered = [item for item in rows if item is not None]
        if source_system is not None:
            filtered = [item for item in filtered if item.source_system == source_system]
        if campaign_id is not None:
            filtered = [item for item in filtered if item.campaign_id == campaign_id]
        return filtered[:limit]

    def save_attribution_quality_snapshot(
        self, snapshot: AttributionDataQualitySnapshot
    ) -> None:
        pipe = self.redis.pipeline()
        pipe.set(
            self._key("attribution-os", "data-quality", snapshot.snapshot_id),
            snapshot.model_dump_json(),
        )
        pipe.zadd(
            self._key("attribution-os", "data-quality-snapshots"),
            {snapshot.snapshot_id: snapshot.created_at.timestamp()},
        )
        pipe.execute()

    def list_attribution_quality_snapshots(
        self, limit: int = 50
    ) -> list[AttributionDataQualitySnapshot]:
        limit = max(1, min(limit, 1000))
        ids = self.redis.zrevrange(
            self._key("attribution-os", "data-quality-snapshots"), 0, limit - 1
        )
        rows: list[AttributionDataQualitySnapshot] = []
        for snapshot_id in ids:
            raw = self.redis.get(
                self._key("attribution-os", "data-quality", str(snapshot_id))
            )
            if raw:
                rows.append(AttributionDataQualitySnapshot.model_validate_json(raw))
        return rows

    def save_attribution_intake_issue(self, issue: AttributionIntakeIssue) -> None:
        pipe = self.redis.pipeline()
        pipe.set(
            self._key("attribution-os", "intake-issue", issue.issue_id),
            issue.model_dump_json(),
        )
        pipe.zadd(
            self._key("attribution-os", "intake-issues"),
            {issue.issue_id: issue.last_seen_at.timestamp()},
        )
        pipe.execute()

    def get_attribution_intake_issue(
        self, issue_id: str
    ) -> AttributionIntakeIssue | None:
        raw = self.redis.get(
            self._key("attribution-os", "intake-issue", issue_id)
        )
        return AttributionIntakeIssue.model_validate_json(raw) if raw else None

    def list_attribution_intake_issues(
        self, *, status: str | None = None, limit: int = 100
    ) -> list[AttributionIntakeIssue]:
        limit = max(1, min(limit, 1000))
        ids = self.redis.zrevrange(
            self._key("attribution-os", "intake-issues"), 0, 4999
        )
        rows = [self.get_attribution_intake_issue(str(item)) for item in ids]
        filtered = [item for item in rows if item is not None]
        if status is not None:
            filtered = [item for item in filtered if item.status.value == status]
        return filtered[:limit]

    def get_touchpoint(self, event_id: str) -> TouchpointEvent | None:
        raw = self.redis.get(self._key("attribution-os", "touchpoint", event_id))
        return TouchpointEvent.model_validate_json(raw) if raw else None

    def list_touchpoints(
        self,
        *,
        campaign_id: str | None = None,
        opportunity_id: str | None = None,
        lead_id: str | None = None,
        limit: int = 200,
    ) -> list[TouchpointEvent]:
        limit = max(1, min(limit, 5000))
        if opportunity_id is not None:
            key = self._key(
                "attribution-os", "opportunity", opportunity_id, "touchpoints"
            )
        elif lead_id is not None:
            key = self._key("attribution-os", "lead", lead_id, "touchpoints")
        elif campaign_id is not None:
            key = self._key(
                "attribution-os", "campaign", campaign_id, "touchpoints"
            )
        else:
            key = self._key("attribution-os", "touchpoints")
        event_ids = self.redis.zrevrange(key, 0, limit - 1)
        rows = [self.get_touchpoint(str(event_id)) for event_id in event_ids]
        filtered = [item for item in rows if item is not None]
        if campaign_id is not None:
            filtered = [item for item in filtered if item.campaign_id == campaign_id]
        if opportunity_id is not None:
            filtered = [item for item in filtered if item.opportunity_id == opportunity_id]
        if lead_id is not None:
            filtered = [item for item in filtered if item.lead_id == lead_id]
        return filtered[:limit]

    def save_attribution_reconciliation(
        self, reconciliation: AttributionReconciliation
    ) -> None:
        pipe = self.redis.pipeline()
        pipe.set(
            self._key(
                "attribution-os", "reconciliation", reconciliation.reconciliation_id
            ),
            reconciliation.model_dump_json(),
        )
        pipe.zadd(
            self._key("attribution-os", "reconciliations"),
            {reconciliation.reconciliation_id: reconciliation.created_at.timestamp()},
        )
        pipe.execute()

    def get_attribution_reconciliation(
        self, reconciliation_id: str
    ) -> AttributionReconciliation | None:
        raw = self.redis.get(
            self._key("attribution-os", "reconciliation", reconciliation_id)
        )
        return AttributionReconciliation.model_validate_json(raw) if raw else None

    def list_attribution_reconciliations(
        self, limit: int = 50
    ) -> list[AttributionReconciliation]:
        limit = max(1, min(limit, 1000))
        ids = self.redis.zrevrange(
            self._key("attribution-os", "reconciliations"), 0, limit - 1
        )
        rows = [self.get_attribution_reconciliation(str(item)) for item in ids]
        return [item for item in rows if item is not None]

    def count_attribution_reconciliations(self) -> int:
        return int(self.redis.zcard(self._key("attribution-os", "reconciliations")))

    def append_attribution_audit(self, event: AttributionAuditEvent) -> None:
        key = self._key("attribution-os", "audit")
        pipe = self.redis.pipeline()
        pipe.rpush(key, event.model_dump_json())
        pipe.ltrim(key, -5000, -1)
        pipe.execute()

    def list_attribution_audit(self, limit: int = 100) -> list[AttributionAuditEvent]:
        limit = max(1, min(limit, 1000))
        rows = self.redis.lrange(
            self._key("attribution-os", "audit"), -limit, -1
        )
        return [AttributionAuditEvent.model_validate_json(raw) for raw in reversed(rows)]

    def save_experiment(self, experiment: Experiment) -> None:
        pipe = self.redis.pipeline()
        pipe.set(
            self._key("experiment-os", "experiment", experiment.experiment_id),
            experiment.model_dump_json(),
        )
        pipe.zadd(
            self._key("experiment-os", "experiments"),
            {experiment.experiment_id: experiment.updated_at.timestamp()},
        )
        pipe.zadd(
            self._key("experiment-os", "campaign", experiment.campaign_id, "experiments"),
            {experiment.experiment_id: experiment.updated_at.timestamp()},
        )
        pipe.execute()

    def get_experiment(self, experiment_id: str) -> Experiment | None:
        raw = self.redis.get(
            self._key("experiment-os", "experiment", experiment_id)
        )
        return Experiment.model_validate_json(raw) if raw else None

    def list_experiments(
        self,
        limit: int = 50,
        campaign_id: str | None = None,
        status: ExperimentStatus | None = None,
    ) -> list[Experiment]:
        limit = max(1, min(limit, 1000))
        key = (
            self._key("experiment-os", "campaign", campaign_id, "experiments")
            if campaign_id is not None
            else self._key("experiment-os", "experiments")
        )
        ids = self.redis.zrevrange(key, 0, max(limit * 5, limit) - 1)
        rows = [self.get_experiment(str(item)) for item in ids]
        filtered = [item for item in rows if item is not None]
        if status is not None:
            filtered = [item for item in filtered if item.status == status]
        return filtered[:limit]

    def append_experiment_audit(self, event: ExperimentAuditEvent) -> None:
        key = self._key("experiment-os", "audit", event.experiment_id)
        pipe = self.redis.pipeline()
        pipe.rpush(key, event.model_dump_json())
        pipe.ltrim(key, -2000, -1)
        pipe.execute()

    def list_experiment_audit(
        self, experiment_id: str, limit: int = 100
    ) -> list[ExperimentAuditEvent]:
        limit = max(1, min(limit, 1000))
        rows = self.redis.lrange(
            self._key("experiment-os", "audit", experiment_id), -limit, -1
        )
        return [ExperimentAuditEvent.model_validate_json(raw) for raw in reversed(rows)]


def build_store(settings: HubSettings | None = None) -> HubStore:
    cfg = settings or default_settings
    backend = cfg.store_backend.casefold()
    if backend == "memory":
        return MemoryHubStore()
    if backend == "redis":
        return RedisHubStore(
            redis_url=cfg.agent_redis_url,
            namespace=cfg.store_namespace,
        )
    raise ValueError(f"unsupported AGENT_STORE_BACKEND={cfg.store_backend}")
