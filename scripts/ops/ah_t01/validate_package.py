#!/usr/bin/env python3
"""Static fail-closed validation for the AH-T01 deployment package."""

from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
OVERLAY = ROOT / "deploy" / "ah-t01" / "docker-compose.telemetry.yml"
DEPLOY = ROOT / "scripts" / "ops" / "ah_t01" / "deploy.sh"
PREFLIGHT = ROOT / "scripts" / "ops" / "ah_t01" / "preflight.sh"


def fail(message: str) -> None:
    raise SystemExit(f"AH-T01 package validation failed: {message}")


def target_array(source: str, name: str) -> set[str]:
    match = re.search(rf"^readonly {re.escape(name)}=\(([^)]*)\)$", source, re.MULTILINE)
    if match is None:
        fail(f"deployment is missing target declaration: {name}")
    return set(shlex.split(match.group(1)))


def main() -> int:
    overlay = OVERLAY.read_text(encoding="utf-8")
    deploy = DEPLOY.read_text(encoding="utf-8")
    preflight = PREFLIGHT.read_text(encoding="utf-8")
    required_overlay = {
        "api:",
        "renderer:",
        "LEGACY_TELEMETRY_SALT_FILE: /run/secrets/legacy_telemetry_salt",
        "AH_T01_TELEMETRY_SALT_HOST_FILE",
    }
    missing = sorted(token for token in required_overlay if token not in overlay)
    if missing:
        fail(f"overlay is missing required tokens: {missing}")
    for forbidden in ("ports:", "networks:", "redis:", "caddy", "command:", "REDIS_URL"):
        if forbidden.casefold() in overlay.casefold():
            fail(f"overlay contains forbidden topology token: {forbidden}")
    if "DEPLOY_AH_T01_TELEMETRY" not in deploy:
        fail("deployment lacks the literal production confirmation")
    expected_targets = {"api", "renderer"}
    forbidden_targets = {"worker", "agent-hub", "redis"}
    if target_array(deploy, "DEPLOY_TARGETS") != expected_targets:
        fail("deploy target must be exactly api + renderer")
    if target_array(deploy, "ROLLBACK_TARGETS") != expected_targets:
        fail("rollback target must be exactly api + renderer")
    if target_array(deploy, "FORBIDDEN_TARGETS") != forbidden_targets:
        fail("forbidden mutation targets must be worker + agent-hub + redis")
    if target_array(preflight, "DEPLOY_TARGETS") != expected_targets:
        fail("preflight target must be exactly api + renderer")
    if target_array(preflight, "IMMUTABLE_TARGETS") != forbidden_targets:
        fail("preflight immutable targets must be worker + agent-hub + redis")
    for forbidden in ("docker compose down", "docker volume rm", "iptables", "POST /api"):
        if forbidden.casefold() in deploy.casefold():
            fail(f"deployment contains forbidden action: {forbidden}")
    if re.search(r"(?im)^\s*(?:docker|systemctl|service|caddy)\b[^\n]*\bcaddy\b", deploy):
        fail("deployment contains a Caddy action")
    for required in (
        "--no-deps",
        '"${DEPLOY_TARGETS[@]}"',
        '"${ROLLBACK_TARGETS[@]}"',
        '"services_recreated": ["api", "renderer"]',
        "worker container identity changed",
        "Agent Hub container identity changed",
        "redis_container_before",
        "AGENT_REDIS_URL fingerprint changed",
        "V1 queue/processing state changed",
        "runtime baseline changed after preflight",
        "Caddy identity or configuration changed",
        "API/renderer/Caddy network membership changed",
        "API/renderer/Caddy port bindings changed",
        "verify_deployment.py",
        "production_business_write_performed",
    ):
        if required not in deploy:
            fail(f"deployment is missing safety invariant: {required}")
    for required in (
        "LLEN",
        "EXPECTED_COMMIT",
        "AH_T01_PREFLIGHT_SNAPSHOT",
        "AGENT_REDIS_URL",
        "CADDYFILE",
        "CADDY_CONTAINER",
    ):
        if required not in preflight:
            fail(f"preflight is missing safety invariant: {required}")
    print(
        "AH-T01A package valid: API/renderer-only deploy+rollback, immutable worker/Agent Hub/Redis"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
