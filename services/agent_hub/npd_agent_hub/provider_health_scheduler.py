from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable

from .config import HubSettings, settings as default_settings
from .provider_health import ProviderHealthService
from .provider_health_models import (
    ProviderHealthSchedulerState,
    ProviderHealthSchedulerStatus,
)
from .store import HubStore


class ProviderHealthScheduler:
    """Lease-guarded internal evaluation loop; it never probes or writes providers."""

    def __init__(
        self,
        store: HubStore,
        provider_health: ProviderHealthService,
        settings: HubSettings | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        worker_id: str | None = None,
    ) -> None:
        self.store = store
        self.provider_health = provider_health
        self.settings = settings or default_settings
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.worker_id = worker_id or f"phs-{uuid.uuid4().hex[:16]}"
        interval = self.settings.provider_health_scheduler_interval_seconds
        if interval < 60 or interval > 86400:
            raise ValueError(
                "AGENT_PROVIDER_HEALTH_SCHEDULER_INTERVAL_SECONDS must be between 60 and 86400"
            )
        self.interval_seconds = interval
        self.enabled = self.settings.provider_health_scheduler_enabled
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    def _initial_status(self) -> ProviderHealthSchedulerStatus:
        return ProviderHealthSchedulerStatus(
            enabled=self.enabled,
            interval_seconds=self.interval_seconds,
            state=(
                ProviderHealthSchedulerState.IDLE
                if self.enabled
                else ProviderHealthSchedulerState.DISABLED
            ),
        )

    def status(self) -> ProviderHealthSchedulerStatus:
        stored = self.store.get_provider_health_scheduler_status() or self._initial_status()
        if (
            stored.enabled != self.enabled
            or stored.interval_seconds != self.interval_seconds
        ):
            stored = stored.model_copy(
                update={
                    "enabled": self.enabled,
                    "interval_seconds": self.interval_seconds,
                    "state": (
                        stored.state
                        if self.enabled
                        else ProviderHealthSchedulerState.DISABLED
                    ),
                    "next_run_at": None if not self.enabled else stored.next_run_at,
                }
            )
        return stored

    async def run_once(self, *, force: bool = False) -> ProviderHealthSchedulerStatus:
        current = self.status()
        if not self.enabled and not force:
            return current
        lease_ttl = max(60, min(self.interval_seconds * 2, 86400))
        if not self.store.acquire_provider_health_scheduler_lease(
            self.worker_id, lease_ttl
        ):
            skipped = current.model_copy(
                update={
                    "skipped_lease_count": current.skipped_lease_count + 1,
                }
            )
            self.store.save_provider_health_scheduler_status(skipped)
            return skipped

        started_at = self.clock()
        running = current.model_copy(
            update={
                "state": ProviderHealthSchedulerState.RUNNING,
                "last_started_at": started_at,
                "last_error_code": None,
            }
        )
        self.store.save_provider_health_scheduler_status(running)
        try:
            result = self.provider_health.evaluate_cached(
                actor="provider_health_scheduler"
            )
            finished_at = self.clock()
            succeeded = running.model_copy(
                update={
                    "state": ProviderHealthSchedulerState.SUCCEEDED,
                    "last_finished_at": finished_at,
                    "next_run_at": (
                        finished_at + timedelta(seconds=self.interval_seconds)
                        if self.enabled
                        else None
                    ),
                    "last_snapshot_id": (
                        result.latest_snapshot.snapshot_id
                        if result.latest_snapshot is not None
                        else None
                    ),
                    "run_count": running.run_count + 1,
                }
            )
            self.store.save_provider_health_scheduler_status(succeeded)
            return succeeded
        except Exception:
            finished_at = self.clock()
            failed = running.model_copy(
                update={
                    "state": ProviderHealthSchedulerState.FAILED,
                    "last_finished_at": finished_at,
                    "next_run_at": (
                        finished_at + timedelta(seconds=self.interval_seconds)
                        if self.enabled
                        else None
                    ),
                    "run_count": running.run_count + 1,
                    "last_error_code": "evaluation_failed",
                }
            )
            self.store.save_provider_health_scheduler_status(failed)
            return failed
        finally:
            self.store.release_provider_health_scheduler_lease(self.worker_id)

    async def _run_forever(self) -> None:
        while not self._stop.is_set():
            await self.run_once()
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self.interval_seconds
                )
            except TimeoutError:
                continue

    async def start(self) -> None:
        if self.store.get_provider_health_scheduler_status() is None:
            self.store.save_provider_health_scheduler_status(self._initial_status())
        if not self.enabled or (self._task is not None and not self._task.done()):
            return
        self._stop.clear()
        self._task = asyncio.create_task(
            self._run_forever(), name="provider-health-scheduler"
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None
