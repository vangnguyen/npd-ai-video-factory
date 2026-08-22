from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Callable

from pydantic import BaseModel

from .attribution import AttributionService
from .attribution_models import (
    AttributionAuditEvent,
    IdentitySource,
    SourceTouchpointIngestRequest,
)
from .config import HubSettings, settings as default_settings
from .delivery_models import (
    AttributionDeadLetter,
    AttributionDeliveryEnvelope,
    AttributionDeliveryFailure,
    AttributionDeliveryReceipt,
    AttributionDeliveryStatus,
    AttributionReceiptVerification,
    DeliveryFailureCode,
    DeliveryFreshnessState,
    DeliveryOutcome,
    DeliverySourceFreshness,
    PRODUCER_PATTERN,
)
from .store import HubStore


DEFAULT_FRESHNESS_SLOS = {
    "n8n_lead_intake": 15,
    "meta_ads": 1440,
    "ga4": 1440,
    "espocrm": 1440,
    "utm": 60,
}


class DeliveryNotConfigured(RuntimeError):
    pass


class DeliveryIntegrityConflict(RuntimeError):
    pass


class AttributionDeliveryService:
    """Signed receipts and transport observability around shadow attribution ingest."""

    def __init__(
        self,
        store: HubStore,
        attribution: AttributionService,
        settings: HubSettings | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.attribution = attribution
        self.settings = settings or default_settings
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.freshness_slos = self._parse_slos(
            self.settings.attribution_freshness_slos_json
        )

    @staticmethod
    def _parse_slos(raw: str) -> dict[str, int]:
        if not raw:
            return dict(DEFAULT_FRESHNESS_SLOS)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("freshness SLO configuration must be valid JSON") from exc
        if not isinstance(payload, dict) or not payload:
            raise ValueError("freshness SLO configuration must be a non-empty object")
        result: dict[str, int] = {}
        for producer, minutes in payload.items():
            if not isinstance(producer, str) or not PRODUCER_PATTERN.fullmatch(producer):
                raise ValueError("freshness SLO producer name is invalid")
            if isinstance(minutes, bool) or not isinstance(minutes, int):
                raise ValueError("freshness SLO minutes must be integers")
            if minutes < 1 or minutes > 60 * 24 * 30:
                raise ValueError("freshness SLO minutes must be between 1 and 43200")
            result[producer] = minutes
        return result

    def _require_configured(self) -> None:
        if len(self.settings.attribution_receipt_signing_key) < 32:
            raise DeliveryNotConfigured(
                "AGENT_ATTRIBUTION_RECEIPT_SIGNING_KEY must be at least 32 characters"
            )
        if not self.settings.attribution_receipt_key_id:
            raise DeliveryNotConfigured(
                "AGENT_ATTRIBUTION_RECEIPT_KEY_ID is required"
            )

    @staticmethod
    def _canonical(value: object) -> bytes:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @classmethod
    def _digest_model(cls, value: BaseModel) -> str:
        return hashlib.sha256(
            cls._canonical(value.model_dump(mode="json"))
        ).hexdigest()

    @staticmethod
    def _receipt_id(delivery_id: str, attempt_number: int) -> str:
        digest = hashlib.sha256(
            f"{delivery_id}:{attempt_number}".encode("utf-8")
        ).hexdigest()[:24]
        return f"adr_{digest}"

    @staticmethod
    def _dead_letter_id(
        delivery_id: str, attempt_number: int, reason: DeliveryFailureCode
    ) -> str:
        digest = hashlib.sha256(
            f"{delivery_id}:{attempt_number}:{reason.value}".encode("utf-8")
        ).hexdigest()[:24]
        return f"adl_{digest}"

    def _signature(self, receipt: AttributionDeliveryReceipt) -> str:
        payload = receipt.model_dump(mode="json", exclude={"signature"})
        digest = hmac.new(
            self.settings.attribution_receipt_signing_key.encode("utf-8"),
            self._canonical(payload),
            hashlib.sha256,
        ).hexdigest()
        return f"hmac-sha256:{digest}"

    def _build_receipt(self, **payload: object) -> AttributionDeliveryReceipt:
        unsigned = AttributionDeliveryReceipt(
            **payload,
            key_id=self.settings.attribution_receipt_key_id,
            signature=f"hmac-sha256:{'0' * 64}",
        )
        return AttributionDeliveryReceipt(
            **unsigned.model_dump(exclude={"signature"}),
            signature=self._signature(unsigned),
        )

    def _audit(
        self,
        *,
        event_type: str,
        actor: str,
        detail: str,
        metadata: dict[str, object],
    ) -> None:
        self.store.append_attribution_audit(
            AttributionAuditEvent(
                event_type=event_type,
                actor=actor,
                detail=detail,
                metadata={**metadata, "external_side_effect": False},
            )
        )

    def _save_dead_letter(
        self,
        *,
        delivery_id: str,
        producer: str,
        source_system: IdentitySource,
        attempt_number: int,
        max_attempts: int,
        reason: DeliveryFailureCode,
        payload_digest: str,
    ) -> AttributionDeadLetter:
        item_id = self._dead_letter_id(delivery_id, attempt_number, reason)
        existing = next(
            (
                item
                for item in self.store.list_attribution_dead_letters(limit=5000)
                if item.dead_letter_id == item_id
            ),
            None,
        )
        if existing is not None:
            return existing
        item = AttributionDeadLetter(
            dead_letter_id=item_id,
            delivery_id=delivery_id,
            producer=producer,
            source_system=source_system,
            attempt_number=attempt_number,
            max_attempts=max_attempts,
            reason_code=reason,
            payload_digest=payload_digest,
            created_at=self.clock(),
        )
        self.store.save_attribution_dead_letter(item)
        return item

    def _existing_or_conflict(
        self,
        *,
        receipt_id: str,
        payload_digest: str,
        delivery_id: str,
        producer: str,
        source_system: IdentitySource,
        attempt_number: int,
        max_attempts: int,
        actor: str,
    ) -> AttributionDeliveryReceipt | None:
        existing = self.store.get_attribution_delivery_receipt(receipt_id)
        if existing is None:
            return None
        if existing.payload_digest == payload_digest:
            return existing
        dead_letter = self._save_dead_letter(
            delivery_id=delivery_id,
            producer=producer,
            source_system=source_system,
            attempt_number=attempt_number,
            max_attempts=max_attempts,
            reason=DeliveryFailureCode.INTEGRITY_CONFLICT,
            payload_digest=payload_digest,
        )
        self._audit(
            event_type="delivery_integrity_conflict",
            actor=actor,
            detail="A reused delivery attempt carried a changed payload and was dead-lettered.",
            metadata={
                "delivery_id": delivery_id,
                "receipt_id": receipt_id,
                "dead_letter_id": dead_letter.dead_letter_id,
            },
        )
        raise DeliveryIntegrityConflict(
            "delivery_id and attempt_number already have a different immutable payload"
        )

    def _validate_attempt_budget(self, attempt_number: int, max_attempts: int) -> None:
        configured_max = self.settings.attribution_delivery_max_attempts
        if configured_max < 1 or configured_max > 10:
            raise DeliveryNotConfigured(
                "AGENT_ATTRIBUTION_DELIVERY_MAX_ATTEMPTS must be between 1 and 10"
            )
        if max_attempts > configured_max or attempt_number > configured_max:
            raise ValueError(
                f"delivery retry budget exceeds configured maximum {configured_max}"
            )

    def ingest(
        self, envelope: AttributionDeliveryEnvelope, *, actor: str
    ) -> AttributionDeliveryReceipt:
        self._require_configured()
        self._validate_attempt_budget(envelope.attempt_number, envelope.max_attempts)
        payload_digest = self._digest_model(envelope)
        receipt_id = self._receipt_id(envelope.delivery_id, envelope.attempt_number)
        existing = self._existing_or_conflict(
            receipt_id=receipt_id,
            payload_digest=payload_digest,
            delivery_id=envelope.delivery_id,
            producer=envelope.producer,
            source_system=envelope.source_system,
            attempt_number=envelope.attempt_number,
            max_attempts=envelope.max_attempts,
            actor=actor,
        )
        if existing is not None:
            return existing

        snapshot = self.attribution.ingest_source_touchpoints(
            SourceTouchpointIngestRequest(events=envelope.events), actor=actor
        )
        outcome = (
            DeliveryOutcome.PARTIAL
            if snapshot.unknown or snapshot.conflicts
            else DeliveryOutcome.ACCEPTED
        )
        receipt = self._build_receipt(
            receipt_id=receipt_id,
            delivery_id=envelope.delivery_id,
            producer=envelope.producer,
            source_system=envelope.source_system,
            attempt_number=envelope.attempt_number,
            max_attempts=envelope.max_attempts,
            outcome=outcome,
            payload_digest=payload_digest,
            snapshot_id=snapshot.snapshot_id,
            received=snapshot.received,
            resolved=snapshot.resolved,
            inserted=snapshot.inserted,
            duplicates=snapshot.duplicates,
            unknown=snapshot.unknown,
            conflicts=snapshot.conflicts,
            received_at=self.clock(),
        )
        self.store.save_attribution_delivery_receipt(receipt)
        self._audit(
            event_type="signed_delivery_received",
            actor=actor,
            detail="A read-only attribution delivery produced an immutable signed receipt.",
            metadata={
                "delivery_id": envelope.delivery_id,
                "receipt_id": receipt.receipt_id,
                "producer": envelope.producer,
                "outcome": receipt.outcome.value,
                "snapshot_id": snapshot.snapshot_id,
            },
        )
        return receipt

    def record_failure(
        self, failure: AttributionDeliveryFailure, *, actor: str
    ) -> AttributionDeliveryReceipt:
        self._require_configured()
        self._validate_attempt_budget(failure.attempt_number, failure.max_attempts)
        payload_digest = self._digest_model(failure)
        receipt_id = self._receipt_id(failure.delivery_id, failure.attempt_number)
        existing = self._existing_or_conflict(
            receipt_id=receipt_id,
            payload_digest=payload_digest,
            delivery_id=failure.delivery_id,
            producer=failure.producer,
            source_system=failure.source_system,
            attempt_number=failure.attempt_number,
            max_attempts=failure.max_attempts,
            actor=actor,
        )
        if existing is not None:
            return existing

        exhausted = failure.attempt_number >= failure.max_attempts
        delay_seconds = min(30 * (2 ** (failure.attempt_number - 1)), 900)
        now = self.clock()
        receipt = self._build_receipt(
            receipt_id=receipt_id,
            delivery_id=failure.delivery_id,
            producer=failure.producer,
            source_system=failure.source_system,
            attempt_number=failure.attempt_number,
            max_attempts=failure.max_attempts,
            outcome=(
                DeliveryOutcome.DEAD_LETTERED
                if exhausted
                else DeliveryOutcome.RETRY_PENDING
            ),
            payload_digest=payload_digest,
            retry_allowed=not exhausted,
            next_retry_at=None if exhausted else now + timedelta(seconds=delay_seconds),
            dead_lettered=exhausted,
            error_code=failure.error_code,
            received_at=now,
        )
        self.store.save_attribution_delivery_receipt(receipt)
        dead_letter_id: str | None = None
        if exhausted:
            item = self._save_dead_letter(
                delivery_id=failure.delivery_id,
                producer=failure.producer,
                source_system=failure.source_system,
                attempt_number=failure.attempt_number,
                max_attempts=failure.max_attempts,
                reason=failure.error_code,
                payload_digest=payload_digest,
            )
            dead_letter_id = item.dead_letter_id
        self._audit(
            event_type="delivery_failure_recorded",
            actor=actor,
            detail=(
                "Delivery retry budget was exhausted and the attempt was dead-lettered."
                if exhausted
                else "Delivery failure was recorded with a bounded producer retry window."
            ),
            metadata={
                "delivery_id": failure.delivery_id,
                "receipt_id": receipt.receipt_id,
                "producer": failure.producer,
                "attempt_number": failure.attempt_number,
                "max_attempts": failure.max_attempts,
                "outcome": receipt.outcome.value,
                "error_code": failure.error_code.value,
                "dead_letter_id": dead_letter_id,
            },
        )
        return receipt

    def list_receipts(
        self,
        *,
        producer: str | None = None,
        outcome: DeliveryOutcome | None = None,
        limit: int = 100,
    ) -> list[AttributionDeliveryReceipt]:
        rows = self.store.list_attribution_delivery_receipts(
            producer=producer, limit=max(limit * 5, limit)
        )
        if outcome is not None:
            rows = [item for item in rows if item.outcome == outcome]
        return rows[:limit]

    def list_dead_letters(
        self, *, producer: str | None = None, limit: int = 100
    ) -> list[AttributionDeadLetter]:
        return self.store.list_attribution_dead_letters(
            producer=producer, limit=limit
        )

    def verify(
        self, receipt: AttributionDeliveryReceipt
    ) -> AttributionReceiptVerification:
        self._require_configured()
        if receipt.key_id != self.settings.attribution_receipt_key_id:
            return AttributionReceiptVerification(
                receipt_id=receipt.receipt_id,
                valid=False,
                key_id=receipt.key_id,
                detail="Receipt key_id is not active.",
            )
        valid = hmac.compare_digest(receipt.signature, self._signature(receipt))
        return AttributionReceiptVerification(
            receipt_id=receipt.receipt_id,
            valid=valid,
            key_id=receipt.key_id,
            detail="Signature is valid." if valid else "Signature verification failed.",
        )

    def status(self) -> AttributionDeliveryStatus:
        receipts = self.store.list_attribution_delivery_receipts(limit=5000)
        dead_letters = self.store.list_attribution_dead_letters(limit=5000)
        now = self.clock()
        successful = {
            DeliveryOutcome.ACCEPTED,
            DeliveryOutcome.PARTIAL,
        }
        observed_producers = {item.producer for item in receipts}
        sources: list[DeliverySourceFreshness] = []
        for producer in sorted(set(self.freshness_slos) | observed_producers):
            target = self.freshness_slos.get(producer, 1440)
            latest = next(
                (
                    item
                    for item in receipts
                    if item.producer == producer and item.outcome in successful
                ),
                None,
            )
            if latest is None:
                sources.append(
                    DeliverySourceFreshness(
                        producer=producer,
                        target_minutes=target,
                        state=DeliveryFreshnessState.NO_DATA,
                    )
                )
                continue
            age_minutes = round(
                max(0.0, (now - latest.received_at).total_seconds() / 60), 2
            )
            sources.append(
                DeliverySourceFreshness(
                    producer=producer,
                    target_minutes=target,
                    state=(
                        DeliveryFreshnessState.FRESH
                        if age_minutes <= target
                        else DeliveryFreshnessState.STALE
                    ),
                    last_success_at=latest.received_at,
                    age_minutes=age_minutes,
                    last_receipt_id=latest.receipt_id,
                )
            )
        counts = {outcome: 0 for outcome in DeliveryOutcome}
        for receipt in receipts:
            counts[receipt.outcome] += 1
        return AttributionDeliveryStatus(
            configured=(
                len(self.settings.attribution_receipt_signing_key) >= 32
                and bool(self.settings.attribution_receipt_key_id)
            ),
            key_id=self.settings.attribution_receipt_key_id,
            receipt_count=len(receipts),
            accepted=counts[DeliveryOutcome.ACCEPTED],
            partial=counts[DeliveryOutcome.PARTIAL],
            retry_pending=counts[DeliveryOutcome.RETRY_PENDING],
            dead_lettered=counts[DeliveryOutcome.DEAD_LETTERED],
            dead_letter_count=len(dead_letters),
            sources=sources,
        )
