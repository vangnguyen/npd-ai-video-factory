from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from .config import HubSettings, settings as default_settings
from .models import ActionStatus, AgentTask, ExecutionStatus, PlannedAction, ToolExecutionResult


N8N_WRITE_TOOLS = {
    "ads.budget.update",
    "social.publish",
    "sales.contact.send",
    "crm.records.update",
}


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
    ) -> None:
        self.settings = settings or default_settings
        self.transport = transport

    async def execute(self, *, task: AgentTask, action: PlannedAction) -> ToolExecutionResult:
        try:
            if action.tool == "video.jobs.create":
                data = await self._create_video_job(task, action)
            elif action.tool == "crm.leads.read":
                data = await self._read_crm_leads(task)
            elif action.tool == "crm.audit.read":
                data = await self._audit_crm(task)
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
        return await self._espo_get(
            "Lead",
            {
                "maxSize": max_size,
                "orderBy": "modifiedAt",
                "order": "desc",
            },
        )

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
            if not record.get("emailAddress") and not record.get("phoneNumber"):
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
