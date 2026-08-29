from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from redis import Redis

from .config import settings


BACKUP_VERSION = 2
LEGACY_BACKUP_VERSION = 1
SUPPORTED_BACKUP_VERSIONS = {LEGACY_BACKUP_VERSION, BACKUP_VERSION}
SUPPORTED_TYPES = {"string", "list", "zset"}
RESTORE_CONFIRMATION = "RESTORE_AGENT_HUB"
TTL_TOLERANCE_MS = 2_000


class MaintenanceError(RuntimeError):
    pass


def _namespace(value: str) -> str:
    namespace = value.strip(":")
    if not namespace:
        raise MaintenanceError("Agent Hub namespace must not be empty")
    return namespace


def _now_epoch_ms() -> int:
    return time.time_ns() // 1_000_000


def _utc_iso(epoch_ms: int) -> str:
    return datetime.fromtimestamp(epoch_ms / 1_000, tz=timezone.utc).isoformat()


def _text(value: Any, *, context: str) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MaintenanceError(f"{context} is not UTF-8") from exc
    raise MaintenanceError(f"{context} is not text")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _normalize_value(key_type: str, value: Any, *, key: str, strict: bool) -> Any:
    if key_type == "string":
        if strict and not isinstance(value, str):
            raise MaintenanceError(f"invalid string payload for {key}")
        return _text(value, context=f"value for {key}")

    if key_type == "list":
        if not isinstance(value, list) or (strict and not all(isinstance(item, str) for item in value)):
            raise MaintenanceError(f"invalid list payload for {key}")
        return [_text(item, context=f"list member for {key}") for item in value]

    if not isinstance(value, list):
        raise MaintenanceError(f"invalid zset payload for {key}")
    normalized: list[dict[str, Any]] = []
    members: set[str] = set()
    for entry in value:
        if not isinstance(entry, dict) or set(entry) != {"member", "score"}:
            raise MaintenanceError(f"invalid zset entry for {key}")
        if strict and not isinstance(entry["member"], str):
            raise MaintenanceError(f"invalid zset member for {key}")
        member = _text(entry["member"], context=f"zset member for {key}")
        if member in members:
            raise MaintenanceError(f"duplicate zset member for {key}")
        members.add(member)
        if isinstance(entry["score"], bool) or not isinstance(entry["score"], (int, float)):
            raise MaintenanceError(f"invalid zset score for {key}")
        score = float(entry["score"])
        if not math.isfinite(score):
            raise MaintenanceError(f"non-finite zset score for {key}")
        normalized.append({"member": member, "score": score})
    return normalized


def _read_item(client: Redis, key: str) -> dict[str, Any]:
    key_type = _text(client.type(key), context=f"type for {key}")
    if key_type == "none":
        raise MaintenanceError(f"key disappeared during export: {key}")
    if key_type not in SUPPORTED_TYPES:
        raise MaintenanceError(f"unsupported Redis type for backup: {key_type} ({key})")

    if key_type == "string":
        raw_value: Any = client.get(key)
        if raw_value is None:
            raise MaintenanceError(f"key disappeared during export: {key}")
        value = _text(raw_value, context=f"value for {key}")
    elif key_type == "list":
        value = [
            _text(member, context=f"list member for {key}")
            for member in client.lrange(key, 0, -1)
        ]
    else:
        value = [
            {
                "member": _text(member, context=f"zset member for {key}"),
                "score": float(score),
            }
            for member, score in client.zrange(key, 0, -1, withscores=True)
        ]

    pttl_ms = int(client.pttl(key))
    if pttl_ms == -2:
        raise MaintenanceError(f"key disappeared during export: {key}")
    if pttl_ms < -1:
        raise MaintenanceError(f"invalid Redis PTTL for {key}: {pttl_ms}")
    expires_at_epoch_ms = None if pttl_ms == -1 else _now_epoch_ms() + pttl_ms
    value_sha256 = _sha256({"type": key_type, "value": value})
    return {
        "key": key,
        "type": key_type,
        "value": value,
        "value_sha256": value_sha256,
        "pttl_ms": pttl_ms,
        "expires_at_epoch_ms": expires_at_epoch_ms,
    }


def _namespace_sha256(items: list[dict[str, Any]]) -> str:
    boundary = [
        {
            "key": item["key"],
            "type": item["type"],
            "value_sha256": item["value_sha256"],
            "expires_at_epoch_ms": item["expires_at_epoch_ms"],
        }
        for item in items
    ]
    return _sha256(boundary)


def _content_sha256(items: list[dict[str, Any]]) -> str:
    boundary = [
        {
            "key": item["key"],
            "type": item["type"],
            "value_sha256": item["value_sha256"],
        }
        for item in items
    ]
    return _sha256(boundary)


def _scan_keys(client: Redis, prefix: str) -> list[str]:
    return sorted(
        _text(raw_key, context="Redis key")
        for raw_key in client.scan_iter(match=f"{prefix}*")
    )


def _verify_source_consistency(
    client: Redis,
    *,
    prefix: str,
    items: list[dict[str, Any]],
) -> None:
    keys = _scan_keys(client, prefix)
    expected_keys = [item["key"] for item in items]
    if keys != expected_keys:
        raise MaintenanceError("Agent Hub namespace changed during export; retry from a quiesced source")

    for expected in items:
        current = _read_item(client, expected["key"])
        if current["type"] != expected["type"] or current["value_sha256"] != expected["value_sha256"]:
            raise MaintenanceError(
                f"Agent Hub key changed during export: {expected['key']}; retry from a quiesced source"
            )
        expected_expiry = expected["expires_at_epoch_ms"]
        current_expiry = current["expires_at_epoch_ms"]
        if (expected_expiry is None) != (current_expiry is None):
            raise MaintenanceError(f"TTL class changed during export: {expected['key']}")
        if (
            expected_expiry is not None
            and current_expiry is not None
            and abs(current_expiry - expected_expiry) > TTL_TOLERANCE_MS
        ):
            raise MaintenanceError(f"TTL changed during export: {expected['key']}")


def export_namespace(client: Redis, namespace: str) -> dict[str, Any]:
    namespace = _namespace(namespace)
    prefix = f"{namespace}:"
    capture_started_at_epoch_ms = _now_epoch_ms()
    keys = _scan_keys(client, prefix)
    items = [_read_item(client, key) for key in keys]
    _verify_source_consistency(client, prefix=prefix, items=items)
    capture_completed_at_epoch_ms = _now_epoch_ms()
    type_counts = dict(sorted(Counter(item["type"] for item in items).items()))

    return {
        "version": BACKUP_VERSION,
        "namespace": namespace,
        "created_at": _utc_iso(capture_started_at_epoch_ms),
        "created_at_epoch_ms": capture_started_at_epoch_ms,
        "capture_completed_at_epoch_ms": capture_completed_at_epoch_ms,
        "capture_duration_ms": capture_completed_at_epoch_ms - capture_started_at_epoch_ms,
        "source_consistency": "PASS",
        "key_count": len(items),
        "type_counts": type_counts,
        "namespace_sha256": _namespace_sha256(items),
        "content_sha256": _content_sha256(items),
        "items": items,
    }


def _normalized_items(payload: dict[str, Any], *, namespace: str) -> list[dict[str, Any]]:
    version = payload.get("version")
    if version not in SUPPORTED_BACKUP_VERSIONS:
        raise MaintenanceError("unsupported Agent Hub backup version")
    if payload.get("namespace") != namespace:
        raise MaintenanceError("backup namespace does not match configured Agent Hub namespace")

    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise MaintenanceError("backup payload does not contain an item list")

    prefix = f"{namespace}:"
    normalized: list[dict[str, Any]] = []
    keys: set[str] = set()
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            raise MaintenanceError("backup contains an invalid item")
        key = raw_item.get("key")
        key_type = raw_item.get("type")
        if not isinstance(key, str) or not key.startswith(prefix):
            raise MaintenanceError("backup contains a key outside the Agent Hub namespace")
        if key in keys:
            raise MaintenanceError(f"backup contains duplicate key: {key}")
        keys.add(key)
        if key_type not in SUPPORTED_TYPES:
            raise MaintenanceError(f"backup contains unsupported Redis type: {key_type}")
        value = _normalize_value(
            str(key_type),
            raw_item.get("value"),
            key=key,
            strict=version == BACKUP_VERSION,
        )

        if version == LEGACY_BACKUP_VERSION:
            pttl_ms = -1
            expires_at_epoch_ms = None
        else:
            pttl_ms = raw_item.get("pttl_ms")
            expires_at_epoch_ms = raw_item.get("expires_at_epoch_ms")
            if isinstance(pttl_ms, bool) or not isinstance(pttl_ms, int) or pttl_ms < -1:
                raise MaintenanceError(f"invalid pttl_ms for {key}")
            if pttl_ms == -1:
                if expires_at_epoch_ms is not None:
                    raise MaintenanceError(f"non-expiring key has expires_at_epoch_ms: {key}")
            elif (
                isinstance(expires_at_epoch_ms, bool)
                or not isinstance(expires_at_epoch_ms, int)
                or expires_at_epoch_ms <= 0
            ):
                raise MaintenanceError(f"expiring key has invalid expires_at_epoch_ms: {key}")

        value_sha256 = _sha256({"type": key_type, "value": value})
        if version == BACKUP_VERSION and raw_item.get("value_sha256") != value_sha256:
            raise MaintenanceError(f"value checksum mismatch for {key}")
        normalized.append(
            {
                "key": key,
                "type": key_type,
                "value": value,
                "value_sha256": value_sha256,
                "pttl_ms": pttl_ms,
                "expires_at_epoch_ms": expires_at_epoch_ms,
            }
        )

    if payload.get("key_count", len(normalized)) != len(normalized):
        raise MaintenanceError("backup key_count does not match item count")

    if version == BACKUP_VERSION:
        created_at_epoch_ms = payload.get("created_at_epoch_ms")
        if (
            isinstance(created_at_epoch_ms, bool)
            or not isinstance(created_at_epoch_ms, int)
            or created_at_epoch_ms <= 0
        ):
            raise MaintenanceError("backup created_at_epoch_ms is invalid")
        expected_types = dict(sorted(Counter(item["type"] for item in normalized).items()))
        if payload.get("type_counts") != expected_types:
            raise MaintenanceError("backup type_counts does not match items")
        if payload.get("namespace_sha256") != _namespace_sha256(normalized):
            raise MaintenanceError("backup namespace checksum mismatch")
        if payload.get("content_sha256") != _content_sha256(normalized):
            raise MaintenanceError("backup content checksum mismatch")
        if payload.get("source_consistency") != "PASS":
            raise MaintenanceError("backup source consistency was not proven")

    return sorted(normalized, key=lambda item: item["key"])


def verify_namespace(
    client: Redis,
    payload: dict[str, Any],
    *,
    namespace: str,
    now_epoch_ms: int | None = None,
) -> dict[str, Any]:
    namespace = _namespace(namespace)
    items = _normalized_items(payload, namespace=namespace)
    now_epoch_ms = _now_epoch_ms() if now_epoch_ms is None else now_epoch_ms
    active = [
        item
        for item in items
        if item["expires_at_epoch_ms"] is None or item["expires_at_epoch_ms"] > now_epoch_ms
    ]
    prefix = f"{namespace}:"
    actual_keys = _scan_keys(client, prefix)
    expected_keys = [item["key"] for item in active]
    if actual_keys != expected_keys:
        raise MaintenanceError("restored Agent Hub key set does not match backup")

    actual_items: list[dict[str, Any]] = []
    ttl_key_count = 0
    for expected in active:
        actual = _read_item(client, expected["key"])
        actual_items.append(actual)
        if actual["type"] != expected["type"]:
            raise MaintenanceError(f"restored Redis type mismatch for {expected['key']}")
        if actual["value_sha256"] != expected["value_sha256"]:
            raise MaintenanceError(f"restored value checksum mismatch for {expected['key']}")
        expected_expiry = expected["expires_at_epoch_ms"]
        actual_expiry = actual["expires_at_epoch_ms"]
        if expected_expiry is None:
            if actual_expiry is not None:
                raise MaintenanceError(f"restored non-expiring key gained a TTL: {expected['key']}")
        else:
            ttl_key_count += 1
            if actual_expiry is None:
                raise MaintenanceError(f"restored expiring key lost its TTL: {expected['key']}")
            if abs(actual_expiry - expected_expiry) > TTL_TOLERANCE_MS:
                raise MaintenanceError(f"restored TTL mismatch for {expected['key']}")

    return {
        "status": "PASS",
        "namespace": namespace,
        "backup_version": payload["version"],
        "expected_active_key_count": len(active),
        "expired_since_capture_count": len(items) - len(active),
        "restored_key_count": len(actual_items),
        "ttl_key_count": ttl_key_count,
        "content_sha256": _content_sha256(actual_items),
        "values_logged": False,
    }


def restore_namespace(
    client: Redis,
    payload: dict[str, Any],
    *,
    namespace: str,
    replace: bool = False,
    now_epoch_ms: int | None = None,
) -> int:
    namespace = _namespace(namespace)
    normalized = _normalized_items(payload, namespace=namespace)
    now_epoch_ms = _now_epoch_ms() if now_epoch_ms is None else now_epoch_ms
    active = [
        item
        for item in normalized
        if item["expires_at_epoch_ms"] is None or item["expires_at_epoch_ms"] > now_epoch_ms
    ]

    prefix = f"{namespace}:"
    existing = _scan_keys(client, prefix)
    if existing and not replace:
        raise MaintenanceError("Agent Hub namespace is not empty; use --replace for an explicit restore")

    pipe = client.pipeline(transaction=True)
    if existing:
        pipe.delete(*existing)

    for item in active:
        key = item["key"]
        key_type = item["type"]
        value = item["value"]
        if key_type == "string":
            pipe.set(key, value)
        elif key_type == "list":
            if value:
                pipe.rpush(key, *value)
        else:
            mapping = {entry["member"]: entry["score"] for entry in value}
            if mapping:
                pipe.zadd(key, mapping)
        if item["expires_at_epoch_ms"] is not None:
            pipe.pexpireat(key, item["expires_at_epoch_ms"])

    pipe.execute()
    verify_namespace(client, payload, namespace=namespace)
    return len(active)


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

    verify = subparsers.add_parser("verify", help="Verify a restored Agent Hub namespace without writing")
    verify.add_argument("--input", default="-", help="Input path or - for stdin")

    args = parser.parse_args(argv)
    client = _client()
    try:
        if args.command == "backup":
            payload = export_namespace(client, settings.store_namespace)
            _write_payload(payload, args.output)
            return 0

        payload = _read_payload(args.input)
        if args.command == "verify":
            report = verify_namespace(client, payload, namespace=settings.store_namespace)
            sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            return 0

        if args.confirm != RESTORE_CONFIRMATION:
            raise MaintenanceError("restore confirmation string is incorrect")
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
