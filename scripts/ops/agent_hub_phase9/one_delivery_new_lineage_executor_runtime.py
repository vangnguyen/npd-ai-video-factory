"""One-attempt file-backed execution model for offline source review.

The state machine exercises the same claim/stage/pre-POST/observation/recovery
boundaries intended for a future runtime, but it is permanently restricted to
an owned local sandbox.  It has no transport, command runner, callback, socket,
HTTP client, credential loader, production path, or provider integration.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import os
from pathlib import Path
from typing import Mapping

import one_delivery_new_lineage as lineage
import one_delivery_new_lineage_readonly_evidence as readonly


BINDING_SCHEMA = "npd.agent-hub.phase9.one-delivery-runtime-binding.v1"
SCENARIO_SCHEMA = "npd.agent-hub.phase9.one-delivery-offline-scenario.v1"
STATE_SCHEMA = "npd.agent-hub.phase9.one-delivery-execution-state.v1"
RESULT_SCHEMA = "npd.agent-hub.phase9.one-delivery-offline-result.v1"
OFFLINE_RUNTIME_DIRECTORY = ".agent-hub-runtime-offline"
FAULT_MODES = {
    "NONE",
    "AFTER_CLAIM",
    "AFTER_STAGE",
    "AFTER_PRE_POST_INTENT",
    "POST_OUTCOME_AMBIGUOUS",
    "READBACK_INVALID",
}
TERMINAL_BY_FAULT = {
    "NONE": "PASS",
    "AFTER_CLAIM": "ABORTED_PRE_STAGE",
    "AFTER_STAGE": "RECOVERED_PRE_POST",
    "AFTER_PRE_POST_INTENT": "HOLD_OWNER_REVIEW",
    "POST_OUTCOME_AMBIGUOUS": "HOLD_OWNER_REVIEW",
    "READBACK_INVALID": "HOLD_OWNER_REVIEW",
}
COMMON_STATE_FIELDS = {
    "schema",
    "lineage",
    "operation_id",
    "runtime_review_manifest_sha256",
    "state",
    "sequence",
    "at_utc",
    "previous_state_sha256",
    "max_attempts",
    "simulated_post_attempts",
    "real_post_attempts",
    "automatic_retry",
    "automatic_rollback_after_post",
    "fixture_only",
    "read_scope_authority",
    "execution_authority",
}
RESULT_FIELDS = {
    "schema",
    "lineage",
    "operation_id",
    "runtime_review_manifest_sha256",
    "terminal_state",
    "terminal_state_sha256",
    "recovery",
    "original_cause",
    "max_attempts",
    "simulated_post_attempts",
    "real_post_attempts",
    "automatic_retry",
    "automatic_rollback_after_post",
    "generated_command_executed",
    "transport_source_sha256",
    "core_source_sha256",
    "builder_source_sha256",
    "readonly_verifier_source_sha256",
    "executor_source_sha256",
    "collector_bytes_sha256",
    "strict_argv_sha256",
    "candidate_archive_sha256",
    "rollback_archive_sha256",
    "fixture_only",
    "production_interaction",
}
STATE_EXTRA_FIELDS = {
    "PREFLIGHT": {"claim_absent", "stage_absent"},
    "CLAIMED": {"claim_id_sha256"},
    "STAGED": {"candidate_archive_sha256", "candidate_mutation"},
    "PRE_POST_INTENT": {"candidate_stage_sha256", "no_retry"},
    "POST_OBSERVED": {"raw_response_sha256", "rollback_attempted"},
    "PASS": {"readback_sha256", "rollback_attempted"},
    "ABORTED_PRE_STAGE": {"cause", "candidate_mutation"},
    "RECOVERED_PRE_POST": {
        "cause",
        "candidate_stage_present",
        "rollback_verified",
    },
    "HOLD_OWNER_REVIEW": {
        "cause",
        "rollback_attempted",
        "owner_review_required",
    },
}
ALLOWED_TRANSITIONS = {
    ("PREFLIGHT", "CLAIMED"),
    ("CLAIMED", "ABORTED_PRE_STAGE"),
    ("CLAIMED", "STAGED"),
    ("STAGED", "RECOVERED_PRE_POST"),
    ("STAGED", "PRE_POST_INTENT"),
    ("PRE_POST_INTENT", "HOLD_OWNER_REVIEW"),
    ("PRE_POST_INTENT", "POST_OBSERVED"),
    ("POST_OBSERVED", "HOLD_OWNER_REVIEW"),
    ("POST_OBSERVED", "PASS"),
}


class OfflineRuntimeHold(lineage.NewLineageStop):
    """The simulated path crossed the pre-POST uncertainty boundary."""


def _exact(value: object, fields: set[str], reason: str) -> Mapping[str, object]:
    lineage.require(isinstance(value, Mapping) and set(value) == fields, reason)
    return value


def _hash(value: object, reason: str) -> str:
    lineage.require(
        isinstance(value, str) and bool(lineage.HASH.fullmatch(value)), reason
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


def verify_runtime_binding(value: object) -> Mapping[str, object]:
    binding = _exact(
        value,
        {
            "schema",
            "lineage",
            "operation_id",
            "candidate_head",
            "base_package_manifest_sha256",
            "runtime_review_manifest_sha256",
            "readonly_request_sha256",
            "transport_profile_sha256",
            "core_source_sha256",
            "builder_source_sha256",
            "transport_source_sha256",
            "executor_source_sha256",
            "readonly_verifier_source_sha256",
            "collector_bytes_sha256",
            "strict_argv_sha256",
            "candidate_archive_sha256",
            "rollback_archive_sha256",
            "fixture_only",
            "generated_command_executed",
            "real_post_attempts",
            "read_scope_authority",
            "execution_authority",
        },
        "RUNTIME_BINDING_SCHEMA_INVALID",
    )
    lineage.parse_operation_id(binding.get("operation_id"))
    lineage.require(
        isinstance(binding.get("candidate_head"), str)
        and bool(lineage.HEAD.fullmatch(binding["candidate_head"])),
        "RUNTIME_BINDING_HEAD_INVALID",
    )
    for field in (
        "base_package_manifest_sha256",
        "runtime_review_manifest_sha256",
        "readonly_request_sha256",
        "transport_profile_sha256",
        "core_source_sha256",
        "builder_source_sha256",
        "transport_source_sha256",
        "executor_source_sha256",
        "readonly_verifier_source_sha256",
        "collector_bytes_sha256",
        "strict_argv_sha256",
        "candidate_archive_sha256",
        "rollback_archive_sha256",
    ):
        _hash(binding.get(field), "RUNTIME_BINDING_HASH_INVALID")
    lineage.require(
        binding.get("schema") == BINDING_SCHEMA
        and binding.get("lineage") == lineage.LINEAGE
        and binding.get("fixture_only") is True
        and binding.get("generated_command_executed") is False
        and binding.get("real_post_attempts") == 0
        and type(binding.get("real_post_attempts")) is int
        and binding.get("read_scope_authority")
        == "NOT_GRANTED_STRUCTURAL_FIXTURE_ONLY"
        and binding.get("execution_authority") == "NOT_GRANTED",
        "RUNTIME_BINDING_AUTHORITY_INVALID",
    )
    return binding


def verify_scenario(value: object, operation_id: str) -> Mapping[str, object]:
    scenario = _exact(
        value,
        {
            "schema",
            "lineage",
            "operation_id",
            "mode",
            "fault_mode",
            "scope_start_utc",
            "preflight_at_utc",
            "claimed_at_utc",
            "staged_at_utc",
            "pre_post_intent_at_utc",
            "post_observed_at_utc",
            "completed_at_utc",
            "scope_end_utc",
            "current_utc",
            "before",
            "after",
            "status_code",
            "raw_response",
            "semantic_receipt",
            "receipt_verification",
            "verification_keys",
        },
        "OFFLINE_SCENARIO_SCHEMA_INVALID",
    )
    times = {
        field: _utc(scenario[field], "OFFLINE_SCENARIO_TIME_INVALID")
        for field in (
            "scope_start_utc",
            "preflight_at_utc",
            "claimed_at_utc",
            "staged_at_utc",
            "pre_post_intent_at_utc",
            "post_observed_at_utc",
            "completed_at_utc",
            "scope_end_utc",
            "current_utc",
        )
    }
    lineage.require(
        scenario.get("schema") == SCENARIO_SCHEMA
        and scenario.get("lineage") == lineage.LINEAGE
        and scenario.get("operation_id") == operation_id
        and scenario.get("mode") == "OFFLINE_SANDBOX_ONLY"
        and scenario.get("fault_mode") in FAULT_MODES
        and times["scope_start_utc"]
        <= times["preflight_at_utc"]
        <= times["claimed_at_utc"]
        <= times["staged_at_utc"]
        <= times["pre_post_intent_at_utc"]
        <= times["post_observed_at_utc"]
        <= times["completed_at_utc"]
        <= times["scope_end_utc"]
        and times["completed_at_utc"] <= times["current_utc"]
        and (times["current_utc"] - times["scope_start_utc"]).total_seconds()
        <= readonly.MAX_EVIDENCE_AGE_SECONDS,
        "OFFLINE_SCENARIO_BOUNDARY_INVALID",
    )
    lineage.require(
        type(scenario.get("raw_response")) is bytes,
        "OFFLINE_SCENARIO_RAW_RESPONSE_INVALID",
    )
    return scenario


def _sync_directory(path: Path) -> None:
    if not hasattr(os, "O_DIRECTORY"):
        return
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        raise lineage.NewLineageStop("OFFLINE_RUNTIME_DIRECTORY_SYNC_FAILED") from None


def _write_exclusive(path: Path, value: Mapping[str, object]) -> None:
    lineage.require(not path.exists() and not path.is_symlink(), "OFFLINE_RUNTIME_CLAIM_EXISTS")
    try:
        with path.open("xb") as handle:
            handle.write(lineage.canonical_bytes(value) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        _sync_directory(path.parent)
    except FileExistsError:
        raise lineage.NewLineageStop("OFFLINE_RUNTIME_CLAIM_EXISTS") from None
    except OSError:
        raise lineage.NewLineageStop("OFFLINE_RUNTIME_DURABILITY_FAILURE") from None


def _replace_json(path: Path, value: Mapping[str, object]) -> None:
    temporary = path.with_name(path.name + ".next")
    lineage.require(not temporary.exists(), "OFFLINE_RUNTIME_TEMP_COLLISION")
    try:
        with temporary.open("xb") as handle:
            handle.write(lineage.canonical_bytes(value) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _sync_directory(path.parent)
    except OSError:
        if temporary.exists():
            temporary.unlink()
        raise lineage.NewLineageStop("OFFLINE_RUNTIME_DURABILITY_FAILURE") from None


def _write_bytes_exclusive(path: Path, raw: bytes) -> None:
    lineage.require(type(raw) is bytes and len(raw) > 0, "OFFLINE_ARCHIVE_BYTES_INVALID")
    try:
        with path.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        _sync_directory(path.parent)
    except FileExistsError:
        raise lineage.NewLineageStop("OFFLINE_STAGE_COLLISION") from None
    except OSError:
        raise lineage.NewLineageStop("OFFLINE_STAGE_DURABILITY_FAILURE") from None


def _verify_archive(raw: object, identity: Mapping[str, object], reason: str) -> bytes:
    lineage.require(type(raw) is bytes and len(raw) > 0, reason)
    lineage.require(
        len(raw) == identity.get("archive_size_bytes")
        and hashlib.sha256(raw).hexdigest() == identity.get("archive_sha256"),
        reason,
    )
    return raw


def _state(
    binding: Mapping[str, object],
    state: str,
    sequence: int,
    at_utc: str,
    previous_sha256: str | None,
    **extra: object,
) -> dict[str, object]:
    return {
        "schema": STATE_SCHEMA,
        "lineage": lineage.LINEAGE,
        "operation_id": binding["operation_id"],
        "runtime_review_manifest_sha256": binding[
            "runtime_review_manifest_sha256"
        ],
        "state": state,
        "sequence": sequence,
        "at_utc": at_utc,
        "previous_state_sha256": previous_sha256,
        "max_attempts": 1,
        "simulated_post_attempts": 0,
        "real_post_attempts": 0,
        "automatic_retry": False,
        "automatic_rollback_after_post": False,
        "fixture_only": True,
        "read_scope_authority": "NOT_GRANTED_STRUCTURAL_FIXTURE_ONLY",
        "execution_authority": "NOT_GRANTED",
        **extra,
    }


def _transition(
    path: Path,
    binding: Mapping[str, object],
    state: str,
    sequence: int,
    at_utc: str,
    previous: Mapping[str, object] | None,
    **extra: object,
) -> dict[str, object]:
    previous_sha256 = (
        lineage.canonical_digest(previous) if previous is not None else None
    )
    value = _state(
        binding,
        state,
        sequence,
        at_utc,
        previous_sha256,
        **extra,
    )
    states = path.parent / "states"
    lineage.require(states.is_dir() and not states.is_symlink(), "OFFLINE_STATE_HISTORY_INVALID")
    _write_exclusive(states / f"{sequence:03d}-{state}.json", value)
    _replace_json(path, value)
    return value


def expected_terminal_state(fault_mode: str) -> str:
    lineage.require(fault_mode in FAULT_MODES, "OFFLINE_FAULT_MODE_INVALID")
    return TERMINAL_BY_FAULT[fault_mode]


def _verify_state_semantics(
    value: Mapping[str, object],
    previous: Mapping[str, object] | None,
    binding: Mapping[str, object],
) -> None:
    state = value["state"]
    post_attempts = value.get("simulated_post_attempts")
    lineage.require(
        type(post_attempts) is int
        and post_attempts
        == (1 if state in {"POST_OBSERVED", "PASS", "HOLD_OWNER_REVIEW"} else 0),
        "OFFLINE_STATE_ATTEMPT_MODEL_INVALID",
    )
    if state == "PREFLIGHT":
        valid = (
            value.get("sequence") == 0
            and previous is None
            and value.get("claim_absent") is True
            and value.get("stage_absent") is True
        )
    elif state == "CLAIMED":
        valid = value.get("claim_id_sha256") == lineage.canonical_digest(
            {
                "operation_id": binding["operation_id"],
                "runtime_review_manifest_sha256": binding[
                    "runtime_review_manifest_sha256"
                ],
            }
        )
    elif state == "STAGED":
        valid = (
            value.get("candidate_archive_sha256")
            == binding["candidate_archive_sha256"]
            and value.get("candidate_mutation") is True
        )
    elif state == "PRE_POST_INTENT":
        valid = (
            value.get("candidate_stage_sha256")
            == binding["candidate_archive_sha256"]
            and value.get("no_retry") is True
        )
    elif state == "POST_OBSERVED":
        _hash(value.get("raw_response_sha256"), "OFFLINE_STATE_SEMANTICS_INVALID")
        valid = value.get("rollback_attempted") is False
    elif state == "PASS":
        _hash(value.get("readback_sha256"), "OFFLINE_STATE_SEMANTICS_INVALID")
        valid = value.get("rollback_attempted") is False
    elif state == "ABORTED_PRE_STAGE":
        valid = (
            value.get("cause") == "FAULT_AFTER_CLAIM"
            and value.get("candidate_mutation") is False
        )
    elif state == "RECOVERED_PRE_POST":
        valid = (
            value.get("cause") == "FAULT_AFTER_STAGE"
            and value.get("candidate_stage_present") is False
            and value.get("rollback_verified") is True
        )
    else:
        valid = (
            isinstance(value.get("cause"), str)
            and bool(value["cause"])
            and value.get("rollback_attempted") is False
            and value.get("owner_review_required") is True
            and previous is not None
            and (
                previous.get("state") != "PRE_POST_INTENT"
                or value.get("cause") == "FAULT_AFTER_PRE_POST_INTENT"
            )
        )
    lineage.require(valid is True, "OFFLINE_STATE_SEMANTICS_INVALID")


def _terminal_result(
    operation: Path,
    binding: Mapping[str, object],
    state: Mapping[str, object],
    terminal: str,
    *,
    recovery: str,
    original_cause: str | None,
) -> dict[str, object]:
    result = {
        "schema": RESULT_SCHEMA,
        "lineage": lineage.LINEAGE,
        "operation_id": binding["operation_id"],
        "runtime_review_manifest_sha256": binding[
            "runtime_review_manifest_sha256"
        ],
        "terminal_state": terminal,
        "terminal_state_sha256": lineage.canonical_digest(state),
        "recovery": recovery,
        "original_cause": original_cause,
        "max_attempts": 1,
        "simulated_post_attempts": state["simulated_post_attempts"],
        "real_post_attempts": 0,
        "automatic_retry": False,
        "automatic_rollback_after_post": False,
        "generated_command_executed": False,
        "transport_source_sha256": binding["transport_source_sha256"],
        "core_source_sha256": binding["core_source_sha256"],
        "builder_source_sha256": binding["builder_source_sha256"],
        "readonly_verifier_source_sha256": binding[
            "readonly_verifier_source_sha256"
        ],
        "executor_source_sha256": binding["executor_source_sha256"],
        "collector_bytes_sha256": binding["collector_bytes_sha256"],
        "strict_argv_sha256": binding["strict_argv_sha256"],
        "candidate_archive_sha256": binding["candidate_archive_sha256"],
        "rollback_archive_sha256": binding["rollback_archive_sha256"],
        "fixture_only": True,
        "production_interaction": "NOT_PERFORMED",
    }
    _write_exclusive(operation / "result.json", result)
    return result


def verify_offline_runtime_terminal(
    sandbox_parent: Path | str,
    *,
    runtime_binding: object,
) -> dict[str, object]:
    """Independently verify the immutable state chain and source-bound result."""
    binding = verify_runtime_binding(runtime_binding)
    parent = Path(sandbox_parent).resolve(strict=True)
    operation = (
        parent / OFFLINE_RUNTIME_DIRECTORY / str(binding["operation_id"])
    )
    lineage.require(
        operation.is_dir() and not operation.is_symlink(),
        "OFFLINE_TERMINAL_DIRECTORY_INVALID",
    )
    claim_path = operation / "claim.json"
    state_path = operation / "state.json"
    result_path = operation / "result.json"
    states = operation / "states"
    for path in (claim_path, state_path, result_path):
        lineage.require(
            path.is_file() and not path.is_symlink(),
            "OFFLINE_TERMINAL_ARTIFACT_MISSING",
        )
    lineage.require(
        states.is_dir() and not states.is_symlink(),
        "OFFLINE_STATE_HISTORY_INVALID",
    )
    history_paths = sorted(states.iterdir(), key=lambda item: item.name)
    lineage.require(
        3 <= len(history_paths) <= 6
        and all(path.is_file() and not path.is_symlink() for path in history_paths),
        "OFFLINE_STATE_HISTORY_INVALID",
    )
    history: list[Mapping[str, object]] = []
    previous: Mapping[str, object] | None = None
    previous_time: datetime | None = None
    for sequence, path in enumerate(history_paths):
        value = lineage.load_json(path)
        lineage.require(isinstance(value, Mapping), "OFFLINE_STATE_RECORD_INVALID")
        lineage.require(
            value.get("sequence") == sequence
            and path.name == f"{sequence:03d}-{value.get('state')}.json"
            and value.get("previous_state_sha256")
            == (
                lineage.canonical_digest(previous)
                if previous is not None
                else None
            ),
            "OFFLINE_STATE_CHAIN_INVALID",
        )
        checked_time = _utc(value.get("at_utc"), "OFFLINE_STATE_TIME_INVALID")
        lineage.require(
            value.get("state") in STATE_EXTRA_FIELDS
            and set(value)
            == COMMON_STATE_FIELDS | STATE_EXTRA_FIELDS[value["state"]]
            and (previous_time is None or previous_time <= checked_time)
            and (
                previous is None
                or (previous.get("state"), value.get("state"))
                in ALLOWED_TRANSITIONS
            )
            and
            value.get("schema") == STATE_SCHEMA
            and value.get("lineage") == lineage.LINEAGE
            and value.get("operation_id") == binding["operation_id"]
            and value.get("runtime_review_manifest_sha256")
            == binding["runtime_review_manifest_sha256"]
            and value.get("max_attempts") == 1
            and value.get("real_post_attempts") == 0
            and value.get("automatic_retry") is False
            and value.get("automatic_rollback_after_post") is False
            and value.get("fixture_only") is True
            and value.get("read_scope_authority")
            == "NOT_GRANTED_STRUCTURAL_FIXTURE_ONLY"
            and value.get("execution_authority") == "NOT_GRANTED",
            "OFFLINE_STATE_BINDING_INVALID",
        )
        _verify_state_semantics(value, previous, binding)
        history.append(value)
        previous = value
        previous_time = checked_time
    lineage.require(
        history[0].get("state") == "PREFLIGHT"
        and history[1].get("state") == "CLAIMED",
        "OFFLINE_STATE_PREFIX_INVALID",
    )
    claim = lineage.load_json(claim_path)
    current = lineage.load_json(state_path)
    result = _exact(
        lineage.load_json(result_path),
        RESULT_FIELDS,
        "OFFLINE_TERMINAL_RESULT_SCHEMA_INVALID",
    )
    lineage.require(
        claim == history[1]
        and current == history[-1]
        and result.get("schema") == RESULT_SCHEMA
        and result.get("lineage") == lineage.LINEAGE
        and result.get("operation_id") == binding["operation_id"]
        and result.get("runtime_review_manifest_sha256")
        == binding["runtime_review_manifest_sha256"]
        and result.get("terminal_state") == current.get("state")
        and result.get("terminal_state_sha256")
        == lineage.canonical_digest(current)
        and result.get("max_attempts") == 1
        and result.get("simulated_post_attempts")
        == current.get("simulated_post_attempts")
        and result.get("real_post_attempts") == 0
        and result.get("automatic_retry") is False
        and result.get("automatic_rollback_after_post") is False
        and result.get("generated_command_executed") is False
        and result.get("transport_source_sha256")
        == binding["transport_source_sha256"]
        and result.get("core_source_sha256") == binding["core_source_sha256"]
        and result.get("builder_source_sha256")
        == binding["builder_source_sha256"]
        and result.get("readonly_verifier_source_sha256")
        == binding["readonly_verifier_source_sha256"]
        and result.get("executor_source_sha256")
        == binding["executor_source_sha256"]
        and result.get("collector_bytes_sha256")
        == binding["collector_bytes_sha256"]
        and result.get("strict_argv_sha256") == binding["strict_argv_sha256"]
        and result.get("candidate_archive_sha256")
        == binding["candidate_archive_sha256"]
        and result.get("rollback_archive_sha256")
        == binding["rollback_archive_sha256"]
        and result.get("fixture_only") is True
        and result.get("production_interaction") == "NOT_PERFORMED",
        "OFFLINE_TERMINAL_RESULT_INVALID",
    )
    expected_terminal = current.get("state")
    lineage.require(
        expected_terminal
        in {"PASS", "ABORTED_PRE_STAGE", "RECOVERED_PRE_POST", "HOLD_OWNER_REVIEW"},
        "OFFLINE_TERMINAL_STATE_INVALID",
    )
    rollback_path = operation / "recovery" / "rollback.archive"
    recovered_candidate_path = operation / "recovery" / "candidate.stage.recovered"
    stage_path = operation / "candidate.archive"
    if expected_terminal == "RECOVERED_PRE_POST":
        lineage.require(
            rollback_path.is_file()
            and not rollback_path.is_symlink()
            and lineage.sha256_file(rollback_path)
            == binding["rollback_archive_sha256"]
            and recovered_candidate_path.is_file()
            and not recovered_candidate_path.is_symlink()
            and lineage.sha256_file(recovered_candidate_path)
            == binding["candidate_archive_sha256"]
            and not stage_path.exists()
            and result.get("recovery")
            == "AUTOMATIC_LOCAL_SANDBOX_PRE_POST_ONLY"
            and result.get("original_cause") == "FAULT_AFTER_STAGE",
            "OFFLINE_RECOVERY_TERMINAL_INVALID",
        )
    elif expected_terminal == "HOLD_OWNER_REVIEW":
        lineage.require(
            not rollback_path.exists()
            and stage_path.is_file()
            and not stage_path.is_symlink()
            and lineage.sha256_file(stage_path)
            == binding["candidate_archive_sha256"]
            and result.get("recovery")
            in {
                "PROHIBITED_AFTER_PRE_POST_INTENT",
                "PROHIBITED_AFTER_POST_OBSERVED",
            }
            and result.get("original_cause") == current.get("cause")
            and result.get("recovery")
            == (
                "PROHIBITED_AFTER_PRE_POST_INTENT"
                if history[-2].get("state") == "PRE_POST_INTENT"
                else "PROHIBITED_AFTER_POST_OBSERVED"
            ),
            "OFFLINE_HOLD_RECOVERY_BOUNDARY_INVALID",
        )
    elif expected_terminal == "PASS":
        lineage.require(
            stage_path.is_file()
            and not stage_path.is_symlink()
            and lineage.sha256_file(stage_path)
            == binding["candidate_archive_sha256"]
            and not rollback_path.exists()
            and result.get("recovery") == "NOT_REQUIRED"
            and result.get("original_cause") is None,
            "OFFLINE_PASS_TERMINAL_INVALID",
        )
    else:
        lineage.require(
            not stage_path.exists()
            and not rollback_path.exists()
            and result.get("recovery") == "NOT_REQUIRED_NO_CANDIDATE_MUTATION"
            and result.get("original_cause") == "FAULT_AFTER_CLAIM",
            "OFFLINE_ABORT_TERMINAL_INVALID",
        )
    return {
        "status": "OFFLINE_RUNTIME_TERMINAL_VERIFIED",
        "operation_id": binding["operation_id"],
        "terminal_state": expected_terminal,
        "state_count": len(history),
        "claim_sha256": lineage.sha256_file(claim_path),
        "terminal_state_sha256": lineage.sha256_file(state_path),
        "result_sha256": lineage.sha256_file(result_path),
        "real_post_attempts": 0,
        "automatic_retry": False,
        "automatic_rollback_after_post": False,
        "production_interaction": "NOT_PERFORMED",
    }


def run_offline_state_machine(
    sandbox_parent: Path | str,
    *,
    base_package: Path | str,
    runtime_binding: object,
    readonly_request: object,
    scenario: object,
    candidate_archive: object,
    rollback_archive: object,
) -> dict[str, object]:
    """Exercise one complete sealed path in an owned local sandbox only."""
    binding = verify_runtime_binding(runtime_binding)
    request = readonly.verify_request_contract(readonly_request)
    lineage.require(
        lineage.canonical_digest(request) == binding["readonly_request_sha256"],
        "RUNTIME_READONLY_REQUEST_BINDING_MISMATCH",
    )
    verified = lineage.verify_package(
        base_package,
        expected_manifest_sha256=binding["base_package_manifest_sha256"],
        expected_head=binding["candidate_head"],
    )
    lineage.require(
        verified["bindings"]["operation_id"] == binding["operation_id"]
        == request["operation_id"],
        "RUNTIME_OPERATION_BINDING_MISMATCH",
    )
    checked_scenario = verify_scenario(scenario, str(binding["operation_id"]))
    candidate = _verify_archive(
        candidate_archive,
        request["candidate_identity"],
        "OFFLINE_CANDIDATE_ARCHIVE_MISMATCH",
    )
    rollback = _verify_archive(
        rollback_archive,
        request["rollback_identity"],
        "OFFLINE_ROLLBACK_ARCHIVE_MISMATCH",
    )

    parent = Path(sandbox_parent).resolve(strict=True)
    lineage.require(parent.is_dir() and not parent.is_symlink(), "OFFLINE_SANDBOX_PARENT_INVALID")
    root = parent / OFFLINE_RUNTIME_DIRECTORY
    root.mkdir(mode=0o700, exist_ok=True)
    lineage.require(root.is_dir() and not root.is_symlink(), "OFFLINE_SANDBOX_ROOT_INVALID")
    operation = root / str(binding["operation_id"])
    operation.mkdir(mode=0o700, exist_ok=True)
    state_path = operation / "state.json"
    claim_path = operation / "claim.json"
    stage_path = operation / "candidate.archive"
    recovery_directory = operation / "recovery"
    recovery_directory.mkdir(mode=0o700, exist_ok=True)

    preflight = _state(
        binding,
        "PREFLIGHT",
        0,
        str(checked_scenario["preflight_at_utc"]),
        None,
        simulated_post_attempts=0,
        claim_absent=not claim_path.exists(),
        stage_absent=not stage_path.exists(),
    )
    lineage.require(
        preflight["claim_absent"] is True and preflight["stage_absent"] is True,
        "OFFLINE_PREFLIGHT_ABSENCE_FAILED",
    )

    claim = _state(
        binding,
        "CLAIMED",
        1,
        str(checked_scenario["claimed_at_utc"]),
        lineage.canonical_digest(preflight),
        simulated_post_attempts=0,
        claim_id_sha256=lineage.canonical_digest(
            {
                "operation_id": binding["operation_id"],
                "runtime_review_manifest_sha256": binding[
                    "runtime_review_manifest_sha256"
                ],
            }
        ),
    )
    _write_exclusive(claim_path, claim)
    states = operation / "states"
    states.mkdir(mode=0o700)
    _sync_directory(operation)
    _write_exclusive(states / "000-PREFLIGHT.json", preflight)
    _write_exclusive(states / "001-CLAIMED.json", claim)
    _replace_json(state_path, claim)
    if checked_scenario["fault_mode"] == "AFTER_CLAIM":
        terminal_state = _transition(
            state_path,
            binding,
            "ABORTED_PRE_STAGE",
            2,
            str(checked_scenario["completed_at_utc"]),
            claim,
            simulated_post_attempts=0,
            cause="FAULT_AFTER_CLAIM",
            candidate_mutation=False,
        )
        return _terminal_result(
            operation,
            binding,
            terminal_state,
            "ABORTED_PRE_STAGE",
            recovery="NOT_REQUIRED_NO_CANDIDATE_MUTATION",
            original_cause="FAULT_AFTER_CLAIM",
        )

    _write_bytes_exclusive(stage_path, candidate)
    lineage.require(
        hashlib.sha256(stage_path.read_bytes()).hexdigest()
        == request["candidate_identity"]["archive_sha256"],
        "OFFLINE_STAGE_READBACK_MISMATCH",
    )
    staged = _transition(
        state_path,
        binding,
        "STAGED",
        2,
        str(checked_scenario["staged_at_utc"]),
        claim,
        simulated_post_attempts=0,
        candidate_archive_sha256=hashlib.sha256(candidate).hexdigest(),
        candidate_mutation=True,
    )
    if checked_scenario["fault_mode"] == "AFTER_STAGE":
        rollback_path = recovery_directory / "rollback.archive"
        _write_bytes_exclusive(rollback_path, rollback)
        recovered_candidate = recovery_directory / "candidate.stage.recovered"
        os.replace(stage_path, recovered_candidate)
        _sync_directory(operation)
        lineage.require(
            not stage_path.exists()
            and hashlib.sha256(rollback_path.read_bytes()).hexdigest()
            == request["rollback_identity"]["archive_sha256"],
            "OFFLINE_PRE_POST_RECOVERY_VERIFY_FAILED",
        )
        terminal_state = _transition(
            state_path,
            binding,
            "RECOVERED_PRE_POST",
            3,
            str(checked_scenario["completed_at_utc"]),
            staged,
            simulated_post_attempts=0,
            cause="FAULT_AFTER_STAGE",
            candidate_stage_present=False,
            rollback_verified=True,
        )
        return _terminal_result(
            operation,
            binding,
            terminal_state,
            "RECOVERED_PRE_POST",
            recovery="AUTOMATIC_LOCAL_SANDBOX_PRE_POST_ONLY",
            original_cause="FAULT_AFTER_STAGE",
        )

    intent = _transition(
        state_path,
        binding,
        "PRE_POST_INTENT",
        3,
        str(checked_scenario["pre_post_intent_at_utc"]),
        staged,
        simulated_post_attempts=0,
        candidate_stage_sha256=hashlib.sha256(stage_path.read_bytes()).hexdigest(),
        no_retry=True,
    )
    if checked_scenario["fault_mode"] == "AFTER_PRE_POST_INTENT":
        hold = _transition(
            state_path,
            binding,
            "HOLD_OWNER_REVIEW",
            4,
            str(checked_scenario["completed_at_utc"]),
            intent,
            simulated_post_attempts=1,
            cause="FAULT_AFTER_PRE_POST_INTENT",
            rollback_attempted=False,
            owner_review_required=True,
        )
        return _terminal_result(
            operation,
            binding,
            hold,
            "HOLD_OWNER_REVIEW",
            recovery="PROHIBITED_AFTER_PRE_POST_INTENT",
            original_cause="FAULT_AFTER_PRE_POST_INTENT",
        )

    observed = _transition(
        state_path,
        binding,
        "POST_OBSERVED",
        4,
        str(checked_scenario["post_observed_at_utc"]),
        intent,
        simulated_post_attempts=1,
        raw_response_sha256=hashlib.sha256(
            checked_scenario["raw_response"]
        ).hexdigest(),
        rollback_attempted=False,
    )
    if checked_scenario["fault_mode"] == "POST_OUTCOME_AMBIGUOUS":
        hold = _transition(
            state_path,
            binding,
            "HOLD_OWNER_REVIEW",
            5,
            str(checked_scenario["completed_at_utc"]),
            observed,
            simulated_post_attempts=1,
            cause="POST_OUTCOME_AMBIGUOUS",
            rollback_attempted=False,
            owner_review_required=True,
        )
        return _terminal_result(
            operation,
            binding,
            hold,
            "HOLD_OWNER_REVIEW",
            recovery="PROHIBITED_AFTER_POST_OBSERVED",
            original_cause="POST_OUTCOME_AMBIGUOUS",
        )

    try:
        receipt, _ = lineage._verify_fixture_response(
            checked_scenario["status_code"],
            checked_scenario["raw_response"],
            checked_scenario["semantic_receipt"],
            verified,
        )
        if checked_scenario["fault_mode"] == "READBACK_INVALID":
            raise lineage.NewLineageStop("FAULT_READBACK_INVALID")
        readback = lineage.verify_readback(
            checked_scenario["before"],
            checked_scenario["after"],
            receipt,
            checked_scenario["receipt_verification"],
            checked_scenario["verification_keys"],
            verified,
        )
    except Exception as error:
        cause = str(error) if isinstance(error, lineage.NewLineageStop) else type(error).__name__
        hold = _transition(
            state_path,
            binding,
            "HOLD_OWNER_REVIEW",
            5,
            str(checked_scenario["completed_at_utc"]),
            observed,
            simulated_post_attempts=1,
            cause=cause,
            rollback_attempted=False,
            owner_review_required=True,
        )
        return _terminal_result(
            operation,
            binding,
            hold,
            "HOLD_OWNER_REVIEW",
            recovery="PROHIBITED_AFTER_POST_OBSERVED",
            original_cause=cause,
        )

    passed = _transition(
        state_path,
        binding,
        "PASS",
        5,
        str(checked_scenario["completed_at_utc"]),
        observed,
        simulated_post_attempts=1,
        readback_sha256=lineage.canonical_digest(readback),
        rollback_attempted=False,
    )
    return _terminal_result(
        operation,
        binding,
        passed,
        "PASS",
        recovery="NOT_REQUIRED",
        original_cause=None,
    )


def refuse_real_runtime() -> None:
    raise lineage.NewLineageStop("REAL_EXECUTION_RUNTIME_NOT_AUTHORIZED")
