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


def main() -> None:
    missing_docs = sorted(name for name in REQUIRED_DOCS if not (AUDIT_DIR / name).is_file())
    if missing_docs:
        fail(f"missing deliverables: {', '.join(missing_docs)}")

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

    print(
        "V1 decommission inventory valid: "
        f"components={len(components)} unknown={len(unknown_ids)} "
        "destructive_change_allowed=false"
    )


if __name__ == "__main__":
    main()
