from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from pydantic import ValidationError

from .auth import WebhookVerifier
from .client import IntegrationDisabled, VideoFactoryClient
from .models import (
    BoundaryMode,
    EventType,
    LIVE_OUTBOUND_EVENTS,
    PersistedVideoFactoryEvent,
    VideoFactoryAuditRecord,
    VideoFactoryEventEnvelope,
    VideoFactoryIntegrationStatus,
    WebhookAcceptedResponse,
    WebhookOutcome,
    WebhookVerificationReceipt,
    utc_now,
)
from .store import EventIdempotencyConflict, VideoFactoryBoundaryStore


class WebhookBoundaryError(RuntimeError):
    def __init__(self, *, code: str, message: str, status_code: int):
        self.code = code
        self.status_code = status_code
        super().__init__(message)


class VideoFactoryWebhookReceiver:
    def __init__(
        self,
        *,
        verifier: WebhookVerifier,
        store: VideoFactoryBoundaryStore,
        live_event_types: frozenset[EventType] | None = None,
        max_body_bytes: int = 1_000_000,
    ) -> None:
        if max_body_bytes < 1024:
            raise ValueError("webhook body limit must be at least 1024 bytes")
        self.verifier = verifier
        self.store = store
        self.max_body_bytes = max_body_bytes
        self.live_event_types = live_event_types or frozenset(
            EventType(value) for value in LIVE_OUTBOUND_EVENTS
        )

    def __repr__(self) -> str:
        return (
            "VideoFactoryWebhookReceiver(verification_keys=<redacted>, "
            f"store={self.store.backend_name!r})"
        )

    def receive(
        self,
        *,
        body: bytes,
        headers: Mapping[str, str],
        received_at: datetime | None = None,
    ) -> WebhookAcceptedResponse:
        if len(body) > self.max_body_bytes:
            raise WebhookBoundaryError(
                code="VIDEO_FACTORY_EVENT_TOO_LARGE",
                message="Video Factory event exceeds the accepted body limit",
                status_code=413,
            )
        verified = self.verifier.verify(body=body, headers=headers)
        try:
            event = VideoFactoryEventEnvelope.model_validate_json(body)
        except ValidationError as exc:
            raise WebhookBoundaryError(
                code="VIDEO_FACTORY_EVENT_INVALID",
                message="Video Factory event violated agent-hub-bridge.v1",
                status_code=422,
            ) from exc
        if not hmac.compare_digest(event.event_id, verified.event_id):
            raise WebhookBoundaryError(
                code="VIDEO_FACTORY_EVENT_ID_MISMATCH",
                message="Signed event ID does not match the event body",
                status_code=409,
            )
        if event.event_type not in self.live_event_types:
            raise WebhookBoundaryError(
                code="VIDEO_FACTORY_EVENT_NOT_LIVE",
                message="Event is reserved but has no accepted V2-11 emitter",
                status_code=409,
            )
        verification = WebhookVerificationReceipt(
            key_id=verified.key_id,
            signed_at_unix=verified.timestamp,
            body_sha256=verified.body_sha256,
        )
        try:
            _record, replayed = self.store.save_event(
                event=event,
                verification=verification,
                received_at=received_at or utc_now(),
            )
        except EventIdempotencyConflict as exc:
            self.store.append_audit(
                VideoFactoryAuditRecord(
                    event_id=event.event_id,
                    outcome=WebhookOutcome.CONFLICT,
                    key_id=verified.key_id,
                    body_sha256=verified.body_sha256,
                    detail="event_id was reused with a different signed body",
                )
            )
            raise WebhookBoundaryError(
                code="VIDEO_FACTORY_EVENT_IDEMPOTENCY_CONFLICT",
                message="Event ID is already bound to a different body",
                status_code=409,
            ) from exc
        outcome = (
            WebhookOutcome.IDEMPOTENT_REPLAY if replayed else WebhookOutcome.ACCEPTED
        )
        self.store.append_audit(
            VideoFactoryAuditRecord(
                event_id=event.event_id,
                outcome=outcome,
                key_id=verified.key_id,
                body_sha256=verified.body_sha256,
                detail=(
                    "verified event replay produced no duplicate side effect"
                    if replayed
                    else "verified live event persisted"
                ),
            )
        )
        return WebhookAcceptedResponse(
            event_id=event.event_id,
            status=outcome.value,
        )


@dataclass(frozen=True)
class VideoFactoryBoundary:
    client: VideoFactoryClient
    store: VideoFactoryBoundaryStore | None = None
    receiver: VideoFactoryWebhookReceiver | None = None

    @classmethod
    def disabled(cls) -> "VideoFactoryBoundary":
        return cls(client=VideoFactoryClient(mode=BoundaryMode.DISABLED))

    def status(self) -> VideoFactoryIntegrationStatus:
        return self.client.status()

    def require_receiver(self) -> VideoFactoryWebhookReceiver:
        if self.receiver is None or self.store is None:
            raise IntegrationDisabled("Video Factory webhook receiver is disabled")
        return self.receiver

    def list_events(self, limit: int = 100) -> list[PersistedVideoFactoryEvent]:
        if self.store is None:
            raise IntegrationDisabled("Video Factory event persistence is disabled")
        return self.store.list_events(limit=limit)

    def list_audit(self, limit: int = 100) -> list[VideoFactoryAuditRecord]:
        if self.store is None:
            raise IntegrationDisabled("Video Factory event audit is disabled")
        return self.store.list_audit(limit=limit)
