from __future__ import annotations

import json
import sys
from typing import Any, Callable

from .store import HubStore, RedisHubStore, build_store


class ReadModelProbeError(RuntimeError):
    pass


def run_probe(store: HubStore) -> dict[str, Any]:
    if not isinstance(store, RedisHubStore):
        raise ReadModelProbeError("read-model probe requires the Redis backend")
    if not store.health():
        raise ReadModelProbeError("Redis health check failed")

    recent_tasks = store.list_recent_tasks(limit=200)
    restored_tasks = 0
    restored_reports = 0
    for task_id, _ in recent_tasks:
        if store.get_task(task_id) is not None:
            restored_tasks += 1
        if store.get_report(task_id) is not None:
            restored_reports += 1

    readers: dict[str, Callable[[], list[Any]]] = {
        "recent_audit": lambda: store.list_recent_audit(limit=1000),
        "campaigns": lambda: store.list_campaigns(limit=1000),
        "identity_mappings": lambda: store.list_identity_mappings(limit=1000),
        "attribution_quality_snapshots": lambda: store.list_attribution_quality_snapshots(
            limit=1000
        ),
        "attribution_intake_issues": lambda: store.list_attribution_intake_issues(limit=1000),
        "attribution_delivery_receipts": lambda: store.list_attribution_delivery_receipts(
            limit=1000
        ),
        "attribution_heartbeat_receipts": lambda: store.list_attribution_heartbeat_receipts(
            limit=1000
        ),
        "attribution_dead_letters": lambda: store.list_attribution_dead_letters(limit=1000),
        "provider_health_snapshots": lambda: store.list_provider_health_snapshots(limit=1000),
        "provider_alerts": lambda: store.list_provider_alerts(limit=1000),
        "touchpoints": lambda: store.list_touchpoints(limit=1000),
        "attribution_reconciliations": lambda: store.list_attribution_reconciliations(
            limit=1000
        ),
        "attribution_audit": lambda: store.list_attribution_audit(limit=1000),
        "experiments": lambda: store.list_experiments(limit=1000),
    }
    counts = {name: len(reader()) for name, reader in readers.items()}
    scheduler_status_present = store.get_provider_health_scheduler_status() is not None

    return {
        "schema_version": "1.0",
        "status": "PASS",
        "backend": store.backend_name,
        "recent_task_index_count": len(recent_tasks),
        "recent_tasks_restored": restored_tasks,
        "recent_reports_restored": restored_reports,
        "read_model_counts": counts,
        "provider_health_scheduler_status_present": scheduler_status_present,
        "values_logged": False,
        "identifiers_logged": False,
        "write_performed": False,
    }


def main() -> int:
    try:
        report = run_probe(build_store())
    except Exception as exc:  # CLI boundary: emit only the exception class, never Redis values.
        sys.stderr.write(f"Agent Hub Redis read-model probe failed: {type(exc).__name__}\n")
        return 2
    sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
