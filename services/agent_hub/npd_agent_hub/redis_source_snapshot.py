from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from typing import Any

from redis import Redis

from .config import settings
from .redis_connection import create_redis_client


class SourceSnapshotError(RuntimeError):
    pass


def _keys(client: Redis) -> set[str]:
    return {str(key) for key in client.scan_iter(match="*", count=1000)}


def snapshot_source(
    client: Redis,
    *,
    namespace: str,
    require_exclusive_namespace: bool = False,
) -> dict[str, Any]:
    prefix = namespace.strip(":") + ":"
    first_size = int(client.dbsize())
    first_keys = _keys(client)
    type_counts: Counter[str] = Counter()
    namespace_keys = sorted(key for key in first_keys if key.startswith(prefix))
    for key in namespace_keys:
        type_counts[str(client.type(key))] += 1
    second_keys = _keys(client)
    second_size = int(client.dbsize())
    if first_size != second_size or first_keys != second_keys or second_size != len(second_keys):
        raise SourceSnapshotError("Redis source changed during boundary snapshot")
    outside_count = len(second_keys) - len(namespace_keys)
    if require_exclusive_namespace and outside_count:
        raise SourceSnapshotError("Redis DB contains keys outside the Agent Hub namespace")
    digest = hashlib.sha256()
    for key in namespace_keys:
        digest.update(key.encode("utf-8"))
        digest.update(b"\0")
    return {
        "schema_version": "1.0",
        "status": "PASS",
        "namespace": namespace.strip(":"),
        "db_key_count": second_size,
        "namespace_key_count": len(namespace_keys),
        "outside_namespace_key_count": outside_count,
        "namespace_type_counts": dict(sorted(type_counts.items())),
        "namespace_key_name_sha256": digest.hexdigest(),
        "source_consistency": "PASS",
        "values_logged": False,
        "identifiers_logged": False,
        "write_performed": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Identity-safe Agent Hub Redis source snapshot")
    parser.add_argument("--require-exclusive-namespace", action="store_true")
    args = parser.parse_args(argv)
    client: Redis | None = None
    try:
        client = create_redis_client(
            settings.agent_redis_url,
            password_file=settings.agent_redis_password_file,
        )
        report = snapshot_source(
            client,
            namespace=settings.store_namespace,
            require_exclusive_namespace=args.require_exclusive_namespace,
        )
    except Exception as exc:  # CLI boundary: never emit Redis keys or values.
        sys.stderr.write(f"Agent Hub Redis source snapshot failed: {type(exc).__name__}\n")
        return 2
    finally:
        if client is not None:
            client.close()
    sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
