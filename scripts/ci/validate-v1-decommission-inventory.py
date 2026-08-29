#!/usr/bin/env python3
"""Validate the AH-01 machine-readable inventory and its safety gates."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AUDIT_DIR = ROOT / "docs" / "video-factory-v1-decommission"
INVENTORY = AUDIT_DIR / "v1-components.json"
STORAGE_MANIFEST = AUDIT_DIR / "v1-storage-ownership-manifest.json"
PROVENANCE_MANIFEST = AUDIT_DIR / "v1-runtime-image-provenance.json"
BACKUP_RESTORE_EVIDENCE = AUDIT_DIR / "v1-backup-restore-evidence.json"
PUBLICATION_CATALOG = AUDIT_DIR / "v1-publication-reference-catalog.json"
PUBLICATION_EVIDENCE = AUDIT_DIR / "v1-publication-reference-evidence.json"
BACKUP_CUSTODY = AUDIT_DIR / "v1-backup-custody.json"
REDIS_M0_EVIDENCE = AUDIT_DIR / "agent-hub-redis-m0-evidence.json"
REQUIRED_TOOLING = {
    ROOT / "scripts" / "ops" / "v1_backup" / "README.md",
    ROOT / "scripts" / "ops" / "v1_backup" / "export-db0-readonly.sh",
    ROOT / "scripts" / "ops" / "v1_backup" / "verify_redis_export.py",
    ROOT / "scripts" / "ops" / "agent_hub_redis" / "README.md",
    ROOT / "scripts" / "ops" / "agent_hub_redis" / "run_synthetic_restore_drill.py",
    ROOT / "scripts" / "ops" / "v1_publication_audit" / "README.md",
    ROOT / "scripts" / "ops" / "v1_publication_audit" / "audit_wordpress_public.py",
    ROOT / "apps" / "api" / "app" / "legacy_telemetry.py",
    ROOT / "renderer" / "src" / "legacyTelemetry.ts",
    ROOT / "renderer" / "src" / "smoke-legacy-telemetry.ts",
}

ALLOWED_DECISIONS = {
    "KEEP",
    "REPLACE_WITH_V2_API",
    "MIGRATE",
    "DEPRECATE",
    "DISABLE",
    "DELETE_LATER",
    "UNKNOWN",
}
ALLOWED_ROUTE_STATES = {
    "ACTIVE",
    "PROXY_TO_V2",
    "DEPRECATED",
    "DISABLED",
    "DELETE_LATER",
}
REQUIRED_DOCS = {
    "README.md",
    "V1_DEPENDENCY_AUDIT.md",
    "V1_RUNTIME_USAGE_AUDIT.md",
    "V1_TO_V2_CAPABILITY_MAP.md",
    "SHUTDOWN_PLAN.md",
    "ROLLBACK.md",
    "RISK_REGISTER.md",
    "v1-components.json",
    "AH01B_EVIDENCE.md",
    "AGENT_HUB_REDIS_OWNERSHIP_MIGRATION_PLAN.md",
    "V1_BACKUP_RESTORE_PLAN.md",
    "V1_PUBLICATION_REFERENCE_AUDIT.md",
    "LEGACY_PR_DECISIONS.md",
    "v1-storage-ownership-manifest.json",
    "v1-runtime-image-provenance.json",
    "v1-backup-restore-evidence.json",
    "AH01C_READINESS_CLOSURE.md",
    "BACKUP_CUSTODY_PLAN.md",
    "LEGACY_TELEMETRY_PLAN.md",
    "PRE_AH03_SNAPSHOT_RUNBOOK.md",
    "v1-publication-reference-catalog.json",
    "v1-publication-reference-evidence.json",
    "v1-backup-custody.json",
    "agent-hub-redis-m0-evidence.json",
}
REQUIRED_COMPONENT_FIELDS = {
    "id",
    "component",
    "type",
    "location",
    "runtime_active",
    "current_state",
    "last_known_use",
    "active_consumers",
    "data_ownership",
    "dependencies",
    "replacement",
    "migration_requirement",
    "shutdown_risk",
    "decision",
    "owner_gate",
    "evidence",
}
FORBIDDEN_SECRET_PATTERNS = (
    re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{16,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def fail(message: str) -> None:
    raise SystemExit(f"inventory validation failed: {message}")


def validate_sha256(value: object, *, context: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        fail(f"{context} must be a lowercase SHA-256")


def validate_storage_manifest() -> None:
    payload = json.loads(STORAGE_MANIFEST.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "1.0":
        fail("storage manifest schema_version must be 1.0")

    files = payload.get("files")
    groups = payload.get("ownership_groups")
    if not isinstance(files, list) or not files:
        fail("storage manifest files must be a non-empty list")
    if not isinstance(groups, list) or not groups:
        fail("storage manifest ownership_groups must be a non-empty list")

    paths: list[str] = []
    for index, item in enumerate(files):
        if not isinstance(item, dict):
            fail(f"storage file {index} is not an object")
        path = item.get("path")
        if (
            not isinstance(path, str)
            or not path
            or path.startswith(("/", "\\"))
            or ".." in Path(path).parts
        ):
            fail(f"storage file {index} has unsafe path {path!r}")
        paths.append(path)
        if not isinstance(item.get("size_bytes"), int) or item["size_bytes"] < 0:
            fail(f"storage file {path} has invalid size")
        if not isinstance(item.get("mtime_utc"), str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z", item["mtime_utc"]
        ):
            fail(f"storage file {path} has invalid mtime_utc")
        validate_sha256(item.get("sha256"), context=f"storage file {path}")
        if item.get("decision") not in ALLOWED_DECISIONS:
            fail(f"storage file {path} has invalid decision")
        if item.get("owner") in (None, "", "UNKNOWN"):
            fail(f"storage file {path} has unresolved owner")
        if not isinstance(item.get("protected_from_v1_decommission"), bool):
            fail(f"storage file {path} has invalid protection flag")

    duplicates = sorted(item for item, count in Counter(paths).items() if count > 1)
    if duplicates:
        fail(f"storage manifest has duplicate paths: {', '.join(duplicates[:5])}")

    summary = payload.get("summary") or {}
    if summary.get("file_count") != len(files):
        fail("storage summary.file_count is stale")
    if summary.get("total_bytes") != sum(item["size_bytes"] for item in files):
        fail("storage summary.total_bytes is stale")
    if summary.get("top_level_groups") != len(groups):
        fail("storage summary.top_level_groups is stale")
    if summary.get("whole_root_mutation_allowed") is not False:
        fail("storage whole_root_mutation_allowed must remain false")

    group_prefixes: list[str] = []
    unknown_groups: list[str] = []
    for group in groups:
        prefix = group.get("path_prefix")
        if not isinstance(prefix, str) or not prefix.endswith("/"):
            fail(f"storage group has invalid prefix {prefix!r}")
        group_prefixes.append(prefix)
        matches = [item for item in files if item["path"].startswith(prefix)]
        if group.get("file_count") != len(matches):
            fail(f"storage group {prefix} file_count is stale")
        if group.get("total_bytes") != sum(item["size_bytes"] for item in matches):
            fail(f"storage group {prefix} total_bytes is stale")
        if group.get("decision") == "UNKNOWN":
            unknown_groups.append(prefix)
        if group.get("owner") in (None, "", "UNKNOWN"):
            fail(f"storage group {prefix} has unresolved owner")
    if len(group_prefixes) != len(set(group_prefixes)):
        fail("storage manifest has duplicate ownership group prefixes")
    if sorted(summary.get("unknown_groups") or []) != sorted(unknown_groups):
        fail("storage summary.unknown_groups is stale")
    for path in paths:
        if sum(path.startswith(prefix) for prefix in group_prefixes) != 1:
            fail(f"storage file {path} must map to exactly one ownership group")


def validate_provenance_manifest() -> None:
    payload = json.loads(PROVENANCE_MANIFEST.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "1.0":
        fail("provenance manifest schema_version must be 1.0")
    if not isinstance(payload.get("method"), str) or not payload["method"].strip():
        fail("provenance manifest must record its comparison method")
    if "runtime image content" not in str(payload.get("source_file_hash_semantics")):
        fail("provenance manifest must define source-file hash semantics")
    if not re.fullmatch(
        r"[0-9a-f]{40}", str(payload.get("production_checkout") or "")
    ):
        fail("provenance manifest has invalid production checkout")
    services = payload.get("services")
    if not isinstance(services, list) or not services:
        fail("provenance services must be a non-empty list")

    names: list[str] = []
    total_files = 0
    total_mismatches = 0
    for item in services:
        name = item.get("service")
        if name not in {"api", "worker", "renderer"}:
            fail(f"provenance has unexpected service {name!r}")
        names.append(name)
        image_id = item.get("image_id")
        if not isinstance(image_id, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
            fail(f"provenance {name} has invalid image ID")
        if not isinstance(item.get("created"), str) or "T" not in item["created"]:
            fail(f"provenance {name} has invalid image created metadata")
        if not isinstance(item.get("size_bytes"), int) or item["size_bytes"] <= 0:
            fail(f"provenance {name} has invalid image size")
        if not isinstance(item.get("repo_tags"), list) or not isinstance(
            item.get("repo_digests"), list
        ):
            fail(f"provenance {name} has invalid tag/digest metadata")
        if not re.fullmatch(r"[0-9a-f]{40}", str(item.get("source_commit") or "")):
            fail(f"provenance {name} has invalid source commit")
        files = item.get("source_files")
        if not isinstance(files, list) or not files:
            fail(f"provenance {name} has no source files")
        if item.get("copied_source_files_observed") != len(files):
            fail(f"provenance {name} source file count is stale")
        paths: list[str] = []
        for source_file in files:
            path = source_file.get("path")
            if not isinstance(path, str) or not path or path.startswith(("/", "\\")):
                fail(f"provenance {name} has unsafe source path {path!r}")
            paths.append(path)
            validate_sha256(
                source_file.get("sha256"), context=f"provenance {name} source {path}"
            )
        if len(paths) != len(set(paths)):
            fail(f"provenance {name} has duplicate source paths")
        mismatch_count = item.get("source_mismatch_count")
        if not isinstance(mismatch_count, int) or mismatch_count < 0:
            fail(f"provenance {name} has invalid mismatch count")
        if mismatch_count == 0 and item.get("source_match_status") != "MATCH":
            fail(f"provenance {name} zero mismatches must have MATCH status")
        total_files += len(files)
        total_mismatches += mismatch_count

    if len(names) != len(set(names)):
        fail("provenance manifest has duplicate services")
    summary = payload.get("summary") or {}
    if summary.get("service_count") != len(services):
        fail("provenance summary.service_count is stale")
    if summary.get("observed_source_file_count") != total_files:
        fail("provenance summary.observed_source_file_count is stale")
    if summary.get("source_mismatch_count") != total_mismatches:
        fail("provenance summary.source_mismatch_count is stale")
    if summary.get("portable_rollback_bundle_verified") is not True:
        fail("portable rollback must remain verified after the real restore drill passes")


def validate_backup_restore_evidence() -> None:
    payload = json.loads(BACKUP_RESTORE_EVIDENCE.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "1.0":
        fail("backup evidence schema_version must be 1.0")
    if payload.get("technical_restore_status") != "PASS":
        fail("backup evidence technical_restore_status must be PASS")
    if payload.get("complete_v1_bundle_restore") is not True:
        fail("backup evidence complete_v1_bundle_restore must be true")
    if payload.get("owner_acceptance_status") != "PENDING":
        fail("backup evidence must preserve the pending owner acceptance gate")
    if not isinstance(payload.get("bundle_total_bytes"), int) or payload["bundle_total_bytes"] <= 0:
        fail("backup evidence has invalid bundle_total_bytes")

    encryption = payload.get("encryption") or {}
    if encryption.get("payload_cipher") != "AES-256-GCM":
        fail("backup evidence payload cipher must be AES-256-GCM")
    if encryption.get("key_protection") != "Windows DPAPI CurrentUser":
        fail("backup evidence key protection must remain Windows DPAPI CurrentUser")
    for field in ("plaintext_payload_at_rest", "key_material_committed", "key_material_logged"):
        if encryption.get(field) is not False:
            fail(f"backup evidence encryption.{field} must be false")

    boundary = payload.get("capture_boundary") or {}
    for field in (
        "production_write_performed",
        "remote_temporary_file_created",
        "redis_save_or_bgsave_called",
        "agent_hub_db1_exported",
    ):
        if boundary.get(field) is not False:
            fail(f"backup evidence capture_boundary.{field} must be false")
    if boundary.get("pre_and_post_snapshot_match") is not True:
        fail("backup evidence production snapshots must match")
    if boundary.get("v1_db0_key_count") != 12:
        fail("backup evidence must record the 12-key V1 DB0 snapshot")
    if boundary.get("v1_queue_length") != 0 or boundary.get("v1_processing_length") != 0:
        fail("backup evidence must preserve the empty V1 queue/processing snapshot")

    payloads = payload.get("payloads")
    if not isinstance(payloads, list) or len(payloads) != 16:
        fail("backup evidence must contain 16 encrypted payload records")
    names: list[str] = []
    for index, item in enumerate(payloads):
        if not isinstance(item, dict):
            fail(f"backup evidence payload {index} is not an object")
        name = item.get("name")
        if not isinstance(name, str) or not name:
            fail(f"backup evidence payload {index} has invalid name")
        names.append(name)
        if not isinstance(item.get("ciphertext_bytes"), int) or item["ciphertext_bytes"] <= 0:
            fail(f"backup evidence payload {name} has invalid ciphertext_bytes")
        validate_sha256(item.get("ciphertext_sha256"), context=f"backup payload {name}")
    if len(names) != len(set(names)):
        fail("backup evidence has duplicate payload names")
    if payload["bundle_total_bytes"] < sum(item["ciphertext_bytes"] for item in payloads):
        fail("backup evidence bundle_total_bytes is smaller than its encrypted payloads")
    required_payloads = {
        "redis-db0-primary",
        "redis-db0-confirmation",
        "storage",
        "pilot",
        "runtime",
        "exact-image-api",
        "exact-image-worker",
        "exact-image-renderer",
        "exact-image-redis",
    }
    if not required_payloads.issubset(names):
        fail("backup evidence is missing a required encrypted payload")

    checks = payload.get("restore_checks") or {}
    if checks.get("encrypted_payload_count") != len(payloads):
        fail("backup evidence encrypted_payload_count is stale")
    redis = checks.get("redis_db0") or {}
    if (
        redis.get("status") != "PASS"
        or redis.get("restored_key_count") != boundary.get("v1_db0_key_count")
        or redis.get("queue_length") != boundary.get("v1_queue_length")
        or redis.get("processing_length") != boundary.get("v1_processing_length")
        or redis.get("post_restart_checksum_type_ttl_parity") is not True
    ):
        fail("backup evidence Redis DB0 restore checks are incomplete")
    for section in ("storage", "production_pilot_artifacts", "protected_runtime"):
        item = checks.get(section) or {}
        if item.get("status") != "PASS":
            fail(f"backup evidence {section} status must be PASS")
        if not isinstance(item.get("file_count"), int) or item["file_count"] <= 0:
            fail(f"backup evidence {section} file_count is invalid")
        if not isinstance(item.get("total_bytes"), int) or item["total_bytes"] <= 0:
            fail(f"backup evidence {section} total_bytes is invalid")
    if (checks.get("protected_runtime") or {}).get("plaintext_logged") is not False:
        fail("backup evidence must not log protected runtime plaintext")

    images = checks.get("exact_images") or {}
    if (
        images.get("status") != "PASS"
        or images.get("production_config_to_local_oci_manifest_verified") is not True
        or images.get("mutable_tags_loaded") is not False
    ):
        fail("backup evidence exact-image restore checks are incomplete")
    for service in ("api", "worker", "renderer", "redis"):
        item = images.get(service) or {}
        for field in ("production_config_id", "local_oci_manifest_id"):
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(item.get(field) or "")):
                fail(f"backup evidence exact image {service}.{field} is invalid")

    isolated = checks.get("isolated_runtime") or {}
    if (
        isolated.get("status") != "PASS"
        or isolated.get("network_internal") is not True
        or isolated.get("published_ports") != 0
        or isolated.get("api_health_ready_job_read") != "PASS"
        or isolated.get("renderer_health") != "PASS"
        or isolated.get("post_restart_read") != "PASS"
        or isolated.get("worker_started") is not False
        or isolated.get("provider_credentials_supplied") is not False
        or isolated.get("provider_or_publish_call_performed") is not False
    ):
        fail("backup evidence isolated runtime safety checks are incomplete")
    cleanup = checks.get("cleanup") or {}
    if cleanup.get("status") != "PASS" or any(
        cleanup.get(field) != 0
        for field in (
            "leftover_containers",
            "leftover_volumes",
            "leftover_networks",
            "plaintext_temporary_files",
        )
    ):
        fail("backup evidence cleanup checks are incomplete")

    for name, value in (payload.get("evidence_hashes") or {}).items():
        validate_sha256(value, context=f"backup evidence hash {name}")
    if len(payload.get("evidence_hashes") or {}) != 3:
        fail("backup evidence must preserve all three evidence hashes")

    postcheck = payload.get("production_postcheck") or {}
    if (
        postcheck.get("checkout_and_image_ids_unchanged") is not True
        or postcheck.get("container_restart_counts") != 0
        or postcheck.get("v1_db0_key_count") != boundary.get("v1_db0_key_count")
        or postcheck.get("v1_queue_length") != boundary.get("v1_queue_length")
        or postcheck.get("v1_processing_length") != boundary.get("v1_processing_length")
        or any(
            postcheck.get(field) != 0
            for field in (
                "api_job_posts_since_capture",
                "worker_jobs_since_capture",
                "renderer_renders_since_capture",
            )
        )
    ):
        fail("backup evidence production postcheck is incomplete")

    gates = payload.get("remaining_gates") or {}
    for field in (
        "owner_bundle_retention_and_dpapi_key_custody_acceptance",
        "second_protected_copy_recommended_before_any_shutdown",
        "agent_hub_db1_backup_and_migration_separate",
        "publication_reference_catalog_unresolved",
    ):
        if gates.get(field) is not True:
            fail(f"backup evidence remaining_gates.{field} must remain true")
    if gates.get("destructive_change_allowed") is not False or gates.get("v1_decommission") != "NO-GO":
        fail("backup evidence must preserve the V1 decommission NO-GO gate")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_publication_closure() -> None:
    catalog = json.loads(PUBLICATION_CATALOG.read_text(encoding="utf-8"))
    if catalog.get("schema_version") != "1.0" or catalog.get("catalog_status") != "RESOLVED_CONSERVATIVE":
        fail("publication catalog must be a resolved conservative v1.0 catalog")
    allowed = {
        "ACTIVE_REFERENCE",
        "ARCHIVE_REQUIRED",
        "REDIRECT_REQUIRED",
        "SAFE_TO_RETIRE",
        "UNKNOWN",
    }
    if set(catalog.get("allowed_classifications") or []) != allowed:
        fail("publication catalog classification enum is invalid")
    if catalog.get("destructive_change_allowed") is not False or catalog.get("v1_decommission") != "NO-GO":
        fail("publication catalog must preserve destructive=false and V1 NO-GO")
    policy = catalog.get("coverage_policy") or {}
    if (
        policy.get("unseen_reference_fallback") != "ARCHIVE_REQUIRED"
        or policy.get("live_url_fallback") != "REDIRECT_REQUIRED"
        or policy.get("absence_authorizes_deletion") is not False
        or policy.get("refresh_required_before_ah03") is not True
    ):
        fail("publication catalog fallback policy is not fail-closed")

    records = catalog.get("records")
    if not isinstance(records, list) or not records:
        fail("publication catalog records must be a non-empty list")
    ids: list[str] = []
    classifications: Counter[str] = Counter()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            fail(f"publication record {index} is not an object")
        record_id = record.get("id")
        classification = record.get("classification")
        if not isinstance(record_id, str) or not record_id:
            fail(f"publication record {index} has invalid id")
        if classification not in allowed:
            fail(f"publication record {record_id} has invalid classification")
        if classification == "UNKNOWN":
            fail(f"publication record {record_id} must not remain UNKNOWN in AH-01C")
        if record.get("deletion_allowed") is not False:
            fail(f"publication record {record_id} must not allow deletion")
        ids.append(record_id)
        classifications[classification] += 1
    if len(ids) != len(set(ids)):
        fail("publication catalog contains duplicate record IDs")

    storage = json.loads(STORAGE_MANIFEST.read_text(encoding="utf-8"))
    expected_job_ids = sorted(
        {
            parts[1]
            for item in storage.get("files") or []
            if len(parts := str(item.get("path") or "").split("/")) >= 3
            and parts[0] == "jobs"
            and parts[1].startswith("vid_")
        }
    )
    job_records = [record for record in records if record.get("record_type") == "V1_JOB"]
    actual_job_ids = sorted(str(record.get("job_id") or "") for record in job_records)
    if actual_job_ids != expected_job_ids or len(actual_job_ids) != 12:
        fail("publication catalog does not cover every retained V1 job exactly once")
    active_jobs = [record for record in job_records if record["classification"] == "ACTIVE_REFERENCE"]
    if [record["job_id"] for record in active_jobs] != ["vid_1786695599261_60dbfd66ed"]:
        fail("publication catalog must preserve the known V3 source lineage")

    summary = catalog.get("summary") or {}
    if (
        summary.get("record_count") != len(records)
        or summary.get("by_classification") != dict(sorted(classifications.items()))
        or summary.get("unknown_count") != 0
        or summary.get("v1_job_count") != len(job_records)
        or summary.get("v1_jobs_with_final_mp4") != sum(
            record.get("final_mp4_bytes") is not None for record in job_records
        )
    ):
        fail("publication catalog summary is stale")

    evidence = json.loads(PUBLICATION_EVIDENCE.read_text(encoding="utf-8"))
    if (
        evidence.get("schema_version") != "1.0"
        or evidence.get("status") != "PASS"
        or evidence.get("read_only") is not True
        or evidence.get("production_write_performed") is not False
        or evidence.get("secret_logged") is not False
        or evidence.get("raw_business_payload_logged") is not False
    ):
        fail("publication evidence safety envelope is invalid")
    sources = evidence.get("sources") or []
    expected_source_ids = {
        "v1-db0-job-metadata",
        "v1-public-read-routes",
        "wordpress-public-rest",
        "primary-facebook-page",
        "production-n8n",
        "agent-hub-db1",
        "content-publisher-state",
        "repository-and-owner-review",
    }
    if {item.get("id") for item in sources if isinstance(item, dict)} != expected_source_ids:
        fail("publication evidence source coverage is incomplete")
    if any(item.get("status") != "PASS" for item in sources):
        fail("publication evidence contains a non-PASS source")
    fallback = evidence.get("fallback_disposition") or {}
    if (
        fallback.get("unseen_or_late_discovered_reference") != "ARCHIVE_REQUIRED"
        or fallback.get("live_legacy_url") != "REDIRECT_REQUIRED"
        or fallback.get("deletion_by_absence_allowed") is not False
    ):
        fail("publication evidence fallback is not fail-closed")


def validate_backup_custody() -> None:
    payload = json.loads(BACKUP_CUSTODY.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "1.0" or payload.get("status") != "PENDING_OWNER_CUSTODY_GATE":
        fail("backup custody must remain pending the owner custody gate")
    if payload.get("production_write_performed") is not False or payload.get("secret_logged") is not False:
        fail("backup custody safety flags are invalid")
    primary = payload.get("primary_copy") or {}
    if (
        primary.get("bundle_id") != "v1-backup-restore-20260829T045502Z"
        or primary.get("bundle_total_bytes") != 1895938306
        or primary.get("payload_count") != 16
        or primary.get("payload_cipher") != "AES-256-GCM"
        or primary.get("technical_restore_status") != "PASS"
        or primary.get("complete_v1_bundle_restore") is not True
    ):
        fail("backup custody primary copy does not match restore-tested evidence")
    validate_sha256(primary.get("manifest_sha256"), context="backup custody manifest")
    second = payload.get("second_protected_copy") or {}
    if second.get("status") != "NOT_CREATED" or second.get("same_device_copy_qualifies") is not False:
        fail("backup custody must not claim an unverified second protected copy")
    key_custody = payload.get("restore_key_custody") or {}
    validate_sha256(key_custody.get("dpapi_blob_sha256"), context="backup custody DPAPI blob")
    if (
        key_custody.get("plaintext_key_at_rest") is not False
        or key_custody.get("plaintext_key_logged") is not False
        or key_custody.get("portable_recovery_proven") is not False
    ):
        fail("backup key custody must preserve the pending portable-recovery gate")
    gate = payload.get("gate") or {}
    if (
        gate.get("primary_copy_technical_restore") != "PASS"
        or gate.get("backup_custody_accepted") is not False
        or gate.get("v1_shutdown_authorized") is not False
        or gate.get("destructive_change_allowed") is not False
    ):
        fail("backup custody must preserve owner and shutdown gates")


def validate_redis_m0_evidence() -> None:
    payload = json.loads(REDIS_M0_EVIDENCE.read_text(encoding="utf-8"))
    if (
        payload.get("schema_version") != "1.0"
        or payload.get("scope") != "synthetic_agent_hub_redis_m0"
        or payload.get("status") != "PASS"
        or payload.get("production_connection_performed") is not False
        or payload.get("production_write_performed") is not False
    ):
        fail("Redis M0 evidence safety envelope is invalid")
    tested = payload.get("tested_sources") or {}
    expected_sources = {
        "maintenance_py_sha256": ROOT / "services" / "agent_hub" / "npd_agent_hub" / "maintenance.py",
        "drill_py_sha256": ROOT / "scripts" / "ops" / "agent_hub_redis" / "run_synthetic_restore_drill.py",
    }
    for field, path in expected_sources.items():
        validate_sha256(tested.get(field), context=f"Redis M0 {field}")
        if tested[field] != file_sha256(path):
            fail(f"Redis M0 evidence is stale for {path.relative_to(ROOT)}")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(payload.get("redis_image_id") or "")):
        fail("Redis M0 exact image ID is invalid")
    isolation = payload.get("synthetic_isolation") or {}
    if (
        isolation.get("remote_exposure") is not False
        or isolation.get("leftover_containers") != 0
        or isolation.get("leftover_volumes") != 0
    ):
        fail("Redis M0 synthetic cleanup/isolation is incomplete")
    checks = payload.get("checks") or {}
    for field in (
        "namespace_only_export",
        "unsupported_type_fail_closed",
        "non_empty_target_fail_closed",
        "namespace_mismatch_fail_closed",
        "checksum_corruption_fail_closed_before_write",
        "first_restore_parity",
        "ttl_semantics",
        "outside_namespace_preserved",
        "explicit_replace_rollback_parity",
        "target_restart_persistence",
    ):
        if checks.get(field) != "PASS":
            fail(f"Redis M0 check {field} must be PASS")
    gate = payload.get("gate") or {}
    if (
        gate.get("m0_offline_tooling") != "PASS"
        or gate.get("production_db1_export_restore") != "NOT_RUN"
        or gate.get("production_migration_authorized") is not False
        or gate.get("v1_shutdown_authorized") is not False
    ):
        fail("Redis M0 evidence must preserve production migration gates")


def validate_telemetry_source_gate() -> None:
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    if not re.search(r"(?m)^LEGACY_TELEMETRY_SALT=$", env_example):
        fail(".env.example must declare an empty legacy telemetry salt")
    worker = (ROOT / "services" / "worker" / "npd_worker" / "pipeline.py").read_text(
        encoding="utf-8"
    )
    tools = (ROOT / "services" / "agent_hub" / "npd_agent_hub" / "tools.py").read_text(
        encoding="utf-8"
    )
    if "video-factory-v1-worker" not in worker or "agent-hub-v1-tool" not in tools:
        fail("known V1 callers must send non-secret telemetry labels")


def main() -> None:
    missing_docs = sorted(name for name in REQUIRED_DOCS if not (AUDIT_DIR / name).is_file())
    if missing_docs:
        fail(f"missing deliverables: {', '.join(missing_docs)}")
    missing_tooling = sorted(str(path.relative_to(ROOT)) for path in REQUIRED_TOOLING if not path.is_file())
    if missing_tooling:
        fail(f"missing AH-01B/AH-01C tooling: {', '.join(missing_tooling)}")

    payload = json.loads(INVENTORY.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "1.0":
        fail("schema_version must be 1.0")
    if set(payload.get("allowed_decisions") or []) != ALLOWED_DECISIONS:
        fail("allowed_decisions does not match the AH-01 enum")

    components = payload.get("components")
    if not isinstance(components, list) or not components:
        fail("components must be a non-empty list")

    ids: list[str] = []
    for index, component in enumerate(components):
        if not isinstance(component, dict):
            fail(f"component {index} is not an object")
        missing = sorted(REQUIRED_COMPONENT_FIELDS - component.keys())
        if missing:
            fail(f"component {index} missing fields: {', '.join(missing)}")
        component_id = component["id"]
        if not isinstance(component_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]+", component_id):
            fail(f"invalid component id at index {index}: {component_id!r}")
        ids.append(component_id)
        if component["decision"] not in ALLOWED_DECISIONS:
            fail(f"{component_id} has invalid decision {component['decision']!r}")
        if component["runtime_active"] not in (True, False, None):
            fail(f"{component_id} runtime_active must be true, false, or null")
        for field in ("active_consumers", "dependencies", "evidence"):
            if not isinstance(component[field], list):
                fail(f"{component_id} {field} must be a list")
        if not component["evidence"]:
            fail(f"{component_id} must include evidence")
        for field in ("route_state_current", "route_state_target"):
            value = component.get(field)
            if value is not None and value not in ALLOWED_ROUTE_STATES:
                fail(f"{component_id} has invalid {field}={value!r}")

    duplicate_ids = sorted(item for item, count in Counter(ids).items() if count > 1)
    if duplicate_ids:
        fail(f"duplicate ids: {', '.join(duplicate_ids)}")

    known_ids = set(ids)
    for component in components:
        unknown_dependencies = sorted(set(component["dependencies"]) - known_ids)
        if unknown_dependencies:
            fail(
                f"{component['id']} references missing dependencies: "
                f"{', '.join(unknown_dependencies)}"
            )

    decision_counts = Counter(component["decision"] for component in components)
    unknown_ids = sorted(
        component["id"] for component in components if component["decision"] == "UNKNOWN"
    )
    summary = payload.get("summary") or {}
    if summary.get("component_count") != len(components):
        fail("summary.component_count is stale")
    if summary.get("by_decision") != dict(sorted(decision_counts.items())):
        fail("summary.by_decision is stale")
    if summary.get("unknown_component_ids") != unknown_ids:
        fail("summary.unknown_component_ids is stale")
    if unknown_ids:
        fail(f"AH-01C inventory must have zero UNKNOWN decisions: {', '.join(unknown_ids)}")
    if summary.get("destructive_change_allowed") is not False:
        fail("destructive_change_allowed must remain false after UNKNOWN reaches zero")

    validate_storage_manifest()
    validate_provenance_manifest()
    validate_backup_restore_evidence()
    validate_publication_closure()
    validate_backup_custody()
    validate_redis_m0_evidence()
    validate_telemetry_source_gate()

    for python_tool in sorted(path for path in REQUIRED_TOOLING if path.suffix == ".py"):
        try:
            compile(python_tool.read_text(encoding="utf-8"), str(python_tool), "exec")
        except SyntaxError as exc:
            fail(f"{python_tool.relative_to(ROOT)} has invalid Python syntax: {exc}")

    for name in sorted(REQUIRED_DOCS):
        path = AUDIT_DIR / name
        text = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_SECRET_PATTERNS:
            if pattern.search(text):
                fail(f"{name} appears to contain secret material")
        if path.suffix != ".md":
            continue
        for target in MARKDOWN_LINK.findall(text):
            if target.startswith(("http://", "https://", "#")):
                continue
            relative_target = target.split("#", 1)[0]
            if relative_target and not (path.parent / relative_target).is_file():
                fail(f"{name} has broken local link: {target}")

    for path in sorted(REQUIRED_TOOLING):
        text = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_SECRET_PATTERNS:
            if pattern.search(text):
                fail(f"{path.relative_to(ROOT)} appears to contain secret material")

    print(
        "V1 decommission inventory valid: "
        f"components={len(components)} unknown={len(unknown_ids)} "
        "destructive_change_allowed=false"
    )


if __name__ == "__main__":
    main()
