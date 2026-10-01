"""Closed in-process rehearsal for a built new-lineage review package.

The rehearsal has no pluggable transport or callback and performs no network,
subprocess, SSH, provider, production, image, or delivery action.  It creates
only local fixture evidence next to the supplied review package.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import hmac
from pathlib import Path

import one_delivery_new_lineage as lineage
import one_delivery_new_lineage_builder as builder
import one_delivery_new_lineage_executor_runtime as executor_runtime


REHEARSAL_KEY_ID = "local-new-lineage-rehearsal-v1"
FAULT_MODES = {"NONE", "RAW_RECEIPT_MISMATCH"}


def _snapshot(
    verified: dict[str, object],
    *,
    touchpoints: int,
    source_events: int,
    receipts: int,
    audits: int,
    audit_types: list[str],
) -> dict[str, object]:
    bindings = verified["bindings"]
    return {
        "schema": lineage.READBACK_SCHEMA,
        "lineage": lineage.LINEAGE,
        "campaign_id": bindings["campaign_id"],
        "delivery_id": bindings["delivery_id"],
        "source_event_id": bindings["source_event_id"],
        "subject_touchpoint_count": touchpoints,
        "source_event_match_count": source_events,
        "delivery_receipt_match_count": receipts,
        "campaign_audit_count": audits,
        "latest_campaign_audit_types": audit_types,
        "dead_letter_match_count": 0,
        "counts_are_exact": True,
        "query_limit_applied": False,
        "internal_audit_cap": lineage.INTERNAL_AUDIT_CAP,
        "runtime_mode": "phase9_delivery",
        "scheduler_enabled": False,
    }


def _signed_receipt(
    verified: dict[str, object], *, signing_key: str, observed_at: str
) -> dict[str, object]:
    lineage.require(
        isinstance(signing_key, str) and len(signing_key) >= 32,
        "REHEARSAL_SIGNING_KEY_INVALID",
    )
    lineage._aware_timestamp(observed_at, "REHEARSAL_TIMESTAMP_INVALID")
    binding = verified["delivery_binding"]
    envelope = verified["delivery_envelope"]
    delivery_id = binding["delivery_id"]
    receipt_id = "adr_" + hashlib.sha256(
        f"{delivery_id}:1".encode("utf-8")
    ).hexdigest()[:24]
    receipt: dict[str, object] = {
        "receipt_id": receipt_id,
        "delivery_id": delivery_id,
        "producer": envelope["producer"],
        "source_system": envelope["source_system"],
        "attempt_number": 1,
        "max_attempts": 1,
        "outcome": "accepted",
        "payload_digest": binding["delivery_payload_sha256"],
        "snapshot_id": "LOCAL-OFFLINE-REHEARSAL-SNAPSHOT",
        "received": 1,
        "resolved": 1,
        "inserted": 1,
        "duplicates": 0,
        "unknown": 0,
        "conflicts": 0,
        "retry_allowed": False,
        "next_retry_at": None,
        "dead_lettered": False,
        "error_code": None,
        "received_at": observed_at,
        "key_id": REHEARSAL_KEY_ID,
        "signature": "",
        "shadow_mode": True,
        "external_writes_enabled": False,
    }
    unsigned = {name: value for name, value in receipt.items() if name != "signature"}
    receipt["signature"] = "hmac-sha256:" + hmac.new(
        signing_key.encode("utf-8"),
        lineage.canonical_bytes(unsigned),
        hashlib.sha256,
    ).hexdigest()
    return receipt


def rehearse_offline_package(
    directory: Path | str,
    *,
    expected_manifest_sha256: str,
    expected_head: str,
    signing_key: str,
    observed_at: str,
    starting_audit_count: int = 0,
    fault_mode: str = "NONE",
) -> dict[str, object]:
    """Run one closed fixture observation and verify its terminal evidence."""
    lineage.require(fault_mode in FAULT_MODES, "REHEARSAL_FAULT_MODE_INVALID")
    lineage.require(
        type(starting_audit_count) is int
        and 0
        <= starting_audit_count
        <= lineage.INTERNAL_AUDIT_CAP - lineage.INTERNAL_AUDIT_BUDGET,
        "INTERNAL_AUDIT_CAPACITY_INSUFFICIENT",
    )
    verified = lineage.verify_package(
        directory,
        expected_manifest_sha256=expected_manifest_sha256,
        expected_head=expected_head,
    )
    before = _snapshot(
        verified,
        touchpoints=0,
        source_events=0,
        receipts=0,
        audits=starting_audit_count,
        audit_types=[],
    )
    after = _snapshot(
        verified,
        touchpoints=1,
        source_events=1,
        receipts=1,
        audits=starting_audit_count + lineage.INTERNAL_AUDIT_BUDGET,
        audit_types=list(lineage.AUDIT_TYPES),
    )
    receipt = _signed_receipt(
        verified, signing_key=signing_key, observed_at=observed_at
    )
    verification = {
        "receipt_id": receipt["receipt_id"],
        "valid": True,
        "key_id": receipt["key_id"],
        "detail": "Signature is valid.",
    }
    raw_response = lineage.canonical_bytes(receipt) + b"\n"
    if fault_mode == "RAW_RECEIPT_MISMATCH":
        raw_response = b"{}\n"
    begin = lineage.begin_offline_fixture(
        directory,
        expected_manifest_sha256=expected_manifest_sha256,
        expected_head=expected_head,
        before=before,
    )
    completion = lineage.complete_offline_fixture(
        directory,
        expected_manifest_sha256=expected_manifest_sha256,
        expected_head=expected_head,
        before=before,
        after=after,
        status_code=200,
        raw_response=raw_response,
        semantic_receipt=receipt,
        receipt_verification=verification,
        verification_keys={REHEARSAL_KEY_ID: signing_key},
    )
    terminal = lineage.verify_offline_terminal_journal(
        directory,
        expected_manifest_sha256=expected_manifest_sha256,
        expected_head=expected_head,
    )
    return {
        "status": "OFFLINE_END_TO_END_REHEARSAL_PASS",
        "operation_id": verified["bindings"]["operation_id"],
        "package_manifest_sha256": expected_manifest_sha256,
        "begin": begin,
        "completion": completion,
        "terminal": terminal,
        "fault_mode": fault_mode,
        "fixture_only": True,
        "module_post_attempts": 0,
        "observed_fixture_attempts": 1,
        "automatic_retry": False,
        "automatic_rollback_after_post": False,
        "production_interaction": "NOT_PERFORMED_BY_THIS_MODULE",
    }


def rehearse_offline_runtime_path(
    sandbox_parent: Path | str,
    *,
    base_package: Path | str,
    runtime_review_package: Path | str,
    expected_base_manifest_sha256: str,
    expected_runtime_manifest_sha256: str,
    expected_head: str,
    runtime_binding: object,
    candidate_archive: bytes,
    rollback_archive: bytes,
    signing_key: str,
    observed_at: str,
    starting_audit_count: int = 0,
    fault_mode: str = "NONE",
) -> dict[str, object]:
    """Exercise the sealed four-component path without running its command."""
    lineage.require(
        fault_mode in executor_runtime.FAULT_MODES,
        "OFFLINE_FAULT_MODE_INVALID",
    )
    lineage.require(
        type(starting_audit_count) is int
        and 0
        <= starting_audit_count
        <= lineage.INTERNAL_AUDIT_CAP - lineage.INTERNAL_AUDIT_BUDGET,
        "INTERNAL_AUDIT_CAPACITY_INSUFFICIENT",
    )
    checked_observed = lineage._aware_timestamp(
        observed_at, "REHEARSAL_TIMESTAMP_INVALID"
    )
    observed = datetime.fromisoformat(checked_observed.replace("Z", "+00:00"))
    lineage.require(
        observed.utcoffset() == timedelta(0), "REHEARSAL_TIMESTAMP_NOT_UTC"
    )
    verified_review = builder.verify_runtime_review_package(
        runtime_review_package,
        expected_manifest_sha256=expected_runtime_manifest_sha256,
        base_package=base_package,
        expected_base_manifest_sha256=expected_base_manifest_sha256,
        expected_head=expected_head,
    )
    expected_binding = builder.runtime_binding_from_verified(verified_review)
    checked_binding = executor_runtime.verify_runtime_binding(runtime_binding)
    lineage.require(
        lineage.canonical_digest(expected_binding)
        == lineage.canonical_digest(checked_binding),
        "REHEARSAL_RUNTIME_BINDING_MISMATCH",
    )
    base_verified = verified_review["base"]
    before = _snapshot(
        base_verified,
        touchpoints=0,
        source_events=0,
        receipts=0,
        audits=starting_audit_count,
        audit_types=[],
    )
    after = _snapshot(
        base_verified,
        touchpoints=1,
        source_events=1,
        receipts=1,
        audits=starting_audit_count + lineage.INTERNAL_AUDIT_BUDGET,
        audit_types=list(lineage.AUDIT_TYPES),
    )
    post_observed = observed + timedelta(seconds=5)
    receipt = _signed_receipt(
        base_verified,
        signing_key=signing_key,
        observed_at=post_observed.isoformat().replace("+00:00", "Z"),
    )
    raw_response = lineage.canonical_bytes(receipt) + b"\n"
    scenario = {
        "schema": executor_runtime.SCENARIO_SCHEMA,
        "lineage": lineage.LINEAGE,
        "operation_id": checked_binding["operation_id"],
        "mode": "OFFLINE_SANDBOX_ONLY",
        "fault_mode": fault_mode,
        "scope_start_utc": (observed - timedelta(seconds=5)).isoformat().replace(
            "+00:00", "Z"
        ),
        "preflight_at_utc": observed.isoformat().replace("+00:00", "Z"),
        "claimed_at_utc": (observed + timedelta(seconds=1)).isoformat().replace(
            "+00:00", "Z"
        ),
        "staged_at_utc": (observed + timedelta(seconds=2)).isoformat().replace(
            "+00:00", "Z"
        ),
        "pre_post_intent_at_utc": (
            observed + timedelta(seconds=4)
        ).isoformat().replace("+00:00", "Z"),
        "post_observed_at_utc": post_observed.isoformat().replace("+00:00", "Z"),
        "completed_at_utc": (observed + timedelta(seconds=6)).isoformat().replace(
            "+00:00", "Z"
        ),
        "scope_end_utc": (observed + timedelta(seconds=10)).isoformat().replace(
            "+00:00", "Z"
        ),
        "current_utc": (observed + timedelta(seconds=6)).isoformat().replace(
            "+00:00", "Z"
        ),
        "before": before,
        "after": after,
        "status_code": 200,
        "raw_response": raw_response,
        "semantic_receipt": receipt,
        "receipt_verification": {
            "receipt_id": receipt["receipt_id"],
            "valid": True,
            "key_id": receipt["key_id"],
            "detail": "Signature is valid.",
        },
        "verification_keys": {REHEARSAL_KEY_ID: signing_key},
    }
    result = executor_runtime.run_offline_state_machine(
        sandbox_parent,
        base_package=base_package,
        runtime_binding=checked_binding,
        readonly_request=verified_review["request"],
        scenario=scenario,
        candidate_archive=candidate_archive,
        rollback_archive=rollback_archive,
    )
    terminal_verification = executor_runtime.verify_offline_runtime_terminal(
        sandbox_parent,
        runtime_binding=checked_binding,
    )
    lineage.require(
        result["terminal_state"]
        == executor_runtime.expected_terminal_state(fault_mode),
        "OFFLINE_MODEL_TERMINAL_MISMATCH",
    )
    lineage.require(
        terminal_verification["terminal_state"] == result["terminal_state"],
        "OFFLINE_TERMINAL_VERIFICATION_MISMATCH",
    )
    return {
        "status": (
            "OFFLINE_RUNTIME_PATH_REHEARSAL_PASS"
            if result["terminal_state"] == "PASS"
            else "OFFLINE_RUNTIME_PATH_REHEARSAL_TERMINAL"
        ),
        "operation_id": checked_binding["operation_id"],
        "base_package_manifest_sha256": expected_base_manifest_sha256,
        "runtime_review_manifest_sha256": expected_runtime_manifest_sha256,
        "terminal": result,
        "terminal_verification": terminal_verification,
        "fault_mode": fault_mode,
        "generated_command_executed": False,
        "simulated_post_attempts": result["simulated_post_attempts"],
        "real_post_attempts": 0,
        "automatic_retry": False,
        "automatic_rollback_after_post": False,
        "fixture_only": True,
        "production_interaction": "NOT_PERFORMED_BY_THIS_MODULE",
    }
