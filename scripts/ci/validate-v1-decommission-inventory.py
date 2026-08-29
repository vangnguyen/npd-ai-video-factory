#!/usr/bin/env python3
"""Validate the AH-01 machine-readable inventory and its safety gates."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AUDIT_DIR = ROOT / "docs" / "video-factory-v1-decommission"
INVENTORY = AUDIT_DIR / "v1-components.json"
STORAGE_MANIFEST = AUDIT_DIR / "v1-storage-ownership-manifest.json"
PROVENANCE_MANIFEST = AUDIT_DIR / "v1-runtime-image-provenance.json"
REQUIRED_TOOLING = {
    ROOT / "scripts" / "ops" / "v1_backup" / "README.md",
    ROOT / "scripts" / "ops" / "v1_backup" / "export-db0-readonly.sh",
    ROOT / "scripts" / "ops" / "v1_backup" / "verify_redis_export.py",
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
    if summary.get("portable_rollback_bundle_verified") is not False:
        fail("portable rollback must remain unverified until a real restore drill passes")


def main() -> None:
    missing_docs = sorted(name for name in REQUIRED_DOCS if not (AUDIT_DIR / name).is_file())
    if missing_docs:
        fail(f"missing deliverables: {', '.join(missing_docs)}")
    missing_tooling = sorted(str(path.relative_to(ROOT)) for path in REQUIRED_TOOLING if not path.is_file())
    if missing_tooling:
        fail(f"missing AH-01B tooling: {', '.join(missing_tooling)}")

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
    if unknown_ids and summary.get("destructive_change_allowed") is not False:
        fail("destructive_change_allowed must be false while UNKNOWN remains")

    validate_storage_manifest()
    validate_provenance_manifest()

    verifier = ROOT / "scripts" / "ops" / "v1_backup" / "verify_redis_export.py"
    try:
        compile(verifier.read_text(encoding="utf-8"), str(verifier), "exec")
    except SyntaxError as exc:
        fail(f"backup verifier has invalid Python syntax: {exc}")

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
