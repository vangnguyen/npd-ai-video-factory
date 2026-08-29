#!/usr/bin/env python3
"""Exercise AH-R01 against disposable, uniquely owned Docker resources only."""

from __future__ import annotations

import json
import os
import secrets
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "deploy" / "phase5" / "docker-compose.agent-hub.prod.yml"
OVERLAY = ROOT / "deploy" / "ah-r01" / "docker-compose.redis-independent.yml"
LABEL = "npd.ah-r01.synthetic"


class DrillError(RuntimeError):
    pass


def run(
    *args: str,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(args),
        cwd=ROOT,
        env=env,
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise DrillError(f"command failed: {args[0]} {args[1] if len(args) > 1 else ''}: {detail}")
    return result


def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run("docker", *args, check=check)


def label_value(kind: str, name: str) -> str:
    result = docker(
        kind,
        "inspect",
        "--format",
        f'{{{{ index .Labels "{LABEL}" }}}}',
        name,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def wait_for_health(
    container_id: str,
    *,
    secret: str,
    timeout_seconds: float = 40.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        status = docker(
            "inspect", "--format", "{{.State.Health.Status}}", container_id, check=False
        ).stdout.strip()
        if status == "healthy":
            return
        if status == "unhealthy":
            state = docker(
                "inspect",
                "--format",
                "status={{.State.Status}} exit={{.State.ExitCode}} error={{.State.Error}}",
                container_id,
                check=False,
            ).stdout.strip()
            logs = docker("logs", "--tail", "30", container_id, check=False)
            detail = (state + " " + logs.stdout + " " + logs.stderr).replace(secret, "[redacted]")
            raise DrillError(f"disposable Redis became unhealthy: {detail.strip()}")
        time.sleep(0.5)
    raise DrillError("disposable Redis health timeout")


def run_drill() -> dict[str, Any]:
    suffix = uuid.uuid4().hex[:10]
    project = f"npd-ah-r01-{suffix}"
    redis_network = f"npd-ah-r01-data-{suffix}"
    redis_volume = f"npd-ah-r01-data-{suffix}"
    v1_network = f"npd-ah-r01-v1-{suffix}"
    n8n_network = f"npd-ah-r01-n8n-{suffix}"
    image = f"npd-agent-hub:ah-r01-synthetic-{suffix}"
    password = secrets.token_urlsafe(48).rstrip("=")
    created_external_networks: list[str] = []
    image_created = False
    compose_started = False
    report: dict[str, Any] | None = None

    with tempfile.TemporaryDirectory(prefix="npd-ah-r01-") as temp_value:
        temp = Path(temp_value)
        password_file = temp / "agent-redis-password"
        env_file = temp / "agent-hub.env"
        password_file.write_text(password + "\n", encoding="utf-8")
        env_file.write_text("# synthetic AH-R01 drill\n", encoding="utf-8")
        if os.name != "nt":
            password_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
            env_file.chmod(stat.S_IRUSR | stat.S_IWUSR)

        env = os.environ.copy()
        env.update(
            {
                "AH_R01_REDIS_PASSWORD_HOST_FILE": str(password_file.resolve()),
                "AH_R01_REDIS_NETWORK_NAME": redis_network,
                "AH_R01_REDIS_VOLUME_NAME": redis_volume,
                "NPD_DOCKER_NETWORK": v1_network,
                "N8N_DOCKER_NETWORK": n8n_network,
                "AGENT_HUB_ENV_FILE": str(env_file.resolve()),
                "AGENT_HUB_IMAGE": image,
            }
        )
        compose_prefix = (
            "docker",
            "compose",
            "--project-name",
            project,
            "-f",
            str(BASE),
            "-f",
            str(OVERLAY),
        )

        def compose(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
            return run(*compose_prefix, *args, env=env, check=check)

        try:
            for network in (v1_network, n8n_network):
                docker("network", "create", "--label", f"{LABEL}=true", network)
                created_external_networks.append(network)

            configured = json.loads(compose("config", "--format", "json").stdout)
            redis_service = configured["services"]["agent-redis"]
            if redis_service.get("ports"):
                raise DrillError("candidate config publishes an agent-redis host port")
            if configured["networks"]["agent-data"].get("internal") is not True:
                raise DrillError("candidate data network is not internal")
            rendered_config = json.dumps(configured, sort_keys=True)
            if password in rendered_config:
                raise DrillError("synthetic password leaked into rendered Compose config")

            run(
                "docker",
                "build",
                "--tag",
                image,
                "--file",
                str(ROOT / "services" / "agent_hub" / "Dockerfile"),
                str(ROOT),
            )
            image_created = True
            compose_started = True
            compose("up", "-d", "--no-deps", "agent-redis")
            container_id = compose("ps", "-q", "agent-redis").stdout.strip()
            if not container_id:
                raise DrillError("candidate Redis container was not created")
            wait_for_health(container_id, secret=password)

            inspected = json.loads(docker("inspect", container_id).stdout)[0]
            if inspected["HostConfig"].get("PortBindings"):
                raise DrillError("running candidate Redis has a host port binding")
            if set(inspected["NetworkSettings"]["Networks"]) != {redis_network}:
                raise DrillError("candidate Redis joined a network outside its dedicated data network")
            if password in json.dumps(inspected, sort_keys=True):
                raise DrillError("synthetic password leaked into container inspection metadata")
            process_uid = docker(
                "exec",
                container_id,
                "sh",
                "-c",
                "sed -n 's/^Uid:[[:space:]]*\\([0-9]*\\).*/\\1/p' /proc/1/status",
            ).stdout.strip()
            if process_uid != "999":
                raise DrillError("candidate Redis does not run as the redis user")

            unauthenticated = docker(
                "exec", container_id, "redis-cli", "ping", check=False
            )
            unauthenticated_output = unauthenticated.stdout + unauthenticated.stderr
            if "NOAUTH" not in unauthenticated_output:
                raise DrillError("candidate Redis accepted an unauthenticated command")
            authenticated = docker(
                "exec",
                "--env",
                f"REDISCLI_AUTH={password}",
                container_id,
                "redis-cli",
                "--no-auth-warning",
                "ping",
            ).stdout.strip()
            if authenticated != "PONG":
                raise DrillError("candidate Redis authentication failed")

            probe = (
                "from npd_agent_hub.config import HubSettings; "
                "from npd_agent_hub.store import build_store; "
                "s=build_store(HubSettings.from_env()); "
                "assert s.health(); "
                "s.redis.set('npd:agent-hub:v1:ah-r01-synthetic','persist'); "
                "assert s.redis.get('npd:agent-hub:v1:ah-r01-synthetic') == 'persist'"
            )
            compose("run", "--rm", "--no-deps", "agent-hub", "python", "-c", probe)
            read_model = json.loads(
                compose(
                    "run",
                    "--rm",
                    "--no-deps",
                    "agent-hub",
                    "python",
                    "-m",
                    "npd_agent_hub.redis_read_model_probe",
                ).stdout
            )
            if read_model.get("status") != "PASS" or read_model.get("write_performed") is not False:
                raise DrillError("Agent Hub read-model probe did not pass safely")
            time.sleep(2)
            compose("restart", "agent-redis")
            container_id = compose("ps", "-q", "agent-redis").stdout.strip()
            wait_for_health(container_id, secret=password)
            persisted = docker(
                "exec",
                "--env",
                f"REDISCLI_AUTH={password}",
                container_id,
                "redis-cli",
                "--no-auth-warning",
                "get",
                "npd:agent-hub:v1:ah-r01-synthetic",
            ).stdout.strip()
            if persisted != "persist":
                raise DrillError("candidate AOF data did not survive Redis restart")
            persistence = docker(
                "exec",
                "--env",
                f"REDISCLI_AUTH={password}",
                container_id,
                "redis-cli",
                "--no-auth-warning",
                "info",
                "persistence",
            ).stdout
            if "aof_enabled:1" not in persistence or "aof_last_write_status:ok" not in persistence:
                raise DrillError("candidate Redis AOF status is not healthy")

            report = {
                "schema_version": "1.0",
                "scope": "ah_r01_offline_independence_candidate",
                "status": "PASS",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "source_revision": run("git", "rev-parse", "HEAD").stdout.strip(),
                "production_connection_performed": False,
                "production_write_performed": False,
                "secrets_logged": False,
                "checks": {
                    "compose_config": "PASS",
                    "no_host_published_port": "PASS",
                    "internal_dedicated_network_only": "PASS",
                    "external_password_file": "PASS",
                    "unauthenticated_command_rejected": "PASS",
                    "agent_hub_password_file_connection": "PASS",
                    "agent_hub_read_models": "PASS",
                    "redis_non_root_uid": 999,
                    "aof_restart_persistence": "PASS",
                },
                "gate": {
                    "m1_provisioning_authorized": False,
                    "production_export_authorized": False,
                    "cutover_authorized": False,
                    "v1_shutdown_authorized": False,
                },
            }
        finally:
            if compose_started:
                project_containers = docker(
                    "ps",
                    "--all",
                    "--filter",
                    f"label=com.docker.compose.project={project}",
                    "--format",
                    "{{.ID}}",
                    check=False,
                ).stdout.split()
                for container_id in project_containers:
                    if label_value("container", container_id) != "true" and docker(
                        "inspect",
                        "--format",
                        '{{ index .Config.Labels "npd.change" }}',
                        container_id,
                        check=False,
                    ).stdout.strip() != "ah-r01":
                        raise DrillError("refusing cleanup of a container without AH-R01 ownership")
                volume_exists = docker(
                    "volume", "inspect", redis_volume, check=False
                ).returncode == 0
                if volume_exists and label_value("volume", redis_volume) != "ah-r01":
                    redis_volume_label = docker(
                        "volume",
                        "inspect",
                        "--format",
                        '{{ index .Labels "npd.change" }}',
                        redis_volume,
                        check=False,
                    ).stdout.strip()
                    if redis_volume_label != "ah-r01":
                        raise DrillError("refusing cleanup of a volume without AH-R01 ownership")
                compose("down", "--volumes", "--remove-orphans", check=False)
            for network in reversed(created_external_networks):
                if label_value("network", network) == "true":
                    docker("network", "rm", network, check=False)
            if image_created and image.startswith("npd-agent-hub:ah-r01-synthetic-"):
                docker("image", "rm", "--force", image, check=False)

            leftovers = docker(
                "ps",
                "--all",
                "--filter",
                f"label=com.docker.compose.project={project}",
                "--format",
                "{{.ID}}",
                check=False,
            ).stdout.split()
            if leftovers:
                raise DrillError("synthetic AH-R01 container cleanup was incomplete")
            for kind, name in (("volume", redis_volume), ("network", redis_network)):
                if docker(kind, "inspect", name, check=False).returncode == 0:
                    raise DrillError(f"synthetic AH-R01 {kind} cleanup was incomplete")
            if report is not None:
                report["cleanup"] = {
                    "owned_containers_left": 0,
                    "production_resources_touched": False,
                }

    if report is None:
        raise DrillError("AH-R01 candidate drill did not produce a report")
    return report


def main() -> int:
    try:
        report = run_drill()
    except (DrillError, OSError, ValueError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"AH-R01 offline candidate drill failed: {exc}\n")
        return 2
    sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
