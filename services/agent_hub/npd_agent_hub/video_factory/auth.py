from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol

from .models import BRIDGE_CONTRACT_VERSION, BRIDGE_WEBHOOK_PATH


SERVICE_ID_HEADER = "X-NPD-Service-Id"
KEY_ID_HEADER = "X-NPD-Key-Id"
TIMESTAMP_HEADER = "X-NPD-Timestamp"
NONCE_HEADER = "X-NPD-Nonce"
CONTENT_HASH_HEADER = "X-NPD-Content-SHA256"
SIGNATURE_HEADER = "X-NPD-Signature"
CONTRACT_VERSION_HEADER = "X-NPD-Contract-Version"
EVENT_ID_HEADER = "X-NPD-Event-Id"

_NONCE_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{16,128}$")
_HEX_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_IDENTITY_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9._:-]{2,119}$")
_EVENT_ID_PATTERN = re.compile(r"^bevt_[A-Za-z0-9_-]{4,60}$")


class BoundaryAuthError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class ReplayRegistry(Protocol):
    def claim_replay(self, scope: str, value: str, *, ttl_seconds: int) -> bool: ...


@dataclass(frozen=True)
class ServiceIdentity:
    service_id: str
    roles: tuple[str, ...]
    keys: Mapping[str, bytes] = field(repr=False)

    def __post_init__(self) -> None:
        _validate_identity_label(self.service_id, "service_id")
        if "service" not in self.roles:
            raise ValueError("service identity must include the service role")
        _validate_keyring(self.keys)
        object.__setattr__(self, "keys", MappingProxyType(dict(self.keys)))


@dataclass(frozen=True)
class VerifiedServiceRequest:
    service_id: str
    key_id: str
    nonce: str


@dataclass(frozen=True)
class VerifiedWebhook:
    key_id: str
    timestamp: int
    event_id: str
    body_sha256: str


def sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def service_canonical_message(
    *,
    method: str,
    path: str,
    query: str,
    timestamp: int,
    nonce: str,
    content_hash: str,
) -> str:
    return "\n".join(
        (method.upper(), path, query, str(timestamp), nonce, content_hash)
    )


def webhook_canonical_message(
    *, timestamp: int, event_id: str, content_hash: str
) -> str:
    return "\n".join(
        ("POST", BRIDGE_WEBHOOK_PATH, str(timestamp), event_id, content_hash)
    )


class ServiceRequestSigner:
    def __init__(
        self,
        *,
        service_id: str,
        key_id: str,
        key: bytes,
        now: Callable[[], float] = time.time,
    ) -> None:
        _validate_identity_label(service_id, "service_id")
        _validate_identity_label(key_id, "key_id")
        _validate_key(key)
        self.service_id = service_id
        self.key_id = key_id
        self.__key = bytes(key)
        self.now = now

    def __repr__(self) -> str:
        return (
            "ServiceRequestSigner("
            f"service_id={self.service_id!r}, key_id={self.key_id!r}, key=<redacted>)"
        )

    def sign(
        self,
        *,
        method: str,
        path: str,
        query: str = "",
        body: bytes = b"",
        timestamp: int | None = None,
        nonce: str,
    ) -> dict[str, str]:
        if not _NONCE_PATTERN.fullmatch(nonce):
            raise ValueError("nonce must contain 16-128 safe characters")
        issued_at = int(self.now()) if timestamp is None else timestamp
        content_hash = sha256_hex(body)
        canonical = service_canonical_message(
            method=method,
            path=path,
            query=query,
            timestamp=issued_at,
            nonce=nonce,
            content_hash=content_hash,
        )
        return {
            SERVICE_ID_HEADER: self.service_id,
            KEY_ID_HEADER: self.key_id,
            TIMESTAMP_HEADER: str(issued_at),
            NONCE_HEADER: nonce,
            CONTENT_HASH_HEADER: content_hash,
            SIGNATURE_HEADER: hmac.new(
                self.__key, canonical.encode("utf-8"), hashlib.sha256
            ).hexdigest(),
            CONTRACT_VERSION_HEADER: BRIDGE_CONTRACT_VERSION,
        }


class ServiceRequestVerifier:
    def __init__(
        self,
        *,
        identities: Mapping[str, ServiceIdentity],
        replay_registry: ReplayRegistry,
        max_clock_skew_seconds: int = 300,
        replay_ttl_seconds: int = 600,
        now: Callable[[], float] = time.time,
    ) -> None:
        if max_clock_skew_seconds < 1 or replay_ttl_seconds < max_clock_skew_seconds:
            raise ValueError("invalid service authentication replay window")
        self.identities = MappingProxyType(dict(identities))
        self.replay_registry = replay_registry
        self.max_clock_skew_seconds = max_clock_skew_seconds
        self.replay_ttl_seconds = replay_ttl_seconds
        self.now = now

    def verify(
        self,
        *,
        method: str,
        path: str,
        query: str,
        body: bytes,
        headers: Mapping[str, str],
    ) -> VerifiedServiceRequest:
        if _header(headers, CONTRACT_VERSION_HEADER) != BRIDGE_CONTRACT_VERSION:
            raise BoundaryAuthError(
                "CONTRACT_VERSION_REQUIRED", "agent-hub-bridge.v1 is required"
            )
        service_id = _header(headers, SERVICE_ID_HEADER)
        key_id = _header(headers, KEY_ID_HEADER)
        nonce = _header(headers, NONCE_HEADER)
        timestamp_text = _header(headers, TIMESTAMP_HEADER)
        supplied_hash = _header(headers, CONTENT_HASH_HEADER)
        signature = _header(headers, SIGNATURE_HEADER)
        if not all(
            (service_id, key_id, nonce, timestamp_text, supplied_hash, signature)
        ):
            raise BoundaryAuthError(
                "SERVICE_AUTH_REQUIRED", "signed service authentication is required"
            )
        if not _IDENTITY_PATTERN.fullmatch(service_id) or not _IDENTITY_PATTERN.fullmatch(
            key_id
        ):
            raise BoundaryAuthError(
                "SERVICE_AUTH_INVALID", "service authentication is invalid"
            )
        if not _NONCE_PATTERN.fullmatch(nonce):
            raise BoundaryAuthError(
                "SERVICE_AUTH_INVALID", "service authentication is invalid"
            )
        timestamp = _parse_timestamp(timestamp_text)
        if abs(int(self.now()) - timestamp) > self.max_clock_skew_seconds:
            raise BoundaryAuthError(
                "SERVICE_AUTH_EXPIRED",
                "service authentication timestamp is outside the allowed window",
            )
        calculated_hash = sha256_hex(body)
        if not _constant_time_sha_match(calculated_hash, supplied_hash):
            raise BoundaryAuthError(
                "SERVICE_AUTH_INVALID", "service authentication is invalid"
            )
        identity = self.identities.get(service_id)
        key = identity.keys.get(key_id) if identity else None
        if identity is None or key is None or "service" not in identity.roles:
            raise BoundaryAuthError(
                "SERVICE_AUTH_INVALID", "service authentication is invalid"
            )
        canonical = service_canonical_message(
            method=method,
            path=path,
            query=query,
            timestamp=timestamp,
            nonce=nonce,
            content_hash=calculated_hash,
        )
        expected = hmac.new(
            key, canonical.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        if not _constant_time_sha_match(expected, signature):
            raise BoundaryAuthError(
                "SERVICE_AUTH_INVALID", "service authentication is invalid"
            )
        if not self.replay_registry.claim_replay(
            f"service:{service_id}:{key_id}",
            nonce,
            ttl_seconds=self.replay_ttl_seconds,
        ):
            raise BoundaryAuthError(
                "SERVICE_AUTH_REPLAY", "signed request nonce has already been used"
            )
        return VerifiedServiceRequest(
            service_id=service_id, key_id=key_id, nonce=nonce
        )


class WebhookVerifier:
    def __init__(
        self,
        *,
        keys: Mapping[str, bytes],
        max_clock_skew_seconds: int = 300,
        now: Callable[[], float] = time.time,
    ) -> None:
        _validate_keyring(keys)
        if max_clock_skew_seconds < 1:
            raise ValueError("webhook clock skew must be positive")
        self.__keys = MappingProxyType(dict(keys))
        self.max_clock_skew_seconds = max_clock_skew_seconds
        self.now = now

    def __repr__(self) -> str:
        return (
            "WebhookVerifier("
            f"key_ids={sorted(self.__keys)!r}, keys=<redacted>, "
            f"max_clock_skew_seconds={self.max_clock_skew_seconds})"
        )

    def verify(
        self, *, body: bytes, headers: Mapping[str, str]
    ) -> VerifiedWebhook:
        if _header(headers, CONTRACT_VERSION_HEADER) != BRIDGE_CONTRACT_VERSION:
            raise BoundaryAuthError(
                "CONTRACT_VERSION_REQUIRED", "agent-hub-bridge.v1 is required"
            )
        key_id = _header(headers, KEY_ID_HEADER)
        timestamp_text = _header(headers, TIMESTAMP_HEADER)
        event_id = _header(headers, EVENT_ID_HEADER)
        supplied_hash = _header(headers, CONTENT_HASH_HEADER)
        signature = _header(headers, SIGNATURE_HEADER)
        if not all((key_id, timestamp_text, event_id, supplied_hash, signature)):
            raise BoundaryAuthError(
                "WEBHOOK_AUTH_REQUIRED", "signed webhook authentication is required"
            )
        if not _IDENTITY_PATTERN.fullmatch(key_id) or not _EVENT_ID_PATTERN.fullmatch(
            event_id
        ):
            raise BoundaryAuthError(
                "WEBHOOK_AUTH_INVALID", "webhook authentication is invalid"
            )
        timestamp = _parse_timestamp(timestamp_text)
        if abs(int(self.now()) - timestamp) > self.max_clock_skew_seconds:
            raise BoundaryAuthError(
                "WEBHOOK_AUTH_EXPIRED",
                "webhook authentication timestamp is outside the allowed window",
            )
        calculated_hash = sha256_hex(body)
        if not _constant_time_sha_match(calculated_hash, supplied_hash):
            raise BoundaryAuthError(
                "WEBHOOK_AUTH_INVALID", "webhook authentication is invalid"
            )
        key = self.__keys.get(key_id)
        if key is None:
            raise BoundaryAuthError(
                "WEBHOOK_AUTH_INVALID", "webhook authentication is invalid"
            )
        canonical = webhook_canonical_message(
            timestamp=timestamp,
            event_id=event_id,
            content_hash=calculated_hash,
        )
        expected = hmac.new(
            key, canonical.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        if not _constant_time_sha_match(expected, signature):
            raise BoundaryAuthError(
                "WEBHOOK_AUTH_INVALID", "webhook authentication is invalid"
            )
        return VerifiedWebhook(
            key_id=key_id,
            timestamp=timestamp,
            event_id=event_id,
            body_sha256=calculated_hash,
        )


def sign_webhook(
    *,
    key: bytes,
    key_id: str,
    body: bytes,
    event_id: str,
    timestamp: int,
) -> dict[str, str]:
    """Test/mock helper implementing the pinned V2 webhook signature contract."""

    _validate_identity_label(key_id, "key_id")
    if not _EVENT_ID_PATTERN.fullmatch(event_id):
        raise ValueError("event_id contains unsupported characters")
    _validate_key(key)
    content_hash = sha256_hex(body)
    canonical = webhook_canonical_message(
        timestamp=timestamp,
        event_id=event_id,
        content_hash=content_hash,
    )
    return {
        KEY_ID_HEADER: key_id,
        TIMESTAMP_HEADER: str(timestamp),
        CONTENT_HASH_HEADER: content_hash,
        SIGNATURE_HEADER: hmac.new(
            key, canonical.encode("utf-8"), hashlib.sha256
        ).hexdigest(),
        CONTRACT_VERSION_HEADER: BRIDGE_CONTRACT_VERSION,
        EVENT_ID_HEADER: event_id,
    }


def _header(headers: Mapping[str, str], name: str) -> str:
    direct = headers.get(name)
    if direct is not None:
        return str(direct)
    target = name.lower()
    for key, value in headers.items():
        if str(key).lower() == target:
            return str(value)
    return ""


def _parse_timestamp(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise BoundaryAuthError(
            "AUTH_TIMESTAMP_INVALID", "authentication timestamp is invalid"
        ) from exc


def _constant_time_sha_match(expected: str, supplied: str) -> bool:
    if not _HEX_SHA256_PATTERN.fullmatch(supplied):
        return False
    return hmac.compare_digest(expected, supplied)


def _validate_key(key: bytes) -> None:
    if not isinstance(key, bytes) or len(key) < 32:
        raise ValueError("HMAC key material must be at least 32 bytes")


def _validate_keyring(keys: Mapping[str, bytes]) -> None:
    if not keys:
        raise ValueError("HMAC keyring must not be empty")
    for key_id, key in keys.items():
        _validate_identity_label(key_id, "key_id")
        _validate_key(key)


def _validate_identity_label(value: str, field_name: str) -> None:
    if not _IDENTITY_PATTERN.fullmatch(value):
        raise ValueError(f"{field_name} contains unsupported characters")
