#!/usr/bin/env python3
"""Static fail-closed checks for the inert AH-R01 deployment candidate."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
OVERLAY = ROOT / "deploy" / "ah-r01" / "docker-compose.redis-independent.yml"
CONNECTION = ROOT / "services" / "agent_hub" / "npd_agent_hub" / "redis_connection.py"
PREFLIGHT = ROOT / "scripts" / "ops" / "agent_hub_redis" / "ah_r01_preflight.sh"
PROVISION = ROOT / "scripts" / "ops" / "agent_hub_redis" / "ah_r01_provision.sh"
EXPORT = ROOT / "scripts" / "ops" / "agent_hub_redis" / "ah_r01_export_encrypted.sh"


def fail(message: str) -> None:
    raise SystemExit(f"AH-R01 candidate validation failed: {message}")


def service_names(compose: str) -> set[str]:
    in_services = False
    names: set[str] = set()
    for line in compose.splitlines():
        if line == "services:":
            in_services = True
            continue
        if in_services and line and not line.startswith(" "):
            break
        match = re.fullmatch(r"  ([a-z0-9-]+):", line)
        if in_services and match:
            names.add(match.group(1))
    return names


def main() -> int:
    overlay = OVERLAY.read_text(encoding="utf-8")
    connection = CONNECTION.read_text(encoding="utf-8")
    preflight = PREFLIGHT.read_text(encoding="utf-8")
    provision = PROVISION.read_text(encoding="utf-8")
    encrypted_export = EXPORT.read_text(encoding="utf-8")
    if service_names(overlay) != {"agent-hub", "agent-redis"}:
        fail("overlay may define only agent-hub and agent-redis")
    required = (
        "appendonly yes",
        "appendfsync everysec",
        "requirepass %s",
        "AGENT_REDIS_URL: redis://agent-redis:6379/0",
        "AGENT_REDIS_PASSWORD_FILE: /run/secrets/agent_redis_password",
        "internal: true",
        "agent-redis-data:/data",
        "AH_R01_REDIS_PASSWORD_HOST_FILE",
        "read_only: true",
        "setpriv --reuid redis --regid redis --clear-groups",
    )
    missing = [token for token in required if token not in overlay]
    if missing:
        fail(f"overlay is missing required controls: {missing}")
    agent_redis_block = overlay.split("  agent-redis:", 1)[1].split("\n  agent-hub:", 1)[0]
    for forbidden in ("ports:", "network_mode:", "redis://redis:6379/1", "host.docker.internal"):
        if forbidden in agent_redis_block:
            fail(f"agent-redis contains forbidden exposure/dependency token: {forbidden}")
    for forbidden_service in ("api", "worker", "renderer", "caddy"):
        if re.search(rf"^  {re.escape(forbidden_service)}:\s*$", overlay, re.MULTILINE):
            fail(f"overlay changes forbidden V1/proxy service: {forbidden_service}")
    if "REDIS_PASSWORD = re.compile" not in connection or "43,128" not in connection:
        fail("application password-file contract is not base64url fail-closed")
    if "password_file" not in connection or "must not embed a password" not in connection:
        fail("application does not separate password custody from the Redis URL")
    for required in (
        "AH_R01_EXPECTED_COMMIT",
        "AH_R01_EXPECTED_REDIS_IMAGE_ID",
        "AH_R01_MIN_FREE_BYTES",
        "redis://redis:6379/1",
        "target_absent=true",
    ):
        if required not in preflight:
            fail(f"M1 preflight is missing invariant: {required}")
    for required in (
        "PROVISION_AH_R01_REDIS",
        "up -d --no-deps --pull never agent-redis",
        "agent_hub_container_unchanged",
        "v1_redis_container_unchanged",
        '"cutover_performed": False',
        '"ah03_authorized": False',
    ):
        if required not in provision:
            fail(f"M1 provisioning runner is missing invariant: {required}")
    for forbidden in (" up -d agent-hub", " stop agent-hub", " down", "FLUSHDB", "FLUSHALL"):
        if forbidden.casefold() in provision.casefold():
            fail(f"M1 provisioning runner contains forbidden action: {forbidden.strip()}")
    for required in (
        "EXPORT_AH_R01_DB1_ENCRYPTED",
        "age --encrypt --recipients-file",
        "maintenance backup --output -",
        "redis_source_snapshot --require-exclusive-namespace",
        '"plaintext_written_to_disk": False',
        '"production_write_performed": False',
        '"restore_rehearsal_performed": False',
        '"cutover_performed": False',
    ):
        if required not in encrypted_export:
            fail(f"encrypted export runner is missing invariant: {required}")
    for forbidden in (" maintenance restore", "FLUSHDB", "FLUSHALL", " stop ", " down "):
        if forbidden.casefold() in encrypted_export.casefold():
            fail(f"encrypted export runner contains forbidden action: {forbidden.strip()}")
    print(
        "AH-R01 candidate valid: dedicated Redis, no host port, external password file, "
        "Agent Hub-only endpoint override"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
