from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .attribution_models import (
    IdentitySource,
    SourceTouchpointEvent,
    assert_no_enabled_write_flags,
    assert_no_raw_pii,
    assert_pseudonymous_reference,
)


PRODUCER_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{1,79}$")
DELIVERY_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{2,119}$")


class DeliveryOutcome(str, Enum):
    ACCEPTED = "accepted"
    PARTIAL = "partial"
    RETRY_PENDING = "retry_pending"
    DEAD_LETTERED = "dead_lettered"


class DeliveryFreshnessState(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    NO_DATA = "no_data"


class DeliveryFailureCode(str, Enum):
    NETWORK_TIMEOUT = "network_timeout"
    RATE_LIMITED = "rate_limited"
    PROVIDER_5XX = "provider_5xx"
    PROVIDER_AUTH = "provider_auth"
    INVALID_PAYLOAD = "invalid_payload"
    INTEGRITY_CONFLICT = "integrity_conflict"
    UNKNOWN = "unknown"


def validate_delivery_id(value: str) -> str:
    assert_pseudonymous_reference(value)
    if not DELIVERY_ID_PATTERN.fullmatch(value):
        raise ValueError("delivery_id contains unsupported characters")
    return value


class AttributionDeliveryEnvelope(BaseModel):
    delivery_id: str
    producer: str = Field(pattern=PRODUCER_PATTERN.pattern)
    source_system: IdentitySource
    attempt_number: int = Field(default=1, ge=1, le=10)
    max_attempts: int = Field(default=4, ge=1, le=10)
    sent_at: datetime
    events: list[SourceTouchpointEvent] = Field(min_length=1, max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)

    _delivery_id = field_validator("delivery_id")(validate_delivery_id)

    @model_validator(mode="after")
    def validate_delivery(self) -> "AttributionDeliveryEnvelope":
        if self.attempt_number > self.max_attempts:
            raise ValueError("attempt_number cannot exceed max_attempts")
        if any(event.source_system != self.source_system for event in self.events):
            raise ValueError("all events must match envelope source_system")
        assert_no_raw_pii(self.metadata, path="delivery.metadata")
        assert_no_enabled_write_flags(self.metadata, path="delivery.metadata")
        return self


class AttributionDeliveryFailure(BaseModel):
    delivery_id: str
    producer: str = Field(pattern=PRODUCER_PATTERN.pattern)
    source_system: IdentitySource
    attempt_number: int = Field(ge=1, le=10)
    max_attempts: int = Field(default=4, ge=1, le=10)
    occurred_at: datetime
    error_code: DeliveryFailureCode
    metadata: dict[str, Any] = Field(default_factory=dict)

    _delivery_id = field_validator("delivery_id")(validate_delivery_id)

    @model_validator(mode="after")
    def validate_failure(self) -> "AttributionDeliveryFailure":
        if self.attempt_number > self.max_attempts:
            raise ValueError("attempt_number cannot exceed max_attempts")
        assert_no_raw_pii(self.metadata, path="delivery_failure.metadata")
        assert_no_enabled_write_flags(
            self.metadata, path="delivery_failure.metadata"
        )
        return self


class AttributionDeliveryReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    receipt_id: str = Field(pattern=r"^adr_[0-9a-f]{24}$")
    delivery_id: str
    producer: str
    source_system: IdentitySource
    attempt_number: int
    max_attempts: int
    outcome: DeliveryOutcome
    payload_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_id: str | None = None
    received: int = 0
    resolved: int = 0
    inserted: int = 0
    duplicates: int = 0
    unknown: int = 0
    conflicts: int = 0
    retry_allowed: bool = False
    next_retry_at: datetime | None = None
    dead_lettered: bool = False
    error_code: DeliveryFailureCode | None = None
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    key_id: str = Field(min_length=3, max_length=80)
    signature: str = Field(pattern=r"^hmac-sha256:[0-9a-f]{64}$")
    shadow_mode: bool = True
    external_writes_enabled: bool = False

    _delivery_id = field_validator("delivery_id")(validate_delivery_id)

    @model_validator(mode="after")
    def validate_receipt(self) -> "AttributionDeliveryReceipt":
        if self.external_writes_enabled:
            raise ValueError("delivery receipt cannot enable external writes")
        if self.dead_lettered != (self.outcome == DeliveryOutcome.DEAD_LETTERED):
            raise ValueError("dead_lettered must match receipt outcome")
        assert_no_raw_pii(self.model_dump(mode="python"), path="delivery_receipt")
        return self


class AttributionDeadLetter(BaseModel):
    model_config = ConfigDict(frozen=True)

    dead_letter_id: str = Field(pattern=r"^adl_[0-9a-f]{24}$")
    delivery_id: str
    producer: str
    source_system: IdentitySource
    attempt_number: int
    max_attempts: int
    reason_code: DeliveryFailureCode
    payload_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    shadow_mode: bool = True
    external_writes_enabled: bool = False

    _delivery_id = field_validator("delivery_id")(validate_delivery_id)

    @model_validator(mode="after")
    def validate_dead_letter(self) -> "AttributionDeadLetter":
        if self.external_writes_enabled:
            raise ValueError("dead letter cannot enable external writes")
        assert_no_raw_pii(self.model_dump(mode="python"), path="dead_letter")
        return self


class DeliverySourceFreshness(BaseModel):
    producer: str
    target_minutes: int
    state: DeliveryFreshnessState
    last_success_at: datetime | None = None
    age_minutes: float | None = None
    last_receipt_id: str | None = None


class AttributionDeliveryStatus(BaseModel):
    mode: str = "signed_read_only_delivery_observability"
    configured: bool
    key_id: str
    receipt_count: int
    accepted: int
    partial: int
    retry_pending: int
    dead_lettered: int
    dead_letter_count: int
    sources: list[DeliverySourceFreshness] = Field(default_factory=list)
    production_write_enabled: bool = False


class AttributionReceiptVerificationRequest(BaseModel):
    receipt: AttributionDeliveryReceipt


class AttributionReceiptVerification(BaseModel):
    receipt_id: str
    valid: bool
    key_id: str
    detail: str
