from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from collections.abc import Callable
from typing import Any

import httpx

from .config import HubSettings, settings as default_settings
from .marketing_sources import MarketingSourceReader
from .models import ActionStatus, AgentTask, ExecutionStatus, PlannedAction, ToolExecutionResult
from .tool_registry import AUTO_READ_TOOLS, N8N_WRITE_TOOLS

CRM_LEAD_SAFE_FIELDS = (
    "id",
    "name",
    "status",
    "assignedUserId",
    "assignedUserName",
    "createdAt",
    "modifiedAt",
    "streamUpdatedAt",
    "cMucDoQuanTam",
    "cThoiGianLienHeMongMuon",
    "cDiemLead",
    "cDaDongYMarketing",
    "source",
    "emailAddress",
    "phoneNumber",
    "cDuAnQuanTam",
)

CRM_LEAD_PERSISTED_FIELDS = set(CRM_LEAD_SAFE_FIELDS) - {"emailAddress", "phoneNumber"}


class ToolExecutionError(RuntimeError):
    pass


class ToolNotConfigured(ToolExecutionError):
    pass


class ToolNotSupported(ToolExecutionError):
    pass


class ToolExecutor:
    """Execute a narrow allowlist of Agent Hub tools.

    External write actions are never sent directly to arbitrary destinations.
    They go only to the single configured n8n executor webhook and only after
    the corresponding action is approved.
    """

    def __init__(
        self,
        settings: HubSettings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        ga4_token_provider: Callable[[], str] | None = None,
    ) -> None:
        self.settings = settings or default_settings
        self.transport = transport
        self.marketing_sources = MarketingSourceReader(
            self.settings,
            transport=transport,
            ga4_token_provider=ga4_token_provider,
        )

    async def execute(self, *, task: AgentTask, action: PlannedAction) -> ToolExecutionResult:
        try:
            if action.tool == "video.jobs.create":
                data = await self._create_video_job(task, action)
            elif action.tool == "crm.leads.read":
                data = await self._read_crm_leads(task)
            elif action.tool == "crm.audit.read":
                data = await self._audit_crm(task)
            elif action.tool == "analytics.read":
                data = await self._read_analytics(task)
            elif action.tool in N8N_WRITE_TOOLS:
                data = await self._execute_n8n(task, action)
            else:
                raise ToolNotSupported(f"tool is not executable in Phase 2: {action.tool}")
        except ToolExecutionError as exc:
            return ToolExecutionResult(
                task_id=task.task_id,
                action_id=action.action_id,
                tool=action.tool,
                status=ExecutionStatus.FAILED,
                detail=str(exc),
            )

        external_id = None
        if isinstance(data, dict):
            raw_external_id = data.get("job_id") or data.get("execution_id") or data.get("id")
            if raw_external_id is not None:
                external_id = str(raw_external_id)
        return ToolExecutionResult(
            task_id=task.task_id,
            action_id=action.action_id,
            tool=action.tool,
            status=ExecutionStatus.SUCCEEDED,
            external_id=external_id,
            data=data if isinstance(data, dict) else {"result": data},
        )

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self.settings.request_timeout_seconds,
            transport=self.transport,
        )

    async def _create_video_job(self, task: AgentTask, action: PlannedAction) -> dict[str, Any]:
        video_job = action.payload.get("video_job") or task.context.get("video_job")
        if not isinstance(video_job, dict):
            raise ToolExecutionError(
                "video.jobs.create requires context.video_job with the existing VideoJobCreate contract"
            )
        if not self.settings.video_api_url:
            raise ToolNotConfigured("VIDEO_API_URL is not configured")

        headers = {"Idempotency-Key": f"agent-{task.task_id}-{action.action_id}"}
        async with self._client() as client:
            try:
                response = await client.post(
                    f"{self.settings.video_api_url}/api/v1/video-jobs",
                    json=video_job,
                    headers=headers,
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise ToolExecutionError(f"video API request failed: {exc}") from exc
        payload = response.json()
        if not isinstance(payload, dict) or not payload.get("job_id"):
            raise ToolExecutionError("video API returned an invalid job response")
        return payload

    def _espo_headers(self) -> dict[str, str]:
        if not self.settings.espocrm_url or not self.settings.espocrm_api_key:
            raise ToolNotConfigured("ESPOCRM_URL and ESPOCRM_API_KEY are required for CRM reads")
        return {"X-Api-Key": self.settings.espocrm_api_key}

    async def _espo_get(self, entity: str, params: dict[str, Any]) -> dict[str, Any]:
        headers = self._espo_headers()
        async with self._client() as client:
            try:
                response = await client.get(
                    f"{self.settings.espocrm_url}/api/v1/{entity}",
                    params=params,
                    headers=headers,
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise ToolExecutionError(f"EspoCRM read failed: {exc}") from exc
        payload = response.json()
        if not isinstance(payload, dict):
            raise ToolExecutionError("EspoCRM returned a non-object response")
        return payload

    async def _read_crm_leads(self, task: AgentTask) -> dict[str, Any]:
        requested_size = task.context.get("crm_max_size", 50)
        try:
            max_size = max(1, min(int(requested_size), 200))
        except (TypeError, ValueError):
            max_size = 50
        payload = await self._espo_get(
            "Lead",
            {
                "maxSize": max_size,
                "orderBy": "modifiedAt",
                "order": "desc",
                "select": ",".join(CRM_LEAD_SAFE_FIELDS),
            },
        )
        records = payload.get("list")
        if not isinstance(records, list):
            records = []
        sanitized_records = []
        for record in records:
            if not isinstance(record, dict):
                continue
            sanitized = {
                field: record.get(field)
                for field in CRM_LEAD_PERSISTED_FIELDS
                if field in record
            }
            sanitized["hasEmail"] = bool(record.get("emailAddress"))
            sanitized["hasPhone"] = bool(record.get("phoneNumber"))
            sanitized_records.append(sanitized)
        return {
            "total": payload.get("total", len(sanitized_records)),
            "list": sanitized_records,
        }

    async def _audit_crm(self, task: AgentTask) -> dict[str, Any]:
        payload = await self._read_crm_leads(task)
        records = payload.get("list")
        if not isinstance(records, list):
            records = []

        missing_contact = 0
        unassigned = 0
        stale = 0
        now = datetime.now(timezone.utc)
        stale_days = task.context.get("crm_stale_days", 7)
        try:
            stale_days = max(1, min(int(stale_days), 365))
        except (TypeError, ValueError):
            stale_days = 7

        for record in records:
            if not isinstance(record, dict):
                continue
            if not record.get("hasEmail") and not record.get("hasPhone"):
                missing_contact += 1
            if not record.get("assignedUserId"):
                unassigned += 1
            raw_modified = record.get("modifiedAt")
            if isinstance(raw_modified, str):
                try:
                    modified = datetime.strptime(raw_modified, "%Y-%m-%d %H:%M:%S").replace(
                        tzinfo=timezone.utc
                    )
                    if (now - modified).days >= stale_days:
                        stale += 1
                except ValueError:
                    pass

        return {
            "returned_records": len(records),
            "reported_total": payload.get("total"),
            "missing_contact": missing_contact,
            "unassigned": unassigned,
            "stale": stale,
            "stale_days": stale_days,
            "records": records,
        }

    @staticmethod
    def _analytics_period_days(task: AgentTask) -> int:
        configured = task.context.get("analytics_days")
        if configured is not None:
            try:
                return max(1, min(int(configured), 365))
            except (TypeError, ValueError):
                pass
        match = re.search(r"(\d{1,3})\s*ngày", task.objective.casefold())
        if match:
            return max(1, min(int(match.group(1)), 365))
        return 30

    @staticmethod
    def _parse_espo_datetime(value: object) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        normalized = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _distribution(records: list[dict[str, Any]], field: str) -> list[dict[str, object]]:
        counts = Counter(str(record.get(field) or "Chưa xác định") for record in records)
        total = len(records)
        return [
            {
                "name": name,
                "count": count,
                "share_pct": round(count * 100 / total, 1) if total else 0.0,
            }
            for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        ]

    async def _read_analytics(self, task: AgentTask) -> dict[str, Any]:
        crm_error = ""
        try:
            payload = await self._read_crm_leads(task)
        except ToolExecutionError as exc:
            payload = {"total": None, "list": []}
            crm_error = str(exc)
        raw_records = payload.get("list")
        records = [record for record in raw_records or [] if isinstance(record, dict)]
        now = datetime.now(timezone.utc)
        period_days = self._analytics_period_days(task)
        recent_cutoff = now.timestamp() - period_days * 86400

        recent_leads = 0
        stale_active_leads = 0
        active_statuses = {"New", "Assigned", "In Process", "Recycled"}
        for record in records:
            created = self._parse_espo_datetime(record.get("createdAt"))
            if created and created.timestamp() >= recent_cutoff:
                recent_leads += 1
            modified = (
                self._parse_espo_datetime(record.get("streamUpdatedAt"))
                or self._parse_espo_datetime(record.get("modifiedAt"))
                or created
            )
            if (
                record.get("status") in active_statuses
                and modified
                and (now - modified).total_seconds() >= 86400
            ):
                stale_active_leads += 1

        converted = sum(record.get("status") == "Converted" for record in records)
        assigned = sum(bool(record.get("assignedUserId")) for record in records)
        contactable = sum(
            bool(record.get("hasEmail") or record.get("hasPhone")) for record in records
        )
        reported_total = payload.get("total")
        try:
            coverage_complete = int(reported_total) <= len(records)
        except (TypeError, ValueError):
            coverage_complete = True

        external = await self.marketing_sources.read_all(period_days=period_days)
        if crm_error:
            external["source_status"]["crm"] = "failed"
            external["source_errors"]["crm"] = crm_error
            external["available_sources"] = [
                source for source in external["available_sources"] if source != "crm"
            ]
            external["missing_sources"] = list(
                dict.fromkeys([*external["missing_sources"], "crm"])
            )
        return {
            "data_source": "EspoCRM Lead plus configured read-only marketing sources",
            "period_days": period_days,
            "records_analyzed": len(records),
            "reported_total": reported_total,
            "coverage_complete": coverage_complete,
            "recent_leads": recent_leads,
            "converted_leads": converted,
            "conversion_rate_pct": round(converted * 100 / len(records), 1) if records else 0.0,
            "assigned_leads": assigned,
            "contactable_leads": contactable,
            "stale_active_leads": stale_active_leads,
            "by_status": self._distribution(records, "status"),
            "by_source": self._distribution(records, "source"),
            "by_project": self._distribution(records, "cDuAnQuanTam"),
            "by_interest": self._distribution(records, "cMucDoQuanTam"),
            "period_start": external["period_start"],
            "period_end": external["period_end"],
            "source_status": external["source_status"],
            "available_sources": external["available_sources"],
            "missing_sources": external["missing_sources"],
            "source_errors": external["source_errors"],
            "external_sources": external["sources"],
            "generated_at": now.isoformat(),
        }

    async def _execute_n8n(self, task: AgentTask, action: PlannedAction) -> dict[str, Any]:
        if action.status != ActionStatus.APPROVED:
            raise ToolExecutionError("write action must be approved before n8n execution")
        if not self.settings.n8n_executor_webhook_url:
            raise ToolNotConfigured("N8N_AGENT_EXECUTOR_WEBHOOK_URL is not configured")

        envelope = {
            "task_id": task.task_id,
            "objective": task.objective,
            "action": action.model_dump(mode="json"),
        }
        async with self._client() as client:
            try:
                response = await client.post(self.settings.n8n_executor_webhook_url, json=envelope)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise ToolExecutionError(f"n8n executor request failed: {exc}") from exc

        if not response.content:
            return {"accepted": True}
        try:
            payload = response.json()
        except ValueError:
            return {"accepted": True, "response_text": response.text[:1000]}
        return payload if isinstance(payload, dict) else {"accepted": True, "result": payload}
