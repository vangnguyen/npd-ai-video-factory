#!/usr/bin/env python3
"""Run the AH-01C Redis M0 proof against disposable loopback-only Redis 7 containers."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
SERVICE_ROOT = ROOT / "services" / "agent_hub"
sys.path.insert(0, str(SERVICE_ROOT))

from redis import Redis  # noqa: E402

from npd_agent_hub.maintenance import (  # noqa: E402
    MaintenanceError,
    export_namespace,
    restore_namespace,
    verify_namespace,
)


IMAGE = "redis:7-alpine"
LABEL = "npd.ah01c.synthetic"
NAMESPACE = "npd:agent-hub:v1"


class DrillError(RuntimeError):
    pass


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(args),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise DrillError(f"command failed: {args[0]} {args[1] if len(args) > 1 else ''}: {detail}")
    return result


def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run("docker", *args, check=check)


def port_for(container: str) -> int:
    output = docker("port", container, "6379/tcp").stdout.strip().splitlines()
    for line in output:
        host, separator, raw_port = line.rpartition(":")
        if separator and host in {"127.0.0.1", "0.0.0.0"}:
            if host != "127.0.0.1":
                raise DrillError("synthetic Redis port is not loopback-only")
            return int(raw_port)
    raise DrillError("could not resolve loopback Redis port")


def connect(container: str, *, timeout_seconds: float = 15.0) -> Redis:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            client = Redis(
                host="127.0.0.1",
                port=port_for(container),
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=2,
            )
            if client.ping():
                return client
        except Exception as exc:  # Redis startup races are expected here.
            last_error = exc
        time.sleep(0.25)
    raise DrillError(f"Redis container did not become ready: {type(last_error).__name__}")


def expect_maintenance_error(action: Any, *, contains: str) -> None:
    try:
        action()
    except MaintenanceError as exc:
        if contains not in str(exc):
            raise DrillError(f"unexpected fail-closed error: {exc}") from exc
        return
    raise DrillError(f"expected fail-closed error containing {contains!r}")


def image_identity() -> str:
    return docker("image", "inspect", IMAGE, "--format", "{{.Id}}").stdout.strip()


def git_revision() -> str:
    return run("git", "rev-parse", "HEAD").stdout.strip()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_created_container(container: str) -> bool:
    result = docker(
        "inspect",
        "--format",
        f"{{{{ index .Config.Labels \"{LABEL}\" }}}}",
        container,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def verify_created_volume(volume: str) -> bool:
    result = docker(
        "volume",
        "inspect",
        "--format",
        f"{{{{ index .Labels \"{LABEL}\" }}}}",
        volume,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def run_drill() -> dict[str, Any]:
    suffix = uuid.uuid4().hex[:10]
    source_name = f"npd-ah01c-source-{suffix}"
    target_name = f"npd-ah01c-target-{suffix}"
    target_volume = f"npd-ah01c-target-data-{suffix}"
    created_containers: list[str] = []
    source: Redis | None = None
    target: Redis | None = None
    report: dict[str, Any] | None = None

    try:
        docker("volume", "create", "--label", f"{LABEL}=true", target_volume)
        if not verify_created_volume(target_volume):
            raise DrillError("synthetic Redis volume does not carry the ownership label")
        docker(
            "run",
            "--detach",
            "--name",
            source_name,
            "--label",
            f"{LABEL}=true",
            "--publish",
            "127.0.0.1::6379",
            "--pull",
            "never",
            IMAGE,
            "redis-server",
            "--save",
            "",
            "--appendonly",
            "no",
        )
        created_containers.append(source_name)
        docker(
            "run",
            "--detach",
            "--name",
            target_name,
            "--label",
            f"{LABEL}=true",
            "--publish",
            "127.0.0.1::6379",
            "--mount",
            f"type=volume,source={target_volume},target=/data",
            "--pull",
            "never",
            IMAGE,
            "redis-server",
            "--appendonly",
            "yes",
            "--appendfsync",
            "always",
        )
        created_containers.append(target_name)

        source = connect(source_name)
        target = connect(target_name)
        if target.dbsize() != 0:
            raise DrillError("disposable target Redis is not empty")

        source.set(f"{NAMESPACE}:task:synthetic", '{"task_id":"synthetic"}')
        source.rpush(f"{NAMESPACE}:audit:synthetic", "created", "validated")
        source.zadd(f"{NAMESPACE}:tasks", {"synthetic": 123.5})
        source.set(f"{NAMESPACE}:provider-health:scheduler:lease", "synthetic-owner", px=120_000)
        source.set("outside:namespace", "must-not-migrate")

        payload = export_namespace(source, NAMESPACE)
        if payload["key_count"] != 4 or payload["type_counts"] != {
            "list": 1,
            "string": 2,
            "zset": 1,
        }:
            raise DrillError("synthetic export boundary is incorrect")
        if sum(item["pttl_ms"] >= 0 for item in payload["items"]) != 1:
            raise DrillError("synthetic export did not capture exactly one TTL key")

        source.hset(f"{NAMESPACE}:unsupported", mapping={"field": "value"})
        expect_maintenance_error(
            lambda: export_namespace(source, NAMESPACE),
            contains="unsupported Redis type",
        )
        source.delete(f"{NAMESPACE}:unsupported")

        target.set("outside:namespace", "preserve")
        first_restore_count = restore_namespace(target, payload, namespace=NAMESPACE)
        first_report = verify_namespace(target, payload, namespace=NAMESPACE)
        if target.get("outside:namespace") != "preserve":
            raise DrillError("restore changed a key outside the Agent Hub namespace")

        expect_maintenance_error(
            lambda: restore_namespace(target, payload, namespace=NAMESPACE),
            contains="not empty",
        )
        expect_maintenance_error(
            lambda: restore_namespace(target, payload, namespace="different:namespace", replace=True),
            contains="does not match",
        )

        corrupted = deepcopy(payload)
        string_item = next(item for item in corrupted["items"] if item["type"] == "string")
        string_item["value"] = "corrupted"
        expect_maintenance_error(
            lambda: restore_namespace(target, corrupted, namespace=NAMESPACE, replace=True),
            contains="checksum mismatch",
        )
        verify_namespace(target, payload, namespace=NAMESPACE)

        target.set(f"{NAMESPACE}:task:synthetic", "divergent")
        target.set(f"{NAMESPACE}:stale", "remove-on-rollback")
        rollback_restore_count = restore_namespace(target, payload, namespace=NAMESPACE, replace=True)
        rollback_report = verify_namespace(target, payload, namespace=NAMESPACE)
        if target.get(f"{NAMESPACE}:stale") is not None:
            raise DrillError("explicit replace rehearsal retained stale namespace data")

        target.close()
        target = None
        docker("restart", target_name)
        target = connect(target_name)
        restart_report = verify_namespace(target, payload, namespace=NAMESPACE)
        if target.get("outside:namespace") != "preserve":
            raise DrillError("restart lost the non-Agent-Hub control key")

        report = {
            "schema_version": "1.0",
            "scope": "synthetic_agent_hub_redis_m0",
            "status": "PASS",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_revision": git_revision(),
            "tested_sources": {
                "maintenance_py_sha256": file_sha256(
                    SERVICE_ROOT / "npd_agent_hub" / "maintenance.py"
                ),
                "drill_py_sha256": file_sha256(Path(__file__).resolve()),
            },
            "redis_image": IMAGE,
            "redis_image_id": image_identity(),
            "production_connection_performed": False,
            "production_write_performed": False,
            "synthetic_isolation": {
                "host_binding": "127.0.0.1 only",
                "remote_exposure": False,
                "ephemeral_source_container": True,
                "ephemeral_target_container": True,
                "ephemeral_target_volume": True,
                "cleanup_required": True,
            },
            "export": {
                "backup_version": payload["version"],
                "namespace": payload["namespace"],
                "key_count": payload["key_count"],
                "type_counts": payload["type_counts"],
                "ttl_key_count": 1,
                "source_consistency": payload["source_consistency"],
                "namespace_sha256": payload["namespace_sha256"],
                "content_sha256": payload["content_sha256"],
                "values_logged": False,
            },
            "checks": {
                "namespace_only_export": "PASS",
                "unsupported_type_fail_closed": "PASS",
                "non_empty_target_fail_closed": "PASS",
                "namespace_mismatch_fail_closed": "PASS",
                "checksum_corruption_fail_closed_before_write": "PASS",
                "first_restore_count": first_restore_count,
                "first_restore_parity": first_report["status"],
                "ttl_semantics": "PASS",
                "outside_namespace_preserved": "PASS",
                "explicit_replace_rollback_count": rollback_restore_count,
                "explicit_replace_rollback_parity": rollback_report["status"],
                "target_restart_persistence": restart_report["status"],
            },
            "gate": {
                "m0_offline_tooling": "PASS",
                "production_db1_export_restore": "NOT_RUN",
                "production_migration_authorized": False,
                "v1_shutdown_authorized": False,
            },
        }
    finally:
        if source is not None:
            source.close()
        if target is not None:
            target.close()
        for container in reversed(created_containers):
            if verify_created_container(container):
                docker("rm", "--force", container, check=False)
        if verify_created_volume(target_volume):
            docker("volume", "rm", target_volume, check=False)

        if report is not None:
            leftover_containers = sum(
                verify_created_container(container) for container in created_containers
            )
            leftover_volumes = int(verify_created_volume(target_volume))
            report["synthetic_isolation"]["leftover_containers"] = leftover_containers
            report["synthetic_isolation"]["leftover_volumes"] = leftover_volumes
            if leftover_containers or leftover_volumes:
                raise DrillError("synthetic Redis cleanup did not remove every owned resource")

    if report is None:
        raise DrillError("synthetic Redis drill did not produce a report")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        report = run_drill()
    except (DrillError, MaintenanceError, OSError, ValueError) as exc:
        sys.stderr.write(f"AH-01C Redis M0 drill failed: {exc}\n")
        return 2
    sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
