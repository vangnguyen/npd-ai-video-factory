"""Offline-only contract for a new Phase-9 one-delivery lineage.

This is not recovered R4 code and it cannot create an R5 package, contact a
host, claim a production operation, stage an image, or perform a POST.  It
validates a source-review package and evaluates caller-supplied local fixture
evidence.  There is deliberately no transport or callback injection point.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime
from pathlib import Path, PurePosixPath
import re
from typing import Mapping
from uuid import UUID, uuid4

from gate2_digest_contract import Gate2DigestContractError, verify_evidence


LINEAGE = "AH_P9_ONE_DELIVERY_NEW_LINEAGE_V1"
OPERATION_PREFIX = "AH-P9-ONE-DELIVERY-NL1-"
MANIFEST_SCHEMA = "npd.agent-hub.phase9.one-delivery-new-lineage-package.v1"
READBACK_SCHEMA = "npd.agent-hub.phase9.one-delivery-readback-snapshot.v1"
JOURNAL_SCHEMA = "npd.agent-hub.phase9.one-delivery-offline-journal.v1"
OFFLINE_EVIDENCE_DIRECTORY = ".agent-hub-offline-evidence"
HISTORICAL_R4_OPERATION = (
    "AH-P9-ONE-DELIVERY-6369ae1d-4b41-4d47-8463-24deacfec75c"
)
HASH = re.compile(r"^[0-9a-f]{64}$")
HEAD = re.compile(r"^[0-9a-f]{40}$")
PRODUCER = re.compile(r"^[a-z][a-z0-9_.-]{1,79}$")
CAMPAIGN_ID = re.compile(r"^CMP-[A-Z0-9]{2,12}-[A-Z0-9]{2,20}-\d{6}-\d{2}$")
DELIVERY_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{2,119}$")
SUBJECT_REF = re.compile(r"^lead:[A-Za-z0-9_-]{1,100}$")
RECEIPT_ID = re.compile(r"^adr_[0-9a-f]{24}$")
SIGNATURE = re.compile(r"^hmac-sha256:[0-9a-f]{64}$")
AUDIT_TYPES = ["source_touchpoints_ingested", "signed_delivery_received"]
INTERNAL_AUDIT_CAP = 2000
INTERNAL_AUDIT_BUDGET = 2
REQUIRED_ARTIFACTS = {
    "OPERATION_BINDINGS.json",
    "DELIVERY_BINDING.json",
    "DELIVERY_ENVELOPE.json",
    "CANDIDATE_IMAGE.json",
    "PREFLIGHT_CONTRACT.json",
    "RECOVERY_CONTRACT.json",
    "READBACK_CONTRACT.json",
    "CAMPAIGN_DIGEST_EVIDENCE.json",
}


class NewLineageStop(ValueError):
    """The package or local fixture evidence failed closed."""


class OfflineOwnerReviewHold(NewLineageStop):
    """A post-observation fixture result is ambiguous and cannot auto-recover."""

    def __init__(self, original_cause: str, journal_cause: str | None = None) -> None:
        self.original_cause = original_cause
        self.journal_cause = journal_cause
        message = f"POST_OUTCOME_AMBIGUOUS_HOLD_OWNER_REVIEW:{original_cause}"
        if journal_cause is not None:
            message += f":{journal_cause}"
        super().__init__(message)


def require(condition: bool, reason: str) -> None:
    if condition is not True:
        raise NewLineageStop(reason)


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def loads_strict(raw: bytes) -> object:
    try:
        return json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                NewLineageStop("NONFINITE_JSON")
            ),
        )
    except NewLineageStop:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise NewLineageStop("JSON_INVALID") from None


def load_json(path: Path) -> object:
    try:
        return loads_strict(path.read_bytes())
    except OSError:
        raise NewLineageStop("ARTIFACT_UNREADABLE") from None


def canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise NewLineageStop("CANONICAL_JSON_INVALID") from None


def canonical_digest(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        raise NewLineageStop("ARTIFACT_UNREADABLE") from None
    return digest.hexdigest()


def parse_operation_id(value: object) -> str:
    require(isinstance(value, str), "NEW_LINEAGE_OPERATION_ID_INVALID")
    require(value != HISTORICAL_R4_OPERATION, "HISTORICAL_R4_OPERATION_RETIRED")
    require(value.startswith(OPERATION_PREFIX), "NEW_LINEAGE_OPERATION_ID_INVALID")
    suffix = value[len(OPERATION_PREFIX):]
    try:
        identifier = UUID(suffix)
    except (ValueError, TypeError, AttributeError):
        raise NewLineageStop("NEW_LINEAGE_OPERATION_ID_INVALID") from None
    require(
        str(identifier) == suffix and identifier.version == 4,
        "NEW_LINEAGE_OPERATION_ID_INVALID",
    )
    return value


def safe_artifact(package: Path, relative: object) -> Path:
    require(isinstance(relative, str) and bool(relative), "ARTIFACT_PATH_INVALID")
    pure = PurePosixPath(relative)
    require(
        not pure.is_absolute()
        and not any(part in {"", ".", ".."} for part in pure.parts)
        and "\\" not in relative
        and ":" not in relative,
        "ARTIFACT_PATH_INVALID",
    )
    candidate = package.joinpath(*pure.parts)
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        raise NewLineageStop("ARTIFACT_MISSING") from None
    require(resolved.is_relative_to(package), "ARTIFACT_PATH_ESCAPE")
    require(
        resolved.is_file()
        and not any(
            package.joinpath(*pure.parts[:index]).is_symlink()
            for index in range(1, len(pure.parts) + 1)
        ),
        "ARTIFACT_FILE_INVALID",
    )
    return resolved


def _exact_fields(value: object, fields: set[str], reason: str) -> Mapping[str, object]:
    require(isinstance(value, Mapping) and set(value) == fields, reason)
    return value


def _string(value: object, *, minimum: int, maximum: int, reason: str) -> str:
    require(isinstance(value, str) and minimum <= len(value) <= maximum, reason)
    return value


def _aware_timestamp(value: object, reason: str) -> str:
    raw = _string(value, minimum=1, maximum=80, reason=reason)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise NewLineageStop(reason) from None
    require(parsed.tzinfo is not None and parsed.utcoffset() is not None, reason)
    return raw


def _pseudonymous(value: object, *, minimum: int, maximum: int, reason: str) -> str:
    raw = _string(value, minimum=minimum, maximum=maximum, reason=reason)
    require(
        "@" not in raw and re.fullmatch(r"\+?\d[\d\s().-]{7,}", raw) is None,
        reason,
    )
    return raw


def _verify_delivery(binding: Mapping[str, object], envelope: Mapping[str, object]) -> None:
    _exact_fields(
        binding,
        {
            "cohort",
            "delivery_id",
            "source_event_id",
            "occurred_at",
            "source_record_sha256",
            "source_audit_sha256",
            "delivery_payload_sha256",
        },
        "DELIVERY_BINDING_SCHEMA_INVALID",
    )
    _exact_fields(
        envelope,
        {
            "delivery_id",
            "producer",
            "source_system",
            "attempt_number",
            "max_attempts",
            "sent_at",
            "events",
            "metadata",
        },
        "DELIVERY_ENVELOPE_SCHEMA_INVALID",
    )
    cohort = binding.get("cohort")
    _exact_fields(
        cohort,
        {
            "classification",
            "canonical_campaign_id",
            "subject_ref",
            "owner_id",
            "owner_approval_sha256",
            "non_customer_proof_sha256",
            "scope",
            "customer_contact",
            "commercial_attribution",
            "automation_enabled",
            "reporting_exclusions",
        },
        "COHORT_BINDING_INVALID",
    )
    exclusions = cohort.get("reporting_exclusions")
    require(
        cohort.get("classification") == "phase9_internal_non_customer"
        and isinstance(cohort.get("canonical_campaign_id"), str)
        and bool(CAMPAIGN_ID.fullmatch(cohort["canonical_campaign_id"]))
        and isinstance(cohort.get("subject_ref"), str)
        and bool(SUBJECT_REF.fullmatch(cohort["subject_ref"]))
        and isinstance(cohort.get("owner_id"), str)
        and 1 <= len(cohort["owner_id"]) <= 200
        and cohort.get("scope")
        == "phase9_one_internal_task_report_audit_one_nba_review"
        and cohort.get("customer_contact") is False
        and cohort.get("commercial_attribution") is False
        and cohort.get("automation_enabled") is False
        and isinstance(exclusions, Mapping)
        and set(exclusions)
        == {
            "commercial_leads",
            "sales_revenue_attribution",
            "customer_sla_metrics",
            "provider_spend",
            "external_notifications",
        }
        and all(value is True for value in exclusions.values())
        and bool(HASH.fullmatch(str(cohort.get("owner_approval_sha256", ""))))
        and bool(HASH.fullmatch(str(cohort.get("non_customer_proof_sha256", "")))),
        "COHORT_BOUNDARY_INVALID",
    )
    events = envelope.get("events")
    require(isinstance(events, list) and len(events) == 1, "ONE_DELIVERY_ONLY")
    event = events[0]
    _exact_fields(
        event,
        {
            "source_event_id",
            "source_system",
            "event_type",
            "occurred_at",
            "channel",
            "canonical_campaign_id",
            "source_account_id",
            "source_campaign_id",
            "source_adset_id",
            "source_ad_group_id",
            "source_ad_id",
            "lead_id",
            "opportunity_id",
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "utm_content",
            "landing_page",
            "metadata",
        },
        "DELIVERY_EVENT_SCHEMA_INVALID",
    )
    delivery_id = _pseudonymous(
        binding.get("delivery_id"), minimum=3, maximum=120,
        reason="DELIVERY_BINDING_SCHEMA_INVALID",
    )
    require(bool(DELIVERY_ID.fullmatch(delivery_id)), "DELIVERY_BINDING_SCHEMA_INVALID")
    source_event_id = _pseudonymous(
        binding.get("source_event_id"), minimum=2, maximum=200,
        reason="DELIVERY_BINDING_SCHEMA_INVALID",
    )
    occurred_at = _aware_timestamp(
        binding.get("occurred_at"), "DELIVERY_BINDING_SCHEMA_INVALID"
    )
    _aware_timestamp(envelope.get("sent_at"), "DELIVERY_ENVELOPE_SCHEMA_INVALID")
    producer = _string(
        envelope.get("producer"), minimum=2, maximum=80,
        reason="DELIVERY_ENVELOPE_SCHEMA_INVALID",
    )
    require(bool(PRODUCER.fullmatch(producer)), "DELIVERY_ENVELOPE_SCHEMA_INVALID")
    _pseudonymous(
        event.get("source_event_id"), minimum=2, maximum=200,
        reason="DELIVERY_EVENT_SCHEMA_INVALID",
    )
    _aware_timestamp(event.get("occurred_at"), "DELIVERY_EVENT_SCHEMA_INVALID")
    _string(event.get("channel"), minimum=2, maximum=80, reason="DELIVERY_EVENT_SCHEMA_INVALID")
    lead_id = _pseudonymous(
        event.get("lead_id"), minimum=1, maximum=100,
        reason="DELIVERY_EVENT_SCHEMA_INVALID",
    )
    require(
        bool(re.fullmatch(r"[A-Za-z0-9_-]{1,100}", lead_id)),
        "DELIVERY_EVENT_SCHEMA_INVALID",
    )
    require(
        envelope.get("attempt_number") == 1
        and type(envelope.get("attempt_number")) is int
        and envelope.get("max_attempts") == 1
        and type(envelope.get("max_attempts")) is int,
        "ONE_ATTEMPT_NO_RETRY_REQUIRED",
    )
    require(
        envelope.get("delivery_id") == delivery_id
        and envelope.get("metadata") == {}
        and bool(HASH.fullmatch(str(binding.get("source_record_sha256", ""))))
        and bool(HASH.fullmatch(str(binding.get("source_audit_sha256", ""))))
        and bool(HASH.fullmatch(str(binding.get("delivery_payload_sha256", ""))))
        and envelope.get("source_system") == "espocrm"
        and event.get("source_system") == "espocrm"
        and event.get("source_event_id") == source_event_id
        and event.get("occurred_at") == occurred_at
        and event.get("event_type") == "lead_created"
        and event.get("canonical_campaign_id") == cohort.get("canonical_campaign_id")
        and f"lead:{lead_id}" == cohort.get("subject_ref")
        and event.get("opportunity_id") is None,
        "DELIVERY_BINDING_MISMATCH",
    )
    require(
        all(
            event.get(name) is None
            for name in (
                "source_account_id",
                "source_campaign_id",
                "source_adset_id",
                "source_ad_group_id",
                "source_ad_id",
                "utm_source",
                "utm_medium",
                "utm_campaign",
                "utm_content",
                "landing_page",
            )
        ),
        "AMBIGUOUS_CAMPAIGN_IDENTITY_DENIED",
    )
    metadata = event.get("metadata")
    require(
        isinstance(metadata, Mapping)
        and set(metadata)
        == {"phase9_internal_cohort", "source_record_sha256", "source_audit_sha256"}
        and metadata.get("phase9_internal_cohort") == cohort
        and metadata.get("source_record_sha256") == binding.get("source_record_sha256")
        and metadata.get("source_audit_sha256") == binding.get("source_audit_sha256"),
        "DELIVERY_EVENT_EVIDENCE_MISMATCH",
    )
    require(
        binding.get("delivery_payload_sha256") == canonical_digest(envelope),
        "DELIVERY_PAYLOAD_DIGEST_MISMATCH",
    )


def _verify_contracts(values: dict[str, Mapping[str, object]], head: str) -> None:
    image = _exact_fields(
        values["CANDIDATE_IMAGE.json"],
        {
            "schema",
            "lineage",
            "application_source_head",
            "candidate_docker_config_sha256",
            "rollback_docker_config_sha256",
            "candidate_staged",
            "image_loaded",
            "production_build_authorized",
        },
        "CANDIDATE_IMAGE_SCHEMA_INVALID",
    )
    require(
        image.get("schema") == "npd.agent-hub.phase9.one-delivery-image-binding.v1"
        and image.get("lineage") == LINEAGE
        and image.get("application_source_head") == head
        and bool(HASH.fullmatch(str(image.get("candidate_docker_config_sha256", ""))))
        and bool(HASH.fullmatch(str(image.get("rollback_docker_config_sha256", ""))))
        and image.get("candidate_staged") is False
        and image.get("image_loaded") is False
        and image.get("production_build_authorized") is False,
        "CANDIDATE_IMAGE_BOUNDARY_INVALID",
    )
    preflight = _exact_fields(
        values["PREFLIGHT_CONTRACT.json"],
        {
            "schema",
            "lineage",
            "mode",
            "production_probe_performed",
            "claim_absent",
            "candidate_staged",
            "delivery_absent",
            "fresh_jit_required",
            "video_factory_db0_counter_evidence",
            "production_qualification",
        },
        "PREFLIGHT_CONTRACT_SCHEMA_INVALID",
    )
    require(
        preflight
        == {
            "schema": "npd.agent-hub.phase9.one-delivery-preflight-contract.v1",
            "lineage": LINEAGE,
            "mode": "OFFLINE_CONTRACT_ONLY",
            "production_probe_performed": False,
            "claim_absent": True,
            "candidate_staged": False,
            "delivery_absent": True,
            "fresh_jit_required": True,
            "video_factory_db0_counter_evidence": "OUT_OF_SCOPE_NOT_COLLECTED",
            "production_qualification": "BLOCKED_EXTERNAL_READONLY_EVIDENCE_REQUIRED",
        },
        "PREFLIGHT_CONTRACT_BOUNDARY_INVALID",
    )
    recovery = _exact_fields(
        values["RECOVERY_CONTRACT.json"],
        {
            "schema",
            "lineage",
            "max_attempts",
            "automatic_retry",
            "pre_post_failure",
            "post_outcome_ambiguous",
            "automatic_rollback_after_post",
            "rollback_source_status",
            "owner_recovery_gate_required",
        },
        "RECOVERY_CONTRACT_SCHEMA_INVALID",
    )
    require(
        recovery
        == {
            "schema": "npd.agent-hub.phase9.one-delivery-recovery-contract.v1",
            "lineage": LINEAGE,
            "max_attempts": 1,
            "automatic_retry": False,
            "pre_post_failure": "ABORT_BEFORE_POST",
            "post_outcome_ambiguous": "HOLD_OWNER_REVIEW",
            "automatic_rollback_after_post": False,
            "rollback_source_status": "NEW_LINEAGE_REQUIRED_NOT_HISTORICAL",
            "owner_recovery_gate_required": True,
        },
        "RECOVERY_CONTRACT_BOUNDARY_INVALID",
    )
    readback = _exact_fields(
        values["READBACK_CONTRACT.json"],
        {
            "schema",
            "lineage",
            "touchpoint_delta",
            "source_event_match_delta",
            "delivery_receipt_delta",
            "campaign_audit_delta",
            "latest_campaign_audit_types",
            "dead_letter_delta",
            "receipt_valid_required",
            "internal_audit_cap",
            "minimum_capacity_before_post",
        },
        "READBACK_CONTRACT_SCHEMA_INVALID",
    )
    require(
        readback
        == {
            "schema": "npd.agent-hub.phase9.one-delivery-readback-contract.v1",
            "lineage": LINEAGE,
            "touchpoint_delta": 1,
            "source_event_match_delta": 1,
            "delivery_receipt_delta": 1,
            "campaign_audit_delta": INTERNAL_AUDIT_BUDGET,
            "latest_campaign_audit_types": AUDIT_TYPES,
            "dead_letter_delta": 0,
            "receipt_valid_required": True,
            "internal_audit_cap": INTERNAL_AUDIT_CAP,
            "minimum_capacity_before_post": INTERNAL_AUDIT_BUDGET,
        },
        "READBACK_CONTRACT_BOUNDARY_INVALID",
    )


def verify_package(
    directory: Path | str,
    *,
    expected_manifest_sha256: str | None = None,
    expected_head: str | None = None,
) -> dict[str, object]:
    package = Path(directory).resolve(strict=True)
    require(package.is_dir(), "PACKAGE_DIRECTORY_INVALID")
    manifest_path = package / "PACKAGE_MANIFEST.json"
    if expected_manifest_sha256 is not None:
        require(bool(HASH.fullmatch(expected_manifest_sha256)), "MANIFEST_ANCHOR_INVALID")
        require(
            sha256_file(manifest_path) == expected_manifest_sha256,
            "PACKAGE_MANIFEST_MISMATCH",
        )
    manifest = _exact_fields(
        load_json(manifest_path),
        {
            "schema",
            "lineage",
            "mode",
            "historical_equivalence",
            "r5_created",
            "production_capable",
            "execution_approval",
            "operation_id",
            "candidate_head",
            "artifacts",
        },
        "PACKAGE_MANIFEST_SCHEMA_INVALID",
    )
    require(
        manifest.get("schema") == MANIFEST_SCHEMA
        and manifest.get("lineage") == LINEAGE
        and manifest.get("mode") == "OFFLINE_REVIEW_ONLY"
        and manifest.get("historical_equivalence") is False
        and manifest.get("r5_created") is False
        and manifest.get("production_capable") is False
        and manifest.get("execution_approval") == "NOT_GRANTED",
        "OFFLINE_AUTHORITY_BOUNDARY_INVALID",
    )
    operation_id = parse_operation_id(manifest.get("operation_id"))
    head = manifest.get("candidate_head")
    require(isinstance(head, str) and bool(HEAD.fullmatch(head)), "CANDIDATE_HEAD_INVALID")
    if expected_head is not None:
        require(head == expected_head, "CANDIDATE_HEAD_MISMATCH")
    entries = manifest.get("artifacts")
    require(isinstance(entries, list) and bool(entries), "ARTIFACT_INVENTORY_INVALID")
    listed: dict[str, Path] = {}
    for entry in entries:
        _exact_fields(entry, {"path", "sha256", "length_bytes"}, "ARTIFACT_ENTRY_INVALID")
        name = entry.get("path")
        require(
            isinstance(name, str) and name.casefold() not in {key.casefold() for key in listed},
            "DUPLICATE_ARTIFACT",
        )
        artifact = safe_artifact(package, name)
        require(
            type(entry.get("length_bytes")) is int
            and entry["length_bytes"] == artifact.stat().st_size
            and bool(HASH.fullmatch(str(entry.get("sha256", ""))))
            and entry["sha256"] == sha256_file(artifact),
            "ARTIFACT_HASH_OR_LENGTH_MISMATCH",
        )
        listed[name] = artifact
    require(REQUIRED_ARTIFACTS <= set(listed), "REQUIRED_ARTIFACT_MISSING")
    require(set(listed) == REQUIRED_ARTIFACTS, "ARTIFACT_ALLOWLIST_MISMATCH")
    actual = {
        path.relative_to(package).as_posix()
        for path in package.rglob("*")
        if path.is_file() and path != manifest_path
    }
    require(actual == set(listed), "ARTIFACT_INVENTORY_MISMATCH")
    values = {name: load_json(listed[name]) for name in REQUIRED_ARTIFACTS}
    bindings = _exact_fields(
        values["OPERATION_BINDINGS.json"],
        {
            "schema",
            "lineage",
            "operation_id",
            "candidate_head",
            "campaign_id",
            "delivery_id",
            "source_event_id",
            "subject_ref",
            "campaign_raw_transport_sha256",
            "campaign_semantic_model_sha256",
            "delivery_binding_sha256",
            "delivery_envelope_sha256",
            "candidate_image_sha256",
            "preflight_contract_sha256",
            "recovery_contract_sha256",
            "readback_contract_sha256",
            "campaign_digest_evidence_sha256",
        },
        "OPERATION_BINDINGS_SCHEMA_INVALID",
    )
    require(
        bindings.get("schema") == "npd.agent-hub.phase9.one-delivery-bindings.v1"
        and bindings.get("lineage") == LINEAGE
        and bindings.get("operation_id") == operation_id
        and bindings.get("candidate_head") == head,
        "OPERATION_BINDING_MISMATCH",
    )
    for name, field in {
        "DELIVERY_BINDING.json": "delivery_binding_sha256",
        "DELIVERY_ENVELOPE.json": "delivery_envelope_sha256",
        "CANDIDATE_IMAGE.json": "candidate_image_sha256",
        "PREFLIGHT_CONTRACT.json": "preflight_contract_sha256",
        "RECOVERY_CONTRACT.json": "recovery_contract_sha256",
        "READBACK_CONTRACT.json": "readback_contract_sha256",
        "CAMPAIGN_DIGEST_EVIDENCE.json": "campaign_digest_evidence_sha256",
    }.items():
        require(bindings.get(field) == sha256_file(listed[name]), "OPERATION_ARTIFACT_BINDING_MISMATCH")
    binding = _exact_fields(values["DELIVERY_BINDING.json"], {
        "cohort", "delivery_id", "source_event_id", "occurred_at",
        "source_record_sha256", "source_audit_sha256", "delivery_payload_sha256",
    }, "DELIVERY_BINDING_SCHEMA_INVALID")
    envelope = _exact_fields(values["DELIVERY_ENVELOPE.json"], {
        "delivery_id", "producer", "source_system", "attempt_number",
        "max_attempts", "sent_at", "events", "metadata",
    }, "DELIVERY_ENVELOPE_SCHEMA_INVALID")
    _verify_delivery(binding, envelope)
    cohort = binding["cohort"]
    require(
        bindings.get("campaign_id") == cohort.get("canonical_campaign_id")
        and bindings.get("delivery_id") == binding.get("delivery_id")
        and bindings.get("source_event_id") == binding.get("source_event_id")
        and bindings.get("subject_ref") == cohort.get("subject_ref"),
        "OPERATION_DELIVERY_BINDING_MISMATCH",
    )
    _verify_contracts(values, head)
    digest_evidence = values["CAMPAIGN_DIGEST_EVIDENCE.json"]
    try:
        verify_evidence(
            digest_evidence,
            expected_campaign_id=bindings["campaign_id"],
            expected_raw_transport_sha256=bindings["campaign_raw_transport_sha256"],
            expected_semantic_model_sha256=bindings["campaign_semantic_model_sha256"],
        )
    except (Gate2DigestContractError, AttributeError):
        raise NewLineageStop("CAMPAIGN_DIGEST_EVIDENCE_INVALID") from None
    return {
        "package": package,
        "manifest": dict(manifest),
        "manifest_sha256": sha256_file(manifest_path),
        "bindings": dict(bindings),
        "delivery_binding": dict(binding),
        "delivery_envelope": dict(envelope),
        "readback_contract": dict(values["READBACK_CONTRACT.json"]),
        "campaign_digest_evidence": dict(digest_evidence),
    }


def _verify_snapshot(value: object, bindings: Mapping[str, object]) -> Mapping[str, object]:
    snapshot = _exact_fields(
        value,
        {
            "schema",
            "lineage",
            "campaign_id",
            "delivery_id",
            "source_event_id",
            "subject_touchpoint_count",
            "source_event_match_count",
            "delivery_receipt_match_count",
            "campaign_audit_count",
            "latest_campaign_audit_types",
            "dead_letter_match_count",
            "counts_are_exact",
            "query_limit_applied",
            "internal_audit_cap",
            "runtime_mode",
            "scheduler_enabled",
        },
        "READBACK_SNAPSHOT_SCHEMA_INVALID",
    )
    require(
        snapshot.get("schema") == READBACK_SCHEMA
        and snapshot.get("lineage") == LINEAGE
        and snapshot.get("campaign_id") == bindings.get("campaign_id")
        and snapshot.get("delivery_id") == bindings.get("delivery_id")
        and snapshot.get("source_event_id") == bindings.get("source_event_id")
        and snapshot.get("counts_are_exact") is True
        and snapshot.get("query_limit_applied") is False
        and snapshot.get("internal_audit_cap") == INTERNAL_AUDIT_CAP
        and snapshot.get("runtime_mode") == "phase9_delivery"
        and snapshot.get("scheduler_enabled") is False,
        "READBACK_SNAPSHOT_BINDING_INVALID",
    )
    for name in (
        "subject_touchpoint_count",
        "source_event_match_count",
        "delivery_receipt_match_count",
        "campaign_audit_count",
        "dead_letter_match_count",
    ):
        require(type(snapshot.get(name)) is int and snapshot[name] >= 0, "READBACK_COUNT_INVALID")
    require(isinstance(snapshot.get("latest_campaign_audit_types"), list), "READBACK_AUDIT_INVALID")
    return snapshot


def _verify_receipt(
    receipt: object,
    receipt_verification: object,
    verification_keys: object,
    verified: Mapping[str, object],
) -> Mapping[str, object]:
    value = _exact_fields(
        receipt,
        {
            "receipt_id", "delivery_id", "producer", "source_system",
            "attempt_number", "max_attempts", "outcome", "payload_digest",
            "snapshot_id", "received", "resolved", "inserted", "duplicates",
            "unknown", "conflicts", "retry_allowed", "next_retry_at",
            "dead_lettered", "error_code", "received_at", "key_id", "signature",
            "shadow_mode", "external_writes_enabled",
        },
        "DELIVERY_RECEIPT_SCHEMA_INVALID",
    )
    bindings = verified["bindings"]
    envelope = verified["delivery_envelope"]
    receipt_id = value.get("receipt_id")
    key_id = value.get("key_id")
    signature = value.get("signature")
    require(
        isinstance(receipt_id, str) and bool(RECEIPT_ID.fullmatch(receipt_id)),
        "DELIVERY_RECEIPT_SCHEMA_INVALID",
    )
    require(
        isinstance(key_id, str) and 3 <= len(key_id) <= 80
        and isinstance(signature, str) and bool(SIGNATURE.fullmatch(signature)),
        "DELIVERY_RECEIPT_SCHEMA_INVALID",
    )
    _aware_timestamp(value.get("received_at"), "DELIVERY_RECEIPT_SCHEMA_INVALID")
    snapshot_id = value.get("snapshot_id")
    require(snapshot_id is None or isinstance(snapshot_id, str), "DELIVERY_RECEIPT_SCHEMA_INVALID")
    for field in (
        "attempt_number", "max_attempts", "received", "resolved", "inserted",
        "duplicates", "unknown", "conflicts",
    ):
        require(type(value.get(field)) is int and value[field] >= 0, "DELIVERY_RECEIPT_SCHEMA_INVALID")
    require(
        value.get("delivery_id") == bindings["delivery_id"]
        and value.get("producer") == envelope["producer"]
        and value.get("source_system") == envelope["source_system"]
        and value.get("attempt_number") == 1
        and value.get("max_attempts") == 1
        and value.get("outcome") == "accepted"
        and value.get("payload_digest")
        == verified["delivery_binding"]["delivery_payload_sha256"]
        and value.get("received") == 1
        and value.get("resolved") == 1
        and value.get("inserted") == 1
        and value.get("duplicates") == 0
        and value.get("unknown") == 0
        and value.get("conflicts") == 0
        and value.get("retry_allowed") is False
        and value.get("next_retry_at") is None
        and value.get("dead_lettered") is False
        and value.get("error_code") is None
        and value.get("shadow_mode") is True
        and value.get("external_writes_enabled") is False,
        "DELIVERY_RECEIPT_INVALID",
    )
    verification = _exact_fields(
        receipt_verification,
        {"receipt_id", "valid", "key_id", "detail"},
        "RECEIPT_VERIFICATION_SCHEMA_INVALID",
    )
    require(
        verification.get("receipt_id") == receipt_id
        and verification.get("key_id") == key_id
        and verification.get("valid") is True
        and verification.get("detail") == "Signature is valid.",
        "RECEIPT_VERIFICATION_INVALID",
    )
    require(isinstance(verification_keys, Mapping), "RECEIPT_KEYRING_INVALID")
    key = verification_keys.get(key_id)
    require(isinstance(key, str) and len(key) >= 32, "RECEIPT_KEY_UNKNOWN")
    unsigned = {name: item for name, item in value.items() if name != "signature"}
    expected = "hmac-sha256:" + hmac.new(
        key.encode("utf-8"), canonical_bytes(unsigned), hashlib.sha256
    ).hexdigest()
    require(hmac.compare_digest(signature, expected), "RECEIPT_SIGNATURE_INVALID")
    return value


def verify_readback(
    before: object,
    after: object,
    receipt: object,
    receipt_verification: object,
    verification_keys: object,
    verified: Mapping[str, object],
) -> dict[str, object]:
    bindings = verified["bindings"]
    contract = verified["readback_contract"]
    earlier = _verify_snapshot(before, bindings)
    later = _verify_snapshot(after, bindings)
    require(
        earlier["campaign_audit_count"] <= INTERNAL_AUDIT_CAP - INTERNAL_AUDIT_BUDGET,
        "INTERNAL_AUDIT_CAPACITY_INSUFFICIENT",
    )
    for name, delta_field in {
        "subject_touchpoint_count": "touchpoint_delta",
        "source_event_match_count": "source_event_match_delta",
        "delivery_receipt_match_count": "delivery_receipt_delta",
        "campaign_audit_count": "campaign_audit_delta",
        "dead_letter_match_count": "dead_letter_delta",
    }.items():
        require(
            later[name] - earlier[name] == contract[delta_field],
            "READBACK_DELTA_MISMATCH:" + name,
        )
    require(
        later["campaign_audit_count"] <= INTERNAL_AUDIT_CAP
        and later["latest_campaign_audit_types"] == AUDIT_TYPES,
        "READBACK_AUDIT_INVALID",
    )
    checked_receipt = _verify_receipt(
        receipt, receipt_verification, verification_keys, verified
    )
    return {
        "status": "PASS",
        "receipt_sha256": canonical_digest(checked_receipt),
        "before_sha256": canonical_digest(earlier),
        "after_sha256": canonical_digest(later),
    }


def _write_journal(path: Path, payload: Mapping[str, object]) -> None:
    require(not path.is_symlink(), "JOURNAL_SYMLINK_DENIED")
    temp = path.with_name(path.name + f".{uuid4().hex}.tmp")
    raw = canonical_bytes(payload) + b"\n"
    try:
        with temp.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        if hasattr(os, "O_DIRECTORY"):
            descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    except FileExistsError:
        raise NewLineageStop("JOURNAL_TEMP_COLLISION") from None
    except OSError:
        raise NewLineageStop("JOURNAL_DURABILITY_FAILURE") from None


def _journal_payload(
    verified: Mapping[str, object], state: str, *, observed_fixture_attempts: int, **extra
) -> dict[str, object]:
    return {
        "schema": JOURNAL_SCHEMA,
        "lineage": LINEAGE,
        "operation_id": verified["bindings"]["operation_id"],
        "package_manifest_sha256": verified["manifest_sha256"],
        "state": state,
        "module_post_attempts": 0,
        "observed_fixture_attempts": observed_fixture_attempts,
        "automatic_retry": False,
        "automatic_rollback_after_post": False,
        "production_authority": "NOT_GRANTED",
        **extra,
    }


def _verify_fixture_response(
    status_code: object,
    raw: object,
    receipt: object,
    verified: Mapping[str, object],
) -> tuple[dict, dict]:
    require(type(status_code) is int and status_code == 200, "POST_RESPONSE_NOT_ACCEPTED")
    require(type(raw) is bytes and len(raw) > 0, "ORIGINAL_HTTP_BYTES_REQUIRED")
    require(isinstance(receipt, Mapping), "SEMANTIC_RECEIPT_REQUIRED")
    parsed = loads_strict(raw)
    require(parsed == receipt, "RAW_HTTP_SEMANTIC_RECEIPT_MISMATCH")
    digest = {
        "raw_http_response_bytes": len(raw),
        "raw_http_response_sha256": hashlib.sha256(raw).hexdigest(),
        "semantic_receipt_sha256": canonical_digest(receipt),
        "raw_body_persisted": False,
    }
    require(receipt.get("delivery_id") == verified["bindings"]["delivery_id"], "DELIVERY_RECEIPT_INVALID")
    return dict(receipt), digest


def _evidence_paths(verified: Mapping[str, object], *, create: bool) -> tuple[Path, Path, Path]:
    package = verified["package"]
    require(isinstance(package, Path), "PACKAGE_DIRECTORY_INVALID")
    parent = package.parent.resolve(strict=True)
    root = parent / OFFLINE_EVIDENCE_DIRECTORY
    if create:
        try:
            root.mkdir(mode=0o700, exist_ok=True)
        except OSError:
            raise NewLineageStop("OFFLINE_EVIDENCE_STORE_UNAVAILABLE") from None
    require(root.exists() and root.is_dir() and not root.is_symlink(), "OFFLINE_EVIDENCE_STORE_INVALID")
    require(root.resolve(strict=True).is_relative_to(parent), "OFFLINE_EVIDENCE_PATH_ESCAPE")
    operation = root / verified["bindings"]["operation_id"]
    if create:
        try:
            operation.mkdir(mode=0o700, exist_ok=True)
        except OSError:
            raise NewLineageStop("OFFLINE_EVIDENCE_STORE_UNAVAILABLE") from None
    require(
        operation.exists() and operation.is_dir() and not operation.is_symlink(),
        "OFFLINE_OPERATION_STORE_INVALID",
    )
    require(operation.resolve(strict=True).is_relative_to(root.resolve(strict=True)), "OFFLINE_EVIDENCE_PATH_ESCAPE")
    return operation, operation / "claim.json", operation / "journal.json"


def _write_exclusive(path: Path, payload: Mapping[str, object]) -> None:
    require(not path.is_symlink(), "OFFLINE_CLAIM_SYMLINK_DENIED")
    try:
        with path.open("xb") as handle:
            handle.write(canonical_bytes(payload) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        if hasattr(os, "O_DIRECTORY"):
            descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    except FileExistsError:
        raise NewLineageStop("OFFLINE_OPERATION_ALREADY_STARTED") from None
    except OSError:
        raise NewLineageStop("OFFLINE_CLAIM_DURABILITY_FAILURE") from None


def begin_offline_fixture(
    directory: Path | str,
    *,
    expected_manifest_sha256: str,
    expected_head: str,
    before: object,
) -> dict[str, object]:
    """Atomically claim one local fixture evaluation; performs no POST."""
    verified = verify_package(
        directory,
        expected_manifest_sha256=expected_manifest_sha256,
        expected_head=expected_head,
    )
    checked_before = _verify_snapshot(before, verified["bindings"])
    require(
        checked_before["subject_touchpoint_count"] == 0
        and checked_before["source_event_match_count"] == 0
        and checked_before["delivery_receipt_match_count"] == 0
        and checked_before["dead_letter_match_count"] == 0,
        "DELIVERY_ALREADY_PRESENT_OR_AMBIGUOUS",
    )
    require(
        checked_before["campaign_audit_count"] <= INTERNAL_AUDIT_CAP - INTERNAL_AUDIT_BUDGET,
        "INTERNAL_AUDIT_CAPACITY_INSUFFICIENT",
    )
    operation, claim, journal = _evidence_paths(verified, create=True)
    claim_payload = _journal_payload(
        verified,
        "OFFLINE_FIXTURE_PRE_POST_INTENT",
        observed_fixture_attempts=0,
        fixture_only=True,
        package_path_sha256=canonical_digest(str(verified["package"])),
        before_sha256=canonical_digest(checked_before),
    )
    _write_exclusive(claim, claim_payload)
    _write_journal(
        journal,
        claim_payload,
    )
    return {
        "status": "OFFLINE_FIXTURE_PRE_POST_INTENT",
        "operation_id": verified["bindings"]["operation_id"],
        "package_manifest_sha256": verified["manifest_sha256"],
        "before_sha256": canonical_digest(checked_before),
        "evidence_directory": str(operation),
        "fixture_only": True,
        "production_interaction": "NOT_PERFORMED_BY_THIS_MODULE",
    }


def _hold_after_observation(
    verified: Mapping[str, object], journal: Path, original_cause: str
) -> None:
    try:
        _write_journal(
            journal,
            _journal_payload(
                verified,
                "POST_OUTCOME_AMBIGUOUS_HOLD_OWNER_REVIEW",
                observed_fixture_attempts=1,
                original_cause=original_cause,
                owner_review_required=True,
            ),
        )
    except Exception as journal_error:
        journal_cause = (
            str(journal_error) if isinstance(journal_error, NewLineageStop)
            else type(journal_error).__name__
        )
        raise OfflineOwnerReviewHold(original_cause, journal_cause) from None
    raise OfflineOwnerReviewHold(original_cause) from None


def complete_offline_fixture(
    directory: Path | str,
    *,
    expected_manifest_sha256: str,
    expected_head: str,
    before: object,
    after: object,
    status_code: object,
    raw_response: object,
    semantic_receipt: object,
    receipt_verification: object,
    verification_keys: object,
) -> dict[str, object]:
    """Evaluate one already-observed local fixture result; performs no POST."""
    verified = verify_package(
        directory,
        expected_manifest_sha256=expected_manifest_sha256,
        expected_head=expected_head,
    )
    _, claim_path, journal = _evidence_paths(verified, create=False)
    observation_claim = claim_path.with_name("observation-claim.json")
    _write_exclusive(
        observation_claim,
        _journal_payload(
            verified,
            "OFFLINE_FIXTURE_OBSERVATION_CLAIMED",
            observed_fixture_attempts=1,
            fixture_only=True,
        ),
    )
    try:
        claim = _exact_fields(
            load_json(claim_path),
            {
                "schema", "lineage", "operation_id", "package_manifest_sha256",
                "state", "module_post_attempts", "observed_fixture_attempts",
                "automatic_retry", "automatic_rollback_after_post",
                "production_authority", "fixture_only", "package_path_sha256",
                "before_sha256",
            },
            "OFFLINE_CLAIM_SCHEMA_INVALID",
        )
        intent = _exact_fields(
            load_json(journal), set(claim), "OFFLINE_INTENT_JOURNAL_SCHEMA_INVALID"
        )
        require(intent == claim, "OFFLINE_INTENT_JOURNAL_MISMATCH")
        require(
            claim.get("state") == "OFFLINE_FIXTURE_PRE_POST_INTENT"
            and claim.get("operation_id") == verified["bindings"]["operation_id"]
            and claim.get("package_manifest_sha256") == verified["manifest_sha256"]
            and claim.get("package_path_sha256") == canonical_digest(str(verified["package"]))
            and claim.get("before_sha256") == canonical_digest(_verify_snapshot(before, verified["bindings"]))
            and claim.get("module_post_attempts") == 0
            and claim.get("observed_fixture_attempts") == 0
            and claim.get("fixture_only") is True,
            "OFFLINE_CLAIM_BINDING_INVALID",
        )
        receipt, response_digests = _verify_fixture_response(
            status_code, raw_response, semantic_receipt, verified
        )
        readback = verify_readback(
            before,
            after,
            receipt,
            receipt_verification,
            verification_keys,
            verified,
        )
    except Exception as error:
        cause = str(error) if isinstance(error, NewLineageStop) else type(error).__name__
        _hold_after_observation(verified, journal, cause)
    result = {
        "status": "OFFLINE_FIXTURE_EVIDENCE_PASS",
        "operation_id": verified["bindings"]["operation_id"],
        "module_post_attempts": 0,
        "observed_fixture_attempts": 1,
        "automatic_retry": False,
        "automatic_rollback_after_post": False,
        "response_digests": response_digests,
        "readback": readback,
        "fixture_only": True,
        "production_interaction": "NOT_PERFORMED_BY_THIS_MODULE",
    }
    try:
        _write_journal(
            journal,
            _journal_payload(
                verified,
                "OFFLINE_FIXTURE_EVIDENCE_PASS",
                observed_fixture_attempts=1,
                result_sha256=canonical_digest(result),
                fixture_only=True,
            ),
        )
    except Exception as error:
        cause = str(error) if isinstance(error, NewLineageStop) else type(error).__name__
        _hold_after_observation(verified, journal, f"FINAL_JOURNAL_DURABILITY_FAILURE:{cause}")
    return result
