"""Closed, shared binding contract for the one-use Owner-fence package.

This file is embedded unchanged into both remote entrypoints. It has no I/O.
"""

import hashlib
import json

if "canonical_docker_mounts" not in globals():
    from owner_fence_representation import canonical_docker_mounts


def _package_canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _package_sha(raw):
    return hashlib.sha256(raw).hexdigest()

EXPECTED_CONTEXT_FIELDS = frozenset({
    "approval_b64", "approval_sha256", "attempt_id", "base_compose",
    "base_compose_sha256", "candidate_head",
    "candidate_image_config", "candidate_image_semantic_sha256",
    "candidate_override_sha256", "candidate_tag", "control_directory",
    "creation_settings", "current_container_id", "current_native_config_sha256",
    "current_override", "current_override_sha256", "current_topology_sha256",
    "gate_d_sha256", "native_lead_probe_b64", "native_lead_probe_sha256",
    "native_probe_b64", "native_probe_sha256", "old_authority_denylist",
    "override_b64", "post_stop_reseal_allowed_fields", "preflight",
    "preflight_evidence_sha256", "protected18_sha256", "recovery_custody",
    "recovery_override", "recovery_override_sha256", "rollback_image_config",
    "semantic_baseline_projection_sha256", "semantic_prestop_baseline",
    "sealed_mounts", "sealed_command_sha256", "sealed_entrypoint_sha256",
    "representation_contract_sha256",
    "settings_preimage", "source_sha256", "timing", "timing_receipt_sha256",
    "workdir",
})

EXPECTED_PREFLIGHT_FIELDS = frozenset({
    "approval_sha256", "attempt_id", "capture_sha256",
    "full_environment_fingerprint_sha256", "gate_d_sha256",
    "production_writes", "schema", "sealed_utc",
    "semantic_baseline_projection_sha256", "status",
})

EXPECTED_TIMING_FIELDS = frozenset({
    "approval_sha256", "attempt_id", "candidate_decision_deadline_utc",
    "candidate_verification_deadline_utc", "entry_deadline_utc",
    "gate_d_sha256", "issued_utc", "owner_grant_observed_utc",
    "recovery_completion_deadline_utc", "schema",
    "stop_completion_deadline_utc",
})


def verify_package_contract(context):
    """Reject missing/extra authority fields and mismatched baseline bindings."""
    if not isinstance(context, dict) or set(context) != EXPECTED_CONTEXT_FIELDS:
        raise RuntimeError("EXECUTION_CONTEXT_SCHEMA_MISMATCH")
    if canonical_docker_mounts(context["sealed_mounts"], target=True) != context["sealed_mounts"]:
        raise RuntimeError("SEALED_MOUNT_CANONICAL_FORM_INVALID")
    for field in ("sealed_command_sha256", "sealed_entrypoint_sha256", "representation_contract_sha256"):
        value = context[field]
        if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise RuntimeError("SEALED_REPRESENTATION_BINDING_INVALID:" + field)
    preflight = context["preflight"]
    if not isinstance(preflight, dict) or set(preflight) != EXPECTED_PREFLIGHT_FIELDS:
        raise RuntimeError("PREFLIGHT_SCHEMA_MISMATCH")
    timing = context["timing"]
    if not isinstance(timing, dict) or set(timing) != EXPECTED_TIMING_FIELDS:
        raise RuntimeError("TIMING_SCHEMA_MISMATCH")
    if preflight["status"] != "PASS_FRESH_READONLY_PREFLIGHT" or preflight["production_writes"] != 0:
        raise RuntimeError("PREFLIGHT_STATUS_INVALID")
    baseline_digest = _package_sha(_package_canonical(context["semantic_prestop_baseline"]))
    if baseline_digest != context["semantic_baseline_projection_sha256"]:
        raise RuntimeError("SEMANTIC_BASELINE_PROJECTION_DIGEST_MISMATCH")
    if preflight["semantic_baseline_projection_sha256"] != baseline_digest:
        raise RuntimeError("PREFLIGHT_BASELINE_BINDING_MISMATCH")
    for field in ("attempt_id", "approval_sha256", "gate_d_sha256"):
        if preflight[field] != context[field] or timing[field] != context[field]:
            raise RuntimeError("IDENTITY_BINDING_MISMATCH:" + field)
    if _package_sha(_package_canonical(preflight)) != context["preflight_evidence_sha256"]:
        raise RuntimeError("PREFLIGHT_DIGEST_MISMATCH")
    if _package_sha(_package_canonical(timing)) != context["timing_receipt_sha256"]:
        raise RuntimeError("TIMING_DIGEST_MISMATCH")
