#!/usr/bin/env python3
"""Validate a V1 DB0 export and optionally restore it to a guarded local Redis."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "1.0"
RESTORE_CONFIRMATION = "RESTORE_ISOLATED_V1_DB0"
RESTORE_LABEL = "npd.ah01b.restore-test"
ALLOWED_KEY = re.compile(
    r"^(?:npd:video-job:.+|npd:video-idempotency:.+|"
    r"npd:video-jobs:(?:queue|processing))$"
)
EXPECTED_TYPES = {
    "npd:video-jobs:queue": "list",
    "npd:video-jobs:processing": "list",
}


class VerificationError(RuntimeError):
    pass


def _run(
    command: list[str], *, input_bytes: bytes | None = None, text: bool = False
) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(
        command,
        input=input_bytes,
        capture_output=True,
        check=False,
        text=text,
    )


def _decode_base64(value: object, *, field: str) -> bytes:
    if not isinstance(value, str):
        raise VerificationError(f"{field} must be a base64 string")
    try:
        return base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise VerificationError(f"{field} is not valid base64") from exc


def load_and_validate(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        raw = sys.stdin.read() if str(path) == "-" else path.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise VerificationError(f"cannot read export: {exc}") from exc
    if not isinstance(payload, dict):
        raise VerificationError("export must be a JSON object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise VerificationError("unsupported export schema_version")
    if payload.get("database") != 0:
        raise VerificationError("export must contain only Redis DB0")
    items = payload.get("items")
    if not isinstance(items, list):
        raise VerificationError("export items must be a list")
    if payload.get("key_count") != len(items):
        raise VerificationError("export key_count is stale")

    normalized: list[dict[str, Any]] = []
    keys: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise VerificationError(f"item {index} is not an object")
        key_bytes = _decode_base64(item.get("key_base64"), field=f"item {index} key")
        try:
            key = key_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise VerificationError(f"item {index} key is not UTF-8") from exc
        if not ALLOWED_KEY.fullmatch(key):
            raise VerificationError(f"item {index} has a key outside the V1 DB0 boundary")
        if key in keys:
            raise VerificationError(f"duplicate key at item {index}")
        keys.add(key)

        key_type = item.get("type")
        expected_type = EXPECTED_TYPES.get(key, "string")
        if key_type != expected_type:
            raise VerificationError(
                f"item {index} type mismatch: expected {expected_type}, got {key_type!r}"
            )
        pttl_ms = item.get("pttl_ms")
        if not isinstance(pttl_ms, int) or pttl_ms < -1:
            raise VerificationError(f"item {index} has invalid pttl_ms")
        dump = _decode_base64(item.get("dump_base64"), field=f"item {index} dump")
        if not dump:
            raise VerificationError(f"item {index} has an empty serialized dump")
        digest = hashlib.sha256(dump).hexdigest()
        if item.get("dump_sha256") != digest:
            raise VerificationError(f"item {index} dump checksum mismatch")
        normalized.append(
            {
                "key": key,
                "type": key_type,
                "pttl_ms": pttl_ms,
                "dump": dump,
                "dump_sha256": digest,
            }
        )

    queue_items = next(
        (item for item in normalized if item["key"] == "npd:video-jobs:queue"), None
    )
    processing_items = next(
        (
            item
            for item in normalized
            if item["key"] == "npd:video-jobs:processing"
        ),
        None,
    )
    for field, item in (
        ("queue_length", queue_items),
        ("processing_length", processing_items),
    ):
        value = payload.get(field)
        if not isinstance(value, int) or value < 0:
            raise VerificationError(f"{field} must be a non-negative integer")
        if item is None and value != 0:
            raise VerificationError(f"{field} is nonzero but its Redis key is absent")

    return payload, normalized


def _docker_inspect(container: str) -> dict[str, Any]:
    result = _run(["docker", "inspect", container])
    if result.returncode != 0:
        raise VerificationError("cannot inspect the restore container")
    try:
        rows = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise VerificationError("docker inspect returned invalid JSON") from exc
    if not isinstance(rows, list) or len(rows) != 1:
        raise VerificationError("restore container identity is ambiguous")
    return rows[0]


def _redis_text(container: str, *args: str) -> str:
    result = _run(["docker", "exec", container, "redis-cli", "-n", "0", "--raw", *args])
    if result.returncode != 0:
        raise VerificationError("isolated Redis command failed")
    return result.stdout.decode("utf-8", errors="strict").strip()


def _validate_guarded_container(container: str) -> None:
    inspect = _docker_inspect(container)
    if not inspect.get("State", {}).get("Running"):
        raise VerificationError("restore container is not running")
    labels = inspect.get("Config", {}).get("Labels") or {}
    if labels.get(RESTORE_LABEL) != "true":
        raise VerificationError(f"restore container must have label {RESTORE_LABEL}=true")
    host_config = inspect.get("HostConfig") or {}
    if host_config.get("NetworkMode") != "none":
        raise VerificationError("restore container must use --network none")
    if host_config.get("PortBindings"):
        raise VerificationError("restore container must not publish ports")

    info = _redis_text(container, "INFO", "server")
    version_match = re.search(r"^redis_version:(\d+)\.", info, flags=re.MULTILINE)
    if not version_match or version_match.group(1) != "7":
        raise VerificationError("isolated restore requires Redis major version 7")


def _verify_existing(
    payload: dict[str, Any], items: list[dict[str, Any]], *, container: str
) -> dict[str, Any]:
    if int(_redis_text(container, "DBSIZE")) != len(items):
        raise VerificationError("isolated Redis key count mismatch")

    for item in items:
        if _redis_text(container, "TYPE", item["key"]) != item["type"]:
            raise VerificationError("isolated Redis type mismatch")
        dump_result = _run(
            [
                "docker",
                "exec",
                container,
                "redis-cli",
                "-n",
                "0",
                "-D",
                "",
                "--raw",
                "DUMP",
                item["key"],
            ]
        )
        if dump_result.returncode != 0:
            raise VerificationError("isolated Redis DUMP verification failed")
        if hashlib.sha256(dump_result.stdout).hexdigest() != item["dump_sha256"]:
            raise VerificationError("isolated Redis serialized checksum mismatch")
        restored_pttl = int(_redis_text(container, "PTTL", item["key"]))
        if item["pttl_ms"] == -1 and restored_pttl != -1:
            raise VerificationError("restored non-expiring key gained a TTL")
        if item["pttl_ms"] >= 0 and restored_pttl < 0:
            raise VerificationError("restored expiring key lost its TTL")

    queue_length = int(_redis_text(container, "LLEN", "npd:video-jobs:queue"))
    processing_length = int(
        _redis_text(container, "LLEN", "npd:video-jobs:processing")
    )
    if queue_length != payload["queue_length"]:
        raise VerificationError("restored queue length mismatch")
    if processing_length != payload["processing_length"]:
        raise VerificationError("restored processing length mismatch")

    return {
        "schema_version": "1.0",
        "scope": "isolated_v1_redis_db0",
        "status": "PASS",
        "source_key_count": payload["key_count"],
        "verified_key_count": len(items),
        "queue_length": queue_length,
        "processing_length": processing_length,
        "container": container,
        "complete_v1_bundle_restore": False,
    }


def restore_and_verify(
    payload: dict[str, Any], items: list[dict[str, Any]], *, container: str
) -> dict[str, Any]:
    _validate_guarded_container(container)
    if _redis_text(container, "DBSIZE") != "0":
        raise VerificationError("isolated Redis DB0 must be empty before restore")

    for item in items:
        ttl = 0 if item["pttl_ms"] == -1 else item["pttl_ms"]
        result = _run(
            [
                "docker",
                "exec",
                "-i",
                container,
                "redis-cli",
                "-n",
                "0",
                "-x",
                "RESTORE",
                item["key"],
                str(ttl),
            ],
            input_bytes=item["dump"],
        )
        if result.returncode != 0 or result.stdout.strip() != b"OK":
            raise VerificationError("isolated Redis RESTORE failed")

    report = _verify_existing(payload, items, container=container)
    report["restore_performed"] = True
    return report


def verify_isolated_existing(
    payload: dict[str, Any],
    items: list[dict[str, Any]],
    *,
    container: str,
    phase: str,
) -> dict[str, Any]:
    _validate_guarded_container(container)
    report = _verify_existing(payload, items, container=container)
    report["restore_performed"] = False
    report["verification_phase_claimed_by_operator"] = phase
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="Validate export structure/checksums")
    validate.add_argument("export", type=Path)
    restore = subparsers.add_parser(
        "restore-isolated", help="Restore to an explicitly disposable local Redis"
    )
    restore.add_argument("export", type=Path)
    restore.add_argument("--container", required=True)
    restore.add_argument("--confirm", required=True)
    existing = subparsers.add_parser(
        "verify-isolated-existing",
        help="Verify an already-restored guarded Redis without writing to it",
    )
    existing.add_argument("export", type=Path)
    existing.add_argument("--container", required=True)
    existing.add_argument(
        "--phase", choices=("post-restore", "post-restart"), required=True
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload, items = load_and_validate(args.export)
        if args.command == "validate":
            print(
                json.dumps(
                    {
                        "status": "VALID",
                        "scope": "v1_redis_db0_export",
                        "key_count": len(items),
                        "restore_performed": False,
                    },
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "restore-isolated":
            if args.confirm != RESTORE_CONFIRMATION:
                raise VerificationError("restore confirmation string is incorrect")
            report = restore_and_verify(payload, items, container=args.container)
        else:
            report = verify_isolated_existing(
                payload, items, container=args.container, phase=args.phase
            )
        print(json.dumps(report, sort_keys=True))
        return 0
    except VerificationError as exc:
        print(f"verification failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
