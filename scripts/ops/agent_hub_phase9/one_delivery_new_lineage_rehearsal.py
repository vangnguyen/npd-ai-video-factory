"""Closed in-process rehearsal for a built new-lineage review package.

The rehearsal has no pluggable transport or callback and performs no network,
subprocess, SSH, provider, production, image, or delivery action.  It creates
only local fixture evidence next to the supplied review package.
"""
from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

import one_delivery_new_lineage as lineage


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
