#!/usr/bin/env python3
"""Static fail-closed validation for the AH-T01 deployment package."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
OVERLAY = ROOT / "deploy" / "ah-t01" / "docker-compose.telemetry.yml"
DEPLOY = ROOT / "scripts" / "ops" / "ah_t01" / "deploy.sh"
PREFLIGHT = ROOT / "scripts" / "ops" / "ah_t01" / "preflight.sh"


def fail(message: str) -> None:
    raise SystemExit(f"AH-T01 package validation failed: {message}")


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
    for forbidden in ("docker compose down", "docker volume rm", "caddy", "iptables", "POST /api"):
        if forbidden.casefold() in deploy.casefold():
            fail(f"deployment contains forbidden action: {forbidden}")
    for required in (
        "--no-deps",
        "api worker renderer",
        "agent-hub",
        "redis_container_before",
        "verify_deployment.py",
        "production_business_write_performed",
    ):
        if required not in deploy:
            fail(f"deployment is missing safety invariant: {required}")
    if "LLEN" not in preflight or "EXPECTED_COMMIT" not in preflight:
        fail("preflight does not prove an idle V1 queue and exact commit")
    print("AH-T01 package valid: telemetry-only overlay, explicit gate, Redis/Caddy/write guards")
    return 0


if __name__ == "__main__":
    sys.exit(main())
