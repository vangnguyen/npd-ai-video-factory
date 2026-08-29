from __future__ import annotations

import re
import shlex
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DEPLOY = (ROOT / "scripts" / "ops" / "ah_t01" / "deploy.sh").read_text(encoding="utf-8")
PREFLIGHT = (ROOT / "scripts" / "ops" / "ah_t01" / "preflight.sh").read_text(
    encoding="utf-8"
)


def shell_array(source: str, name: str) -> set[str]:
    match = re.search(rf"^readonly {re.escape(name)}=\(([^)]*)\)$", source, re.MULTILINE)
    assert match is not None, f"missing shell target declaration: {name}"
    return set(shlex.split(match.group(1)))


def mutating_compose_lines(source: str) -> list[str]:
    normalized = source.replace("\\\n", " ")
    return [
        line.strip()
        for line in normalized.splitlines()
        if "docker compose" in line and (" build " in line or "--force-recreate" in line)
    ]


def test_deploy_and_rollback_targets_are_exactly_api_and_renderer() -> None:
    expected = {"api", "renderer"}
    assert shell_array(DEPLOY, "DEPLOY_TARGETS") == expected
    assert shell_array(DEPLOY, "ROLLBACK_TARGETS") == expected
    assert shell_array(PREFLIGHT, "DEPLOY_TARGETS") == expected
    assert '"services_recreated": ["api", "renderer"]' in DEPLOY
    assert '"rollback_targets": ["api", "renderer"]' in DEPLOY


def test_worker_agent_hub_and_redis_are_forbidden_mutation_targets() -> None:
    forbidden = {"worker", "agent-hub", "redis"}
    assert shell_array(DEPLOY, "FORBIDDEN_TARGETS") == forbidden
    assert shell_array(PREFLIGHT, "IMMUTABLE_TARGETS") == forbidden
    lines = mutating_compose_lines(DEPLOY)
    assert lines
    for line in lines:
        assert not forbidden.intersection(shlex.split(line.replace('"', "")))
        assert "${DEPLOY_TARGETS[@]}" in line or "${ROLLBACK_TARGETS[@]}" in line


def test_immutable_runtime_evidence_is_fail_closed() -> None:
    for token in (
        "worker container identity changed",
        "worker image identity changed",
        "Agent Hub container identity changed",
        "Agent Hub image identity changed",
        "V1 Redis container identity changed",
        "V1 queue/processing state changed",
        "runtime baseline changed after preflight",
        "AGENT_REDIS_URL fingerprint changed",
        "Caddy identity or configuration changed",
        "an immutable service or Caddy is not running",
        "API/renderer/Caddy network membership changed",
        "API/renderer/Caddy port bindings changed",
    ):
        assert token in DEPLOY
    for forbidden_action in (
        "docker compose down",
        "docker volume rm",
        "iptables",
        "docker network connect",
        "docker network disconnect",
    ):
        assert forbidden_action not in DEPLOY.casefold()


def test_deploy_and_rollback_both_use_bounded_readiness_verification() -> None:
    assert DEPLOY.count("wait_for_api_renderer_ready") == 3
    assert "for attempt in $(seq 1 30)" in DEPLOY
    assert "AH-T01 deploy error: API/renderer readiness timed out" in DEPLOY

    rollback = re.search(
        r"rollback_on_failure\(\) \{(?P<body>.*?)\n\}\ntrap rollback_on_failure EXIT",
        DEPLOY,
        re.DOTALL,
    )
    assert rollback is not None
    rollback_body = rollback.group("body")
    assert "wait_for_api_renderer_ready" in rollback_body
    assert "rollback_images_restored" in rollback_body
    assert "rollback health/readiness verification failed after bounded wait" in rollback_body
    assert "rollback image identity verification failed" in rollback_body
    for forbidden in ("worker", "agent-hub", "redis"):
        assert forbidden not in shlex.split(rollback_body.replace('"', ""))
