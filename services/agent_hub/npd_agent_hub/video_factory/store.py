from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Protocol

from redis import Redis

from .models import (
    PersistedVideoFactoryEvent,
    VideoFactoryAuditRecord,
    VideoFactoryEventEnvelope,
    WebhookVerificationReceipt,
    utc_now,
)


class EventIdempotencyConflict(RuntimeError):
    pass


class VideoFactoryBoundaryStore(Protocol):
    backend_name: str

    def claim_replay(self, scope: str, value: str, *, ttl_seconds: int) -> bool: ...

    def save_event(
        self,
        *,
        event: VideoFactoryEventEnvelope,
        verification: WebhookVerificationReceipt,
        received_at: datetime | None = None,
    ) -> tuple[PersistedVideoFactoryEvent, bool]: ...

    def get_event(self, event_id: str) -> PersistedVideoFactoryEvent | None: ...

    def list_events(self, limit: int = 100) -> list[PersistedVideoFactoryEvent]: ...

    def append_audit(self, record: VideoFactoryAuditRecord) -> None: ...

    def list_audit(self, limit: int = 100) -> list[VideoFactoryAuditRecord]: ...


@dataclass
class MemoryVideoFactoryBoundaryStore:
    """Deterministic CI/mock store; never shared with a Video Factory runtime."""

    backend_name: str = "memory"
    now: Callable[[], float] = time.time
    _replays: dict[str, float] = field(default_factory=dict)
    _events: dict[str, PersistedVideoFactoryEvent] = field(default_factory=dict)
    _audit: list[VideoFactoryAuditRecord] = field(default_factory=list)

    def claim_replay(self, scope: str, value: str, *, ttl_seconds: int) -> bool:
        if ttl_seconds < 1:
            raise ValueError("replay TTL must be positive")
        current = self.now()
        replay_key = _replay_key(scope, value)
        expires_at = self._replays.get(replay_key)
        if expires_at is not None and expires_at > current:
            return False
        self._replays[replay_key] = current + ttl_seconds
        return True

    def save_event(
        self,
        *,
        event: VideoFactoryEventEnvelope,
        verification: WebhookVerificationReceipt,
        received_at: datetime | None = None,
    ) -> tuple[PersistedVideoFactoryEvent, bool]:
        existing = self._events.get(event.event_id)
        if existing is not None:
            if existing.verification.body_sha256 != verification.body_sha256:
                raise EventIdempotencyConflict(
                    "event_id is already bound to a different body"
                )
            return existing.model_copy(deep=True), True
        record = PersistedVideoFactoryEvent(
            event=event,
            verification=verification,
            received_at=received_at or utc_now(),
        )
        self._events[event.event_id] = record.model_copy(deep=True)
        return record, False

    def get_event(self, event_id: str) -> PersistedVideoFactoryEvent | None:
        record = self._events.get(event_id)
        return record.model_copy(deep=True) if record else None

    def list_events(self, limit: int = 100) -> list[PersistedVideoFactoryEvent]:
        _validate_limit(limit)
        rows = sorted(
            self._events.values(), key=lambda item: item.received_at, reverse=True
        )[:limit]
        return [row.model_copy(deep=True) for row in rows]

    def append_audit(self, record: VideoFactoryAuditRecord) -> None:
        self._audit.append(record.model_copy(deep=True))
        del self._audit[:-5000]

    def list_audit(self, limit: int = 100) -> list[VideoFactoryAuditRecord]:
        _validate_limit(limit)
        return [row.model_copy(deep=True) for row in self._audit[-limit:]][::-1]


class RedisVideoFactoryBoundaryStore:
    """Agent Hub-owned persistence using an isolated namespace, never V2 keys."""

    backend_name = "redis"

    def __init__(
        self,
        *,
        client: Redis,
        namespace: str = "npd:agent-hub:v1:video-factory-boundary",
    ) -> None:
        cleaned = namespace.strip(":")
        if not cleaned.startswith("npd:agent-hub:"):
            raise ValueError("boundary store must use an Agent Hub-owned namespace")
        self.redis = client
        self.namespace = cleaned

    def _key(self, *parts: str) -> str:
        return ":".join((self.namespace, *parts))

    def claim_replay(self, scope: str, value: str, *, ttl_seconds: int) -> bool:
        if ttl_seconds < 1:
            raise ValueError("replay TTL must be positive")
        digest = _replay_key(scope, value)
        return bool(
            self.redis.set(
                self._key("replay", digest), "1", nx=True, ex=ttl_seconds
            )
        )

    def save_event(
        self,
        *,
        event: VideoFactoryEventEnvelope,
        verification: WebhookVerificationReceipt,
        received_at: datetime | None = None,
    ) -> tuple[PersistedVideoFactoryEvent, bool]:
        record = PersistedVideoFactoryEvent(
            event=event,
            verification=verification,
            received_at=received_at or utc_now(),
        )
        key = self._key("event", event.event_id)
        inserted = self.redis.set(key, record.model_dump_json(), nx=True)
        if inserted:
            self.redis.zadd(
                self._key("events"), {event.event_id: record.received_at.timestamp()}
            )
            return record, False
        existing = self.get_event(event.event_id)
        if existing is None:
            raise RuntimeError("event disappeared during idempotency check")
        if existing.verification.body_sha256 != verification.body_sha256:
            raise EventIdempotencyConflict(
                "event_id is already bound to a different body"
            )
        # Repair a missing index entry after a process crash between SET NX and ZADD.
        self.redis.zadd(
            self._key("events"),
            {event.event_id: existing.received_at.timestamp()},
        )
        return existing, True

    def get_event(self, event_id: str) -> PersistedVideoFactoryEvent | None:
        raw = self.redis.get(self._key("event", event_id))
        if raw is None:
            return None
        return PersistedVideoFactoryEvent.model_validate_json(_as_text(raw))

    def list_events(self, limit: int = 100) -> list[PersistedVideoFactoryEvent]:
        _validate_limit(limit)
        event_ids = self.redis.zrevrange(self._key("events"), 0, limit - 1)
        rows: list[PersistedVideoFactoryEvent] = []
        for event_id in event_ids:
            record = self.get_event(_as_text(event_id))
            if record is not None:
                rows.append(record)
        return rows

    def append_audit(self, record: VideoFactoryAuditRecord) -> None:
        key = self._key("audit")
        pipe = self.redis.pipeline()
        pipe.rpush(key, record.model_dump_json())
        pipe.ltrim(key, -5000, -1)
        pipe.execute()

    def list_audit(self, limit: int = 100) -> list[VideoFactoryAuditRecord]:
        _validate_limit(limit)
        rows = self.redis.lrange(self._key("audit"), -limit, -1)
        return [
            VideoFactoryAuditRecord.model_validate_json(_as_text(row))
            for row in rows[::-1]
        ]


def _replay_key(scope: str, value: str) -> str:
    return hashlib.sha256(f"{scope}\n{value}".encode("utf-8")).hexdigest()


def _as_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def _validate_limit(limit: int) -> None:
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000")
