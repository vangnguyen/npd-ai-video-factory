from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
from collections import Counter
from threading import Lock
from typing import Any


LOGGER = logging.getLogger("npd.legacy_telemetry")
CALLER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
ROUTE_ACTIONS = {
    "/healthz": "health_probe",
    "/readyz": "health_probe",
    "/api/v1/video-jobs": "legacy_write",
    "/api/v1/video-jobs/{job_id}": "legacy_read",
    "/api/v1/video-jobs/{job_id}/artifacts/{artifact_name}": "legacy_artifact_read",
}


def _safe_claimed_caller(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value if CALLER_ID.fullmatch(value) else "invalid"


def _fingerprint(value: str, salt: bytes | None) -> str | None:
    if not salt:
        return None
    digest = hmac.new(salt, value.encode("utf-8", errors="replace"), hashlib.sha256).hexdigest()
    return f"hmac-sha256:{digest[:24]}"


class LegacyTelemetry:
    """Emit identity-safe route events without storing payloads, IDs, URLs, IPs or user agents."""

    def __init__(self, *, salt: str | None, logger: logging.Logger = LOGGER):
        self._salt = salt.encode("utf-8") if salt else None
        self._logger = logger
        self._route_counts: Counter[str] = Counter()
        self._deprecated_attempt_count = 0
        self._lock = Lock()

    @classmethod
    def from_environment(cls) -> "LegacyTelemetry":
        return cls(salt=os.getenv("LEGACY_TELEMETRY_SALT", "").strip() or None)

    @property
    def identity_ready(self) -> bool:
        return self._salt is not None

    def record(
        self,
        *,
        route: str | None,
        method: str,
        status_code: int,
        peer_host: str | None,
        claimed_caller_id: str | None,
        user_agent: str | None,
    ) -> dict[str, Any] | None:
        if route not in ROUTE_ACTIONS:
            return None
        action = ROUTE_ACTIONS[route]
        deprecated_attempt = action != "health_probe"
        with self._lock:
            self._route_counts[route] += 1
            route_count = self._route_counts[route]
            if deprecated_attempt:
                self._deprecated_attempt_count += 1
            deprecated_count = self._deprecated_attempt_count

        peer = peer_host or "unavailable"
        agent = user_agent or "unavailable"
        event: dict[str, Any] = {
            "event": "legacy_route_access",
            "service": "video-factory-v1-api",
            "route": route,
            "method": method.upper(),
            "status_code": int(status_code),
            "action": action,
            "deprecated_attempt": deprecated_attempt,
            "claimed_caller_id": _safe_claimed_caller(claimed_caller_id),
            "source_fingerprint": _fingerprint(peer, self._salt),
            "client_fingerprint": _fingerprint(f"{peer}\n{agent}", self._salt),
            "identity_ready": self.identity_ready,
            "route_request_count": route_count,
            "deprecated_attempt_count": deprecated_count,
            "payload_logged": False,
            "raw_network_identity_logged": False,
        }
        self._logger.info(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
        return event
