"""Pure verifier for fresh read-only evidence under the adopted new lineage.

This module deliberately has no transport, subprocess, network, credential,
claim, stage, image-load, delivery, or recovery entry point.  It defines the
minimum evidence-only Owner scope and verifies caller-supplied capture bytes.
Passing this verifier is preparation evidence, never execution authority.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from typing import Mapping
from uuid import UUID

import one_delivery_new_lineage as lineage


REQUEST_SCHEMA = "npd.agent-hub.phase9.one-delivery-readonly-request.v1"
SCOPE_SCHEMA = "npd.agent-hub.phase9.one-delivery-db0-evidence-scope.v1"
CAPTURE_SCHEMA = "npd.agent-hub.phase9.one-delivery-readonly-capture.v1"
EVIDENCE_SCHEMA = "npd.agent-hub.phase9.one-delivery-readonly-evidence.v1"
MAX_EVIDENCE_AGE_SECONDS = 600
PROTECTED_SERVICE_COUNT = 18
COUNTER_NAMES = (
    "video_factory_job_count",
    "video_factory_queue_count",
    "video_factory_processing_count",
    "video_factory_in_flight_count",
)
REMOTE_ARGV_SHAPE = [
    "python3",
    "-B",
    "-",
    "readonly-evidence",
    "<redacted canonical request>",
]
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def _exact(value: object, fields: set[str], reason: str) -> Mapping[str, object]:
    lineage.require(isinstance(value, Mapping) and set(value) == fields, reason)
    return value


def _hash(value: object, reason: str) -> str:
    lineage.require(
        isinstance(value, str) and bool(lineage.HASH.fullmatch(value)), reason
    )
    return value


def _head(value: object, reason: str) -> str:
    lineage.require(
        isinstance(value, str) and bool(lineage.HEAD.fullmatch(value)), reason
    )
    return value


def _utc(value: object, reason: str) -> datetime:
    lineage.require(isinstance(value, str) and bool(value), reason)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise lineage.NewLineageStop(reason) from None
    lineage.require(parsed.utcoffset() == timedelta(0), reason)
    return parsed


def _uuid4(value: object, reason: str) -> str:
    lineage.require(isinstance(value, str), reason)
    try:
        parsed = UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise lineage.NewLineageStop(reason) from None
    lineage.require(str(parsed) == value and parsed.version == 4, reason)
    return value


def _image_identity(value: object, reason: str) -> Mapping[str, object]:
    identity = _exact(
        value,
        {
            "source_head",
            "archive_sha256",
            "archive_size_bytes",
            "oci_index_sha256",
            "oci_manifest_sha256",
            "oci_config_sha256",
            "platform",
            "custody_manifest_sha256",
        },
        reason,
    )
    _head(identity.get("source_head"), reason)
    for field in (
        "archive_sha256",
        "oci_index_sha256",
        "oci_manifest_sha256",
        "oci_config_sha256",
        "custody_manifest_sha256",
    ):
        _hash(identity.get(field), reason)
    lineage.require(
        type(identity.get("archive_size_bytes")) is int
        and identity["archive_size_bytes"] > 0
        and identity.get("platform") == "linux/amd64",
        reason,
    )
    return identity


def verify_scope_receipt(
    receipt: object,
    *,
    operation_id: str,
    current: datetime,
) -> Mapping[str, object]:
    """Verify a narrow Owner scope for four aggregate DB0 reads only."""
    value = _exact(
        receipt,
        {
            "schema",
            "lineage",
            "operation_id",
            "decision",
            "fresh_explicit_owner_evidence_only_scope",
            "authorized_counter_names",
            "query_command",
            "database",
            "server_readonly_required",
            "eval_fallback_allowed",
            "raw_keys_values_credentials_or_job_payloads_authorized",
            "video_factory_workstream_opened",
            "video_factory_writes_authorized",
            "agent_hub_execution_authorized",
            "valid_from_utc",
            "expires_at_utc",
        },
        "DB0_SCOPE_SCHEMA_INVALID",
    )
    start = _utc(value.get("valid_from_utc"), "DB0_SCOPE_WINDOW_INVALID")
    end = _utc(value.get("expires_at_utc"), "DB0_SCOPE_WINDOW_INVALID")
    lineage.require(
        value.get("schema") == SCOPE_SCHEMA
        and value.get("lineage") == lineage.LINEAGE
        and value.get("operation_id") == operation_id
        and value.get("decision") == "APPROVED_EVIDENCE_ONLY"
        and value.get("fresh_explicit_owner_evidence_only_scope") is True
        and value.get("authorized_counter_names") == list(COUNTER_NAMES)
        and value.get("query_command") == "EVAL_RO"
        and value.get("database") == 0
        and type(value.get("database")) is int
        and value.get("server_readonly_required") is True
        and value.get("eval_fallback_allowed") is False
        and value.get("raw_keys_values_credentials_or_job_payloads_authorized")
        is False
        and value.get("video_factory_workstream_opened") is False
        and value.get("video_factory_writes_authorized") is False
        and value.get("agent_hub_execution_authorized") is False
        and start <= current < end,
        "DB0_EVIDENCE_ONLY_SCOPE_NOT_GRANTED",
    )
    return value


def build_request(
    *,
    operation_id: str,
    candidate_head: str,
    transport_profile_sha256: str,
    collector_source_sha256: str,
    expected_protected_services_sha256: str,
    candidate_identity: object,
    rollback_identity: object,
    db0_scope_receipt: object,
    current: datetime,
) -> dict[str, object]:
    """Build deterministic review data for a later read-only collection."""
    operation = lineage.parse_operation_id(operation_id)
    _head(candidate_head, "READONLY_REQUEST_HEAD_INVALID")
    _hash(transport_profile_sha256, "READONLY_TRANSPORT_PROFILE_INVALID")
    _hash(collector_source_sha256, "READONLY_COLLECTOR_SOURCE_INVALID")
    _hash(expected_protected_services_sha256, "PROTECTED_BASELINE_ANCHOR_INVALID")
    candidate = dict(_image_identity(candidate_identity, "CANDIDATE_IDENTITY_INVALID"))
    rollback = dict(_image_identity(rollback_identity, "ROLLBACK_IDENTITY_INVALID"))
    lineage.require(
        candidate["source_head"] == candidate_head,
        "CANDIDATE_SOURCE_HEAD_MISMATCH",
    )
    scope = verify_scope_receipt(
        db0_scope_receipt, operation_id=operation, current=current
    )
    return {
        "schema": REQUEST_SCHEMA,
        "lineage": lineage.LINEAGE,
        "operation_id": operation,
        "candidate_head": candidate_head,
        "transport_profile_sha256": transport_profile_sha256,
        "collector_source_sha256": collector_source_sha256,
        "expected_protected_services_sha256": expected_protected_services_sha256,
        "candidate_identity": candidate,
        "rollback_identity": rollback,
        "db0_scope_receipt_sha256": lineage.canonical_digest(scope),
        "remote_argv_shape": list(REMOTE_ARGV_SHAPE),
        "required_counter_names": list(COUNTER_NAMES),
        "collection_mode": "READ_ONLY_EVIDENCE_ONLY",
        "production_execution_approval": "NOT_GRANTED",
        "claim_stage_load_deploy_delivery_authorized": False,
    }


def _verify_request(value: object) -> Mapping[str, object]:
    request = _exact(
        value,
        {
            "schema",
            "lineage",
            "operation_id",
            "candidate_head",
            "transport_profile_sha256",
            "collector_source_sha256",
            "expected_protected_services_sha256",
            "candidate_identity",
            "rollback_identity",
            "db0_scope_receipt_sha256",
            "remote_argv_shape",
            "required_counter_names",
            "collection_mode",
            "production_execution_approval",
            "claim_stage_load_deploy_delivery_authorized",
        },
        "READONLY_REQUEST_SCHEMA_INVALID",
    )
    lineage.parse_operation_id(request.get("operation_id"))
    _head(request.get("candidate_head"), "READONLY_REQUEST_HEAD_INVALID")
    for field in (
        "transport_profile_sha256",
        "collector_source_sha256",
        "expected_protected_services_sha256",
        "db0_scope_receipt_sha256",
    ):
        _hash(request.get(field), "READONLY_REQUEST_HASH_INVALID")
    candidate = _image_identity(
        request.get("candidate_identity"), "CANDIDATE_IDENTITY_INVALID"
    )
    _image_identity(request.get("rollback_identity"), "ROLLBACK_IDENTITY_INVALID")
    lineage.require(
        request.get("schema") == REQUEST_SCHEMA
        and request.get("lineage") == lineage.LINEAGE
        and candidate.get("source_head") == request.get("candidate_head")
        and request.get("remote_argv_shape") == REMOTE_ARGV_SHAPE
        and request.get("required_counter_names") == list(COUNTER_NAMES)
        and request.get("collection_mode") == "READ_ONLY_EVIDENCE_ONLY"
        and request.get("production_execution_approval") == "NOT_GRANTED"
        and request.get("claim_stage_load_deploy_delivery_authorized") is False,
        "READONLY_REQUEST_BOUNDARY_INVALID",
    )
    return request


def _verify_capture(
    value: object,
    *,
    request: Mapping[str, object],
    raw_stdout: bytes,
) -> Mapping[str, object]:
    capture = _exact(
        value,
        {
            "schema",
            "lineage",
            "operation_id",
            "request_sha256",
            "transport_profile_sha256",
            "collector_source_sha256",
            "remote_argv_shape",
            "invocation_id",
            "started_at_utc",
            "completed_at_utc",
            "child_returncode",
            "timed_out",
            "launch_error_class",
            "raw_stdout_sha256",
            "raw_stdout_length_bytes",
            "canonical_payload_sha256",
            "raw_stderr_sha256",
            "raw_stderr_length_bytes",
            "raw_transport_bytes",
            "argv_or_authorization_persisted",
        },
        "READONLY_CAPTURE_SCHEMA_INVALID",
    )
    started = _utc(capture.get("started_at_utc"), "READONLY_CAPTURE_TIME_INVALID")
    completed = _utc(
        capture.get("completed_at_utc"), "READONLY_CAPTURE_TIME_INVALID"
    )
    _uuid4(capture.get("invocation_id"), "READONLY_CAPTURE_UUID_INVALID")
    request_sha = lineage.canonical_digest(request)
    lineage.require(
        type(raw_stdout) is bytes
        and len(raw_stdout) > 0
        and capture.get("schema") == CAPTURE_SCHEMA
        and capture.get("lineage") == lineage.LINEAGE
        and capture.get("operation_id") == request.get("operation_id")
        and capture.get("request_sha256") == request_sha
        and capture.get("transport_profile_sha256")
        == request.get("transport_profile_sha256")
        and capture.get("collector_source_sha256")
        == request.get("collector_source_sha256")
        and capture.get("remote_argv_shape") == REMOTE_ARGV_SHAPE
        and started <= completed
        and capture.get("child_returncode") == 0
        and type(capture.get("child_returncode")) is int
        and capture.get("timed_out") is False
        and capture.get("launch_error_class") is None
        and capture.get("raw_stdout_length_bytes") == len(raw_stdout)
        and capture.get("raw_stdout_sha256")
        == hashlib.sha256(raw_stdout).hexdigest()
        and capture.get("raw_stderr_length_bytes") == 0
        and capture.get("raw_stderr_sha256") == EMPTY_SHA256
        and capture.get("raw_transport_bytes") is True
        and capture.get("argv_or_authorization_persisted") is False,
        "READONLY_CAPTURE_INVALID",
    )
    return capture


def _verify_evidence(
    value: object,
    *,
    request: Mapping[str, object],
    scope: Mapping[str, object],
    capture: Mapping[str, object],
    current: datetime,
) -> Mapping[str, object]:
    evidence = _exact(
        value,
        {
            "schema",
            "lineage",
            "operation_id",
            "request_sha256",
            "observed_at_utc",
            "agent_hub",
            "candidate",
            "rollback",
            "video_factory_db0",
            "effects",
            "production_execution_approval",
        },
        "READONLY_EVIDENCE_SCHEMA_INVALID",
    )
    observed = _utc(
        evidence.get("observed_at_utc"), "READONLY_EVIDENCE_TIMESTAMP_INVALID"
    )
    age = (current - observed).total_seconds()
    lineage.require(
        -5 <= age <= MAX_EVIDENCE_AGE_SECONDS,
        "READONLY_EVIDENCE_STALE_OR_FUTURE",
    )
    completed = _utc(
        capture.get("completed_at_utc"), "READONLY_CAPTURE_TIME_INVALID"
    )
    scope_start = _utc(scope.get("valid_from_utc"), "DB0_SCOPE_WINDOW_INVALID")
    scope_end = _utc(scope.get("expires_at_utc"), "DB0_SCOPE_WINDOW_INVALID")
    lineage.require(
        observed <= completed
        and completed - observed <= timedelta(seconds=MAX_EVIDENCE_AGE_SECONDS),
        "READONLY_EVIDENCE_CAPTURE_TIME_MISMATCH",
    )
    lineage.require(
        scope_start <= observed <= completed < scope_end,
        "READONLY_EVIDENCE_OUTSIDE_SCOPE_WINDOW",
    )

    agent = _exact(
        evidence.get("agent_hub"),
        {
            "compose_project",
            "compose_service",
            "target_container_id",
            "target_image_config_sha256",
            "target_signature_sha256",
            "protected_service_count",
            "protected_services_sha256",
            "healthy",
            "ready",
            "restart_count",
            "runtime_mode",
            "scheduler_enabled",
            "external_writes_enabled",
            "claim_absent",
            "candidate_staged",
            "delivery_absent",
        },
        "READONLY_AGENT_HUB_SCHEMA_INVALID",
    )
    _hash(agent.get("target_container_id"), "READONLY_AGENT_HUB_TARGET_INVALID")
    _hash(
        agent.get("target_image_config_sha256"),
        "READONLY_AGENT_HUB_TARGET_INVALID",
    )
    _hash(
        agent.get("target_signature_sha256"),
        "READONLY_AGENT_HUB_TARGET_INVALID",
    )
    _hash(
        agent.get("protected_services_sha256"),
        "READONLY_AGENT_HUB_TARGET_INVALID",
    )
    rollback_request = request["rollback_identity"]
    lineage.require(
        agent.get("compose_project") == "npd-agent-hub-prod"
        and agent.get("compose_service") == "agent-hub"
        and agent.get("target_image_config_sha256")
        == rollback_request["oci_config_sha256"]
        and agent.get("protected_service_count") == PROTECTED_SERVICE_COUNT
        and type(agent.get("protected_service_count")) is int
        and agent.get("protected_services_sha256")
        == request.get("expected_protected_services_sha256")
        and agent.get("healthy") is True
        and agent.get("ready") is True
        and agent.get("restart_count") == 0
        and type(agent.get("restart_count")) is int
        and agent.get("runtime_mode") == "phase9_creation"
        and agent.get("scheduler_enabled") is False
        and agent.get("external_writes_enabled") is False
        and agent.get("claim_absent") is True
        and agent.get("candidate_staged") is False
        and agent.get("delivery_absent") is True,
        "READONLY_AGENT_HUB_BOUNDARY_INVALID",
    )

    candidate = _exact(
        evidence.get("candidate"),
        {
            "identity",
            "archive_verified",
            "custody_manifest_verified",
            "staged",
            "loaded",
        },
        "READONLY_CANDIDATE_SCHEMA_INVALID",
    )
    rollback = _exact(
        evidence.get("rollback"),
        {
            "identity",
            "archive_verified",
            "custody_manifest_verified",
            "image_present",
            "current_target",
        },
        "READONLY_ROLLBACK_SCHEMA_INVALID",
    )
    lineage.require(
        candidate.get("identity") == request.get("candidate_identity")
        and candidate.get("archive_verified") is True
        and candidate.get("custody_manifest_verified") is True
        and candidate.get("staged") is False
        and candidate.get("loaded") is False,
        "READONLY_CANDIDATE_BINDING_INVALID",
    )
    lineage.require(
        rollback.get("identity") == request.get("rollback_identity")
        and rollback.get("archive_verified") is True
        and rollback.get("custody_manifest_verified") is True
        and rollback.get("image_present") is True
        and rollback.get("current_target") is True,
        "READONLY_ROLLBACK_BINDING_INVALID",
    )

    db0 = _exact(
        evidence.get("video_factory_db0"),
        {
            "scope_receipt_sha256",
            "counter_names",
            "counters",
            "query_command",
            "database",
            "server_enforced_readonly",
            "eval_fallback_used",
            "raw_keys_values_credentials_or_job_payloads_emitted",
            "video_factory_workstream_opened",
            "video_factory_writes",
        },
        "READONLY_DB0_SCHEMA_INVALID",
    )
    counters = db0.get("counters")
    lineage.require(
        isinstance(counters, Mapping)
        and set(counters) == set(COUNTER_NAMES)
        and all(type(item) is int and item >= 0 for item in counters.values()),
        "READONLY_DB0_COUNTERS_INVALID",
    )
    lineage.require(
        db0.get("scope_receipt_sha256") == lineage.canonical_digest(scope)
        == request.get("db0_scope_receipt_sha256")
        and db0.get("counter_names") == list(COUNTER_NAMES)
        and db0.get("query_command") == "EVAL_RO"
        and db0.get("database") == 0
        and type(db0.get("database")) is int
        and db0.get("server_enforced_readonly") is True
        and db0.get("eval_fallback_used") is False
        and db0.get("raw_keys_values_credentials_or_job_payloads_emitted")
        is False
        and db0.get("video_factory_workstream_opened") is False
        and db0.get("video_factory_writes") == 0
        and type(db0.get("video_factory_writes")) is int
        and counters["video_factory_queue_count"] == 0
        and counters["video_factory_processing_count"] == 0
        and counters["video_factory_in_flight_count"] == 0,
        "READONLY_DB0_BOUNDARY_INVALID",
    )

    effects = _exact(
        evidence.get("effects"),
        {
            "production_read_only",
            "production_mutation",
            "business_system_write",
            "claim_created",
            "stage_performed",
            "image_loaded",
            "delivery_posted",
            "provider_calls",
            "video_factory_writes",
        },
        "READONLY_EFFECTS_SCHEMA_INVALID",
    )
    lineage.require(
        effects.get("production_read_only") is True
        and effects.get("production_mutation") is False
        and effects.get("business_system_write") is False
        and effects.get("claim_created") is False
        and effects.get("stage_performed") is False
        and effects.get("image_loaded") is False
        and effects.get("delivery_posted") is False
        and effects.get("provider_calls") == 0
        and type(effects.get("provider_calls")) is int
        and effects.get("video_factory_writes") == 0
        and type(effects.get("video_factory_writes")) is int,
        "READONLY_EFFECTS_INVALID",
    )
    lineage.require(
        evidence.get("schema") == EVIDENCE_SCHEMA
        and evidence.get("lineage") == lineage.LINEAGE
        and evidence.get("operation_id") == request.get("operation_id")
        and evidence.get("request_sha256") == lineage.canonical_digest(request)
        and evidence.get("production_execution_approval") == "NOT_GRANTED",
        "READONLY_EVIDENCE_BINDING_INVALID",
    )
    return evidence


def verify_readonly_evidence(
    request: object,
    db0_scope_receipt: object,
    capture_receipt: object,
    raw_stdout: bytes,
    *,
    current: datetime | None = None,
) -> dict[str, object]:
    """Verify exact fresh raw evidence; never turn it into execution approval."""
    now = current or datetime.now(timezone.utc)
    lineage.require(now.utcoffset() == timedelta(0), "CURRENT_TIME_NOT_UTC")
    checked_request = _verify_request(request)
    scope = verify_scope_receipt(
        db0_scope_receipt,
        operation_id=str(checked_request["operation_id"]),
        current=now,
    )
    lineage.require(
        lineage.canonical_digest(scope)
        == checked_request.get("db0_scope_receipt_sha256"),
        "DB0_SCOPE_RECEIPT_BINDING_MISMATCH",
    )
    capture = _verify_capture(
        capture_receipt, request=checked_request, raw_stdout=raw_stdout
    )
    try:
        evidence = lineage.loads_strict(raw_stdout)
    except lineage.NewLineageStop:
        raise lineage.NewLineageStop("READONLY_RAW_EVIDENCE_INVALID") from None
    lineage.require(
        lineage.canonical_digest(evidence)
        == capture.get("canonical_payload_sha256"),
        "READONLY_CAPTURE_CANONICAL_DIGEST_MISMATCH",
    )
    checked_evidence = _verify_evidence(
        evidence,
        request=checked_request,
        scope=scope,
        capture=capture,
        current=now,
    )
    return {
        "status": "READONLY_EVIDENCE_VERIFIED_EXECUTION_NOT_AUTHORIZED",
        "lineage": lineage.LINEAGE,
        "operation_id": checked_request["operation_id"],
        "request_sha256": lineage.canonical_digest(checked_request),
        "scope_receipt_sha256": lineage.canonical_digest(scope),
        "capture_receipt_sha256": lineage.canonical_digest(capture),
        "evidence_sha256": lineage.canonical_digest(checked_evidence),
        "protected_service_count": PROTECTED_SERVICE_COUNT,
        "protected_services_sha256": checked_evidence["agent_hub"][
            "protected_services_sha256"
        ],
        "video_factory_db0_counters": dict(
            checked_evidence["video_factory_db0"]["counters"]
        ),
        "production_execution_approval": "NOT_GRANTED",
        "production_mutation": False,
        "claim_stage_load_deploy_delivery": False,
    }
