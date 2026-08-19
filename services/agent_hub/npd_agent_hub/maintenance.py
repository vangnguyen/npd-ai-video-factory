from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from redis import Redis

from .config import settings


BACKUP_VERSION = 1
SUPPORTED_TYPES = {"string", "list", "zset"}
RESTORE_CONFIRMATION = "RESTORE_AGENT_HUB"


class MaintenanceError(RuntimeError):
    pass


def _namespace(value: str) -> str:
    namespace = value.strip(":")
    if not namespace:
        raise MaintenanceError("Agent Hub namespace must not be empty")
    return namespace


def export_namespace(client: Redis, namespace: str) -> dict[str, Any]:
    namespace = _namespace(namespace)
    prefix = f"{namespace}:"
    items: list[dict[str, Any]] = []

    for raw_key in sorted(client.scan_iter(match=f"{prefix}*")):
        key = str(raw_key)
        key_type = str(client.type(key))
        if key_type not in SUPPORTED_TYPES:
            raise MaintenanceError(f"unsupported Redis type for backup: {key_type} ({key})")

        if key_type == "string":
            value: Any = client.get(key)
        elif key_type == "list":
            value = client.lrange(key, 0, -1)
        else:
            value = [
                {"member": str(member), "score": float(score)}
                for member, score in client.zrange(key, 0, -1, withscores=True)
            ]

        items.append({"key": key, "type": key_type, "value": value})

    return {
        "version": BACKUP_VERSION,
        "namespace": namespace,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "key_count": len(items),
        "items": items,
    }


def restore_namespace(
    client: Redis,
    payload: dict[str, Any],
    *,
    namespace: str,
    replace: bool = False,
) -> int:
    namespace = _namespace(namespace)
    if payload.get("version") != BACKUP_VERSION:
        raise MaintenanceError("unsupported Agent Hub backup version")
    if payload.get("namespace") != namespace:
        raise MaintenanceError("backup namespace does not match configured Agent Hub namespace")

    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise MaintenanceError("backup payload does not contain an item list")

    prefix = f"{namespace}:"
    normalized: list[dict[str, Any]] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            raise MaintenanceError("backup contains an invalid item")
        key = raw_item.get("key")
        key_type = raw_item.get("type")
        if not isinstance(key, str) or not key.startswith(prefix):
            raise MaintenanceError("backup contains a key outside the Agent Hub namespace")
        if key_type not in SUPPORTED_TYPES:
            raise MaintenanceError(f"backup contains unsupported Redis type: {key_type}")
        normalized.append(raw_item)

    existing = [str(key) for key in client.scan_iter(match=f"{prefix}*")]
    if existing and not replace:
        raise MaintenanceError("Agent Hub namespace is not empty; use --replace for an explicit restore")

    pipe = client.pipeline(transaction=True)
    if existing:
        pipe.delete(*existing)

    for item in normalized:
        key = str(item["key"])
        key_type = str(item["type"])
        value = item.get("value")
        if key_type == "string":
            if value is not None:
                pipe.set(key, str(value))
        elif key_type == "list":
            if not isinstance(value, list):
                raise MaintenanceError(f"invalid list payload for {key}")
            if value:
                pipe.rpush(key, *[str(entry) for entry in value])
        else:
            if not isinstance(value, list):
                raise MaintenanceError(f"invalid zset payload for {key}")
            mapping: dict[str, float] = {}
            for entry in value:
                if not isinstance(entry, dict) or "member" not in entry or "score" not in entry:
                    raise MaintenanceError(f"invalid zset entry for {key}")
                mapping[str(entry["member"])] = float(entry["score"])
            if mapping:
                pipe.zadd(key, mapping)

    pipe.execute()
    return len(normalized)


def _client() -> Redis:
    return Redis.from_url(settings.agent_redis_url, decode_responses=True)


def _write_payload(payload: dict[str, Any], output: str) -> None:
    raw = json.dumps(payload, ensure_ascii=False, indent=2)
    if output == "-":
        sys.stdout.write(raw + "\n")
        return
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def _read_payload(source: str) -> dict[str, Any]:
    raw = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise MaintenanceError("backup payload must be a JSON object")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Agent Hub Redis namespace maintenance")
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup = subparsers.add_parser("backup", help="Export only the configured Agent Hub namespace")
    backup.add_argument("--output", default="-", help="Output path or - for stdout")

    restore = subparsers.add_parser("restore", help="Restore only the configured Agent Hub namespace")
    restore.add_argument("--input", default="-", help="Input path or - for stdin")
    restore.add_argument("--replace", action="store_true", help="Replace existing Agent Hub namespace keys")
    restore.add_argument("--confirm", required=True, help=f"Must equal {RESTORE_CONFIRMATION}")

    args = parser.parse_args(argv)
    client = _client()
    try:
        if args.command == "backup":
            payload = export_namespace(client, settings.store_namespace)
            _write_payload(payload, args.output)
            return 0

        if args.confirm != RESTORE_CONFIRMATION:
            raise MaintenanceError("restore confirmation string is incorrect")
        payload = _read_payload(args.input)
        restored = restore_namespace(
            client,
            payload,
            namespace=settings.store_namespace,
            replace=bool(args.replace),
        )
        sys.stderr.write(f"restored {restored} Agent Hub keys\n")
        return 0
    except (MaintenanceError, json.JSONDecodeError, OSError, ValueError) as exc:
        sys.stderr.write(f"maintenance error: {exc}\n")
        return 2
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
