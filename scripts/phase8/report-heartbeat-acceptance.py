#!/usr/bin/env python3
"""Build a read-only heartbeat acceptance report from Agent Hub APIs."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def api(base_url: str, token: str, path: str) -> Any:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def build_report(
    *,
    now: datetime,
    window_hours: int,
    interval_seconds: int,
    heartbeats: list[dict[str, Any]],
    alerts: list[dict[str, Any]],
    provider_status: dict[str, Any],
    scheduler: dict[str, Any],
    redis_baseline_bytes: int | None = None,
    redis_current_bytes: int | None = None,
) -> dict[str, Any]:
    window_start = now - timedelta(hours=window_hours)
    receipts = sorted(
        (
            item
            for item in heartbeats
            if item.get("producer") == "n8n_lead_intake"
            and (parse_time(item.get("received_at")) or datetime.min.replace(tzinfo=timezone.utc))
            >= window_start
        ),
        key=lambda item: parse_time(item.get("received_at")) or window_start,
    )
    times = [parse_time(item.get("received_at")) for item in receipts]
    times = [item for item in times if item is not None]
    observation_start = times[0] if times else None
    coverage_seconds = max(0, (now - observation_start).total_seconds()) if observation_start else 0
    expected = math.floor(coverage_seconds / interval_seconds) + 1 if times else 0
    gaps = [
        (right - left).total_seconds()
        for left, right in zip(times, times[1:])
    ]
    if times:
        gaps.append(max(0, (now - times[-1]).total_seconds()))

    incidents = []
    recovery_seconds: list[float] = []
    for alert in alerts:
        first = parse_time(alert.get("first_detected_at"))
        resolved = parse_time(alert.get("resolved_at"))
        if not first:
            continue
        if first < window_start and resolved and resolved < window_start:
            continue
        duration = ((resolved or now) - first).total_seconds()
        incidents.append(alert)
        if resolved:
            recovery_seconds.append(max(0, duration))

    snapshot = provider_status.get("latest_snapshot") or {}
    providers = snapshot.get("providers") or []
    lead = next(
        (item for item in providers if item.get("provider") == "n8n_lead_intake"),
        {},
    )
    scheduler_last = parse_time(scheduler.get("last_finished_at"))
    scheduler_interval = int(scheduler.get("interval_seconds") or interval_seconds)
    scheduler_lag = (
        max(0, (now - scheduler_last).total_seconds() - scheduler_interval)
        if scheduler_last
        else None
    )
    redis_growth = (
        redis_current_bytes - redis_baseline_bytes
        if redis_baseline_bytes is not None and redis_current_bytes is not None
        else None
    )

    return {
        "generated_at": now.isoformat(),
        "window_hours_requested": window_hours,
        "observation_started_at": observation_start.isoformat() if observation_start else None,
        "window_complete": bool(
            observation_start and observation_start <= window_start + timedelta(seconds=interval_seconds)
        ),
        "heartbeat": {
            "count": len(times),
            "expected_for_observed_coverage": expected,
            "success_rate_percent": round(min(100, len(times) * 100 / expected), 2)
            if expected
            else None,
            "max_gap_seconds": round(max(gaps), 3) if gaps else None,
            "latest_at": times[-1].isoformat() if times else None,
            "latest_age_minutes": lead.get("heartbeat_age_minutes"),
        },
        "lead_activity": {
            "latest_age_minutes": lead.get("activity_age_minutes"),
            "pipeline_alive_without_new_lead": bool(
                lead.get("freshness_evidence") == "heartbeat"
                and lead.get("freshness_state") == "fresh"
                and lead.get("activity_age_minutes") is not None
                and lead.get("activity_age_minutes", 0) > lead.get("target_minutes", 15)
            ),
        },
        "scheduler": {
            "enabled": scheduler.get("enabled"),
            "state": scheduler.get("state"),
            "run_count": scheduler.get("run_count"),
            "skipped_lease_count": scheduler.get("skipped_lease_count"),
            "last_finished_at": scheduler.get("last_finished_at"),
            "lag_seconds_beyond_interval": round(scheduler_lag, 3)
            if scheduler_lag is not None
            else None,
            "cached_state_only": scheduler.get("evaluates_cached_state_only"),
        },
        "incidents": {
            "count": len(incidents),
            "open": sum(item.get("status") == "open" for item in incidents),
            "resolved": sum(item.get("status") == "resolved" for item in incidents),
            "max_recovery_seconds": round(max(recovery_seconds), 3)
            if recovery_seconds
            else None,
            "false_positive_review_required": len(incidents) > 0,
        },
        "redis": {
            "baseline_bytes": redis_baseline_bytes,
            "current_bytes": redis_current_bytes,
            "growth_bytes": redis_growth,
        },
        "safety": {
            "external_notifications_enabled": provider_status.get(
                "external_notifications_enabled", False
            ),
            "production_write_enabled": provider_status.get(
                "production_write_enabled", False
            ),
            "scheduler_external_probes_enabled": scheduler.get(
                "external_provider_probes_enabled", False
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--window-hours", type=int, default=48)
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--output", default="-")
    parser.add_argument("--redis-baseline-bytes", type=int)
    parser.add_argument("--redis-current-bytes", type=int)
    args = parser.parse_args()
    if not 1 <= args.window_hours <= 168:
        parser.error("--window-hours must be between 1 and 168")
    token = os.environ.get("NPD_AGENT_HUB_TOKEN", "")
    if not token:
        raise SystemExit("NPD_AGENT_HUB_TOKEN is required and is never printed")

    report = build_report(
        now=datetime.now(timezone.utc),
        window_hours=args.window_hours,
        interval_seconds=args.interval_seconds,
        heartbeats=api(
            args.base_url,
            token,
            "/api/v1/attribution/deliveries/heartbeats?producer=n8n_lead_intake&limit=1000",
        ),
        alerts=api(
            args.base_url,
            token,
            "/api/v1/provider-health/alerts?provider=n8n_lead_intake&limit=1000",
        ),
        provider_status=api(args.base_url, token, "/api/v1/provider-health/status"),
        scheduler=api(args.base_url, token, "/api/v1/provider-health/scheduler"),
        redis_baseline_bytes=args.redis_baseline_bytes,
        redis_current_bytes=args.redis_current_bytes,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output == "-":
        sys.stdout.write(rendered)
    else:
        Path(args.output).write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
