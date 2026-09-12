"""Capture a read-only preflight before interpreting its result.

Library only: this module has no dispatcher, approval, claim or deploy entrypoint.
The caller must supply its validated strict-SSH invoker and a fresh binding.
Opaque output is represented by exact byte lengths/hashes and redacted content.
Only a narrowly validated, non-sensitive failure document is retained verbatim.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Callable
from uuid import UUID, uuid4


SAFE_FAILURE_REASONS = frozenset({
    "PROTECTED_SERVICE_DRIFT", "TARGET_BASELINE_DRIFT",
    "TARGET_BASELINE_SIGNATURE_DRIFT", "PREFLIGHT_OUTSIDE_MUTATION_START_WINDOW",
    "OPERATION_ALREADY_CLAIMED_OR_ATTEMPTED", "OPERATION_RACED_DURING_PREFLIGHT",
})


class CaptureStop(Exception):
    """A bounded reason, with a pointer to evidence; never raw child output."""

    def __init__(self, reason: str, capture_path: Path | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.capture_path = capture_path


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _parse(raw: bytes) -> dict | None:
    if len(raw) > 1024 * 1024:
        return None
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
        return value if isinstance(value, dict) else None
    except (ValueError, UnicodeError, RecursionError):
        return None


def _safe_failure(raw: bytes, binding_id: str) -> dict | None:
    value = _parse(raw)
    if value is None or set(value) != {"status", "reason", "operation_id", "raw_sensitive_output"}:
        return None
    if (value["status"] != "ABORTED_FAIL_CLOSED"
            or not isinstance(value["reason"], str)
            or value["reason"] not in SAFE_FAILURE_REASONS
            or value["operation_id"] != binding_id
            or value["raw_sensitive_output"] is not False):
        return None
    return value


def _bytes(value: bytes | str | None) -> bytes:
    if isinstance(value, str):
        return value.encode("utf-8")
    return value or b""


def _stream(raw: bytes, *, retain_verbatim: bool = False) -> dict:
    result = {"length_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    if not raw:
        result["content"] = "EMPTY"
    elif retain_verbatim:
        result["content"] = "VALIDATED_NON_SENSITIVE_FAILURE_BASE64"
        result["base64"] = base64.b64encode(raw).decode("ascii")
    else:
        result["content"] = "REDACTED_OPAQUE_OUTPUT"
    return result


def _publish(directory: Path, invocation_id: str, value: dict) -> Path:
    """Publish one complete, fsynced receipt atomically, without overwriting."""
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / ("capture-" + invocation_id + ".json")
    raw = json.dumps(value, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    descriptor, temporary = tempfile.mkstemp(prefix=".capture-", dir=directory)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        # Linking an already complete file is atomic and fails if target exists.
        os.link(temporary_path, target)
    finally:
        temporary_path.unlink(missing_ok=True)
    return target


def invoke_preflight(
    invoker: Callable,
    argv: list[str],
    *,
    input_bytes: bytes,
    timeout: float,
    evidence_directory: Path,
    binding_id: str,
    invocation_id: str | None = None,
    success_verifier: Callable[[dict], bool] | None = None,
) -> tuple[dict, Path]:
    """Persist streams/rc/UUID first; a nonzero rc always aborts.

    ``invoker`` has the existing invoke_argv(argv, input_bytes, timeout)
    contract. Neither argv nor stdin is written: they may carry authorization.
    Success requires explicit read-only flags and a caller's binding verifier.
    The verifier must return exactly True; missing/failed verification aborts.
    """
    identifier = invocation_id or str(uuid4())
    try:
        if str(UUID(identifier)) != identifier:
            raise ValueError("noncanonical UUID")
        if not isinstance(binding_id, str) or not 1 <= len(binding_id) <= 160:
            raise ValueError("invalid binding")
        if not all(character.isascii() and (character.isalnum() or character in "-_.")
                   for character in binding_id):
            raise ValueError("invalid binding")
    except (ValueError, AttributeError, TypeError):
        raise CaptureStop("CAPTURE_BINDING_INVALID") from None

    started = datetime.now(timezone.utc).isoformat()
    timed_out = False
    launch_error = None
    try:
        result = invoker(argv, input_bytes=input_bytes, timeout=timeout)
        stdout, stderr, returncode = result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired as error:
        stdout, stderr, returncode = error.stdout, error.stderr, None
        timed_out = True
    except OSError as error:
        stdout, stderr, returncode = b"", b"", None
        launch_error = type(error).__name__
    except Exception as error:
        # The existing SSH contract wraps TimeoutExpired/OSError in ContractError.
        # Preserve the underlying partial streams without copying error messages.
        underlying = error
        for _ in range(8):
            if isinstance(underlying, (subprocess.TimeoutExpired, OSError)):
                break
            if underlying.__cause__ is None:
                break
            underlying = underlying.__cause__
        if isinstance(underlying, subprocess.TimeoutExpired):
            stdout, stderr, returncode = underlying.stdout, underlying.stderr, None
            timed_out = True
        else:
            stdout, stderr, returncode = b"", b"", None
            launch_error = type(underlying).__name__
    stdout, stderr = _bytes(stdout), _bytes(stderr)
    failure = _safe_failure(stdout, binding_id)
    receipt = {
        "schema": "npd.agent-hub.phase9.remote-preflight-capture.v1",
        "binding_id": binding_id, "invocation_id": identifier,
        "started_at_utc": started,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "child_returncode": returncode, "timed_out": timed_out,
        "launch_error_class": launch_error,
        "stdin": {"length_bytes": len(input_bytes), "sha256": hashlib.sha256(input_bytes).hexdigest()},
        "stdout": _stream(stdout, retain_verbatim=failure is not None),
        "stderr": _stream(stderr), "validated_failure": failure,
        "argv_or_authorization_persisted": False,
    }
    try:
        capture_path = _publish(evidence_directory, identifier, receipt)
    except OSError:
        raise CaptureStop("CAPTURE_EVIDENCE_UNAVAILABLE") from None

    if timed_out:
        raise CaptureStop("REMOTE_PREFLIGHT_TIMEOUT", capture_path)
    if launch_error:
        raise CaptureStop("REMOTE_PREFLIGHT_LAUNCH_ERROR", capture_path)
    if type(returncode) is not int:
        raise CaptureStop("REMOTE_PREFLIGHT_RETURNCODE_INVALID", capture_path)
    if returncode != 0:
        reason = failure["reason"] if failure else "UNCLASSIFIED"
        raise CaptureStop("REMOTE_PREFLIGHT_FAILED:" + reason, capture_path)
    value = _parse(stdout)
    if (stderr or value is None or value.get("status") != "PASS"
            or value.get("operation_id") != binding_id or value.get("mode") != "preflight"
            or value.get("claim_absent") is not True
            or value.get("candidate_staged") is not False
            or value.get("production_mutation") is not False
            or value.get("business_system_write") is not False
            or value.get("raw_secrets_accounts_keys_values_or_pii_emitted") is not False):
        raise CaptureStop("REMOTE_PREFLIGHT_OUTPUT_INVALID", capture_path)
    if success_verifier is None:
        raise CaptureStop("REMOTE_PREFLIGHT_VERIFIER_REQUIRED", capture_path)
    try:
        verified = success_verifier(value)
    except Exception:
        raise CaptureStop("REMOTE_PREFLIGHT_VERIFIER_FAILED", capture_path) from None
    if verified is not True:
        raise CaptureStop("REMOTE_PREFLIGHT_VERIFIER_FAILED", capture_path)
    return value, capture_path
