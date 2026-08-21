from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from redis import Redis

from .config import HubSettings, settings as default_settings
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


@dataclass
class MemoryHubStore:
    backend_name: str = "memory"
    tasks: dict[str, AgentTask] = field(default_factory=dict)
    reports: dict[str, CommandCenterReport] = field(default_factory=dict)
    executions: dict[str, list[ToolExecutionResult]] = field(default_factory=dict)
    audit: dict[str, list[AuditEvent]] = field(default_factory=dict)
    global_audit: list[AuditEvent] = field(default_factory=list)
    updated_at: dict[str, datetime] = field(default_factory=dict)

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
