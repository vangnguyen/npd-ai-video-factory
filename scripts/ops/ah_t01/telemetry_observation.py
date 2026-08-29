#!/usr/bin/env python3
"""Build and evaluate identity-safe AH-T01 legacy telemetry observation evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import UUID


EVENT_NAME = "legacy_route_access"
EVENT_MARKER = re.compile(r'\{\s*"event"\s*:\s*"legacy_route_access"')
FINGERPRINT = re.compile(r"^hmac-sha256:[0-9a-f]{24}$")
ALLOWED_SERVICES = {"video-factory-v1-api", "video-factory-v1-renderer"}
ALLOWED_ACTIONS = {
    "health_probe",
    "legacy_write",
    "legacy_read",
    "legacy_artifact_read",
    "legacy_render",
    "legacy_media_read",
}
ROUTE_ACTIONS = {
    "video-factory-v1-api": {
        "/healthz": "health_probe",
        "/readyz": "health_probe",
        "/api/v1/video-jobs": "legacy_write",
        "/api/v1/video-jobs/{job_id}": "legacy_read",
        "/api/v1/video-jobs/{job_id}/artifacts/{artifact_name}": "legacy_artifact_read",
    },
    "video-factory-v1-renderer": {
        "/healthz": "health_probe",
        "/render": "legacy_render",
        "/media/{path}": "legacy_media_read",
    },
}
REQUIRED_ACCEPTANCE_PATHS = {
    "api_legacy_routes",
    "renderer_render",
    "renderer_media",
}
CALLER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
METHOD = re.compile(r"^[A-Z]{3,10}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_KEYS = {
    "authorization",
    "cookie",
    "ip",
    "peer_host",
    "request_body",
    "response_body",
    "salt",
    "user_agent",
}


class ObservationError(RuntimeError):
    pass


def parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ObservationError(f"invalid timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise ObservationError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def extract_events(lines: Iterable[str]) -> tuple[list[dict[str, Any]], str]:
    raw_lines = list(lines)
    raw = "".join(raw_lines).encode("utf-8")
    events: list[dict[str, Any]] = []
    decoder = json.JSONDecoder()
    for line in raw_lines:
        match = EVENT_MARKER.search(line)
        if match is None:
            continue
        try:
            event, _ = decoder.raw_decode(line[match.start():])
        except json.JSONDecodeError as exc:
            raise ObservationError("malformed legacy telemetry event") from exc
        if isinstance(event, dict) and event.get("event") == EVENT_NAME:
            events.append(event)
    return events, hashlib.sha256(raw).hexdigest()


def validate_event(event: dict[str, Any]) -> datetime:
    forbidden = sorted(FORBIDDEN_KEYS.intersection(key.casefold() for key in event))
    if forbidden:
        raise ObservationError(f"event contains forbidden field(s): {', '.join(forbidden)}")
    service = event.get("service")
    if service not in ALLOWED_SERVICES:
        raise ObservationError("event service is not an accepted V1 telemetry source")
    action = event.get("action")
    if action not in ALLOWED_ACTIONS:
        raise ObservationError("event action is not recognized")
    route = event.get("route")
    if not isinstance(route, str) or ROUTE_ACTIONS[str(service)].get(route) != action:
        raise ObservationError("event route/action is not an accepted fixed telemetry label")
    method = event.get("method")
    if not isinstance(method, str) or not METHOD.fullmatch(method):
        raise ObservationError("event method is invalid")
    status_code = event.get("status_code")
    if (
        isinstance(status_code, bool)
        or not isinstance(status_code, int)
        or not 100 <= status_code <= 599
    ):
        raise ObservationError("event status_code is invalid")
    claimed_caller = event.get("claimed_caller_id")
    if claimed_caller is not None and (
        not isinstance(claimed_caller, str) or not CALLER_ID.fullmatch(claimed_caller)
    ):
        raise ObservationError("claimed_caller_id is not a safe fixed label")
    deprecated_attempt = event.get("deprecated_attempt")
    if not isinstance(deprecated_attempt, bool) or deprecated_attempt != (action != "health_probe"):
        raise ObservationError("deprecated_attempt is inconsistent with action")
    if event.get("identity_ready") is not True:
        raise ObservationError("identity_ready must be true before the observation clock starts")
    if event.get("payload_logged") is not False:
        raise ObservationError("payload_logged must remain false")
    if event.get("raw_network_identity_logged") is not False:
        raise ObservationError("raw_network_identity_logged must remain false")
    for field in ("source_fingerprint", "client_fingerprint"):
        value = event.get(field)
        if not isinstance(value, str) or not FINGERPRINT.fullmatch(value):
            raise ObservationError(f"{field} is missing or invalid")
    try:
        UUID(str(event.get("process_instance_id")))
    except (ValueError, TypeError) as exc:
        raise ObservationError("process_instance_id is not a UUID") from exc
    for field in ("route_request_count", "deprecated_attempt_count"):
        value = event.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ObservationError(f"{field} is invalid")
    return parse_time(str(event.get("observed_at", "")))


def attribution_status(claimed_caller_id: Any) -> str:
    return (
        "ATTRIBUTED"
        if isinstance(claimed_caller_id, str) and claimed_caller_id != "invalid"
        else "UNATTRIBUTED"
    )


def path_coverage_label(service: Any, route: Any) -> str | None:
    if service == "video-factory-v1-api" and route in ROUTE_ACTIONS["video-factory-v1-api"]:
        return None if route in {"/healthz", "/readyz"} else "api_legacy_routes"
    if service == "video-factory-v1-renderer" and route == "/render":
        return "renderer_render"
    if service == "video-factory-v1-renderer" and route == "/media/{path}":
        return "renderer_media"
    return None


def summarize(
    lines: Iterable[str],
    *,
    window_start: datetime,
    window_end: datetime,
) -> dict[str, Any]:
    if window_end <= window_start:
        raise ObservationError("window end must be after window start")
    events, source_sha256 = extract_events(lines)
    if not events:
        raise ObservationError("no legacy telemetry events were found")

    timed: list[tuple[datetime, dict[str, Any]]] = []
    for event in events:
        observed_at = validate_event(event)
        if not window_start <= observed_at < window_end:
            raise ObservationError("event falls outside the declared observation window")
        timed.append((observed_at, event))
    timed.sort(key=lambda item: item[0])

    route_last: dict[tuple[str, str, str], int] = {}
    route_bounds: dict[tuple[str, str, str], list[int]] = {}
    deprecated_last: dict[tuple[str, str], int] = {}
    deprecated_bounds: dict[tuple[str, str], list[int]] = {}
    process_bounds: dict[tuple[str, str], list[datetime]] = {}
    aggregate_counts: Counter[tuple[Any, ...]] = Counter()
    for observed_at, event in timed:
        service = str(event["service"])
        process_id = str(event["process_instance_id"])
        route = str(event["route"])
        route_key = (service, process_id, route)
        route_count = int(event["route_request_count"])
        if route_key in route_last and route_count != route_last[route_key] + 1:
            raise ObservationError("route counter gap/reset detected within a process instance")
        route_last[route_key] = route_count
        boundary = route_bounds.setdefault(route_key, [route_count, route_count, 0])
        boundary[1] = route_count
        boundary[2] += 1

        deprecated_key = (service, process_id)
        deprecated_count = int(event["deprecated_attempt_count"])
        previous = deprecated_last.get(deprecated_key)
        if previous is not None:
            expected = previous + int(bool(event["deprecated_attempt"]))
            if deprecated_count != expected:
                raise ObservationError("deprecated counter gap/reset detected within a process instance")
        deprecated_last[deprecated_key] = deprecated_count
        deprecated_boundary = deprecated_bounds.setdefault(
            deprecated_key, [deprecated_count, deprecated_count, 0]
        )
        deprecated_boundary[1] = deprecated_count
        deprecated_boundary[2] += 1

        bounds = process_bounds.setdefault((service, process_id), [observed_at, observed_at])
        bounds[1] = observed_at
        aggregate_counts[
            (
                service,
                route,
                str(event["action"]),
                str(event["method"]),
                int(event["status_code"]),
                event.get("claimed_caller_id"),
                str(event["source_fingerprint"]),
                str(event["client_fingerprint"]),
            )
        ] += 1

    aggregates = [
        {
            "service": key[0],
            "route": key[1],
            "action": key[2],
            "method": key[3],
            "status_code": key[4],
            "claimed_caller_id": key[5],
            "attribution_status": attribution_status(key[5]),
            "source_fingerprint": key[6],
            "client_fingerprint": key[7],
            "event_count": count,
        }
        for key, count in sorted(aggregate_counts.items(), key=lambda item: tuple(str(v) for v in item[0]))
    ]
    processes = [
        {
            "service": service,
            "process_instance_id": process_id,
            "first_observed_at": iso(bounds[0]),
            "last_observed_at": iso(bounds[1]),
        }
        for (service, process_id), bounds in sorted(process_bounds.items())
    ]
    route_counter_boundaries = [
        {
            "service": service,
            "process_instance_id": process_id,
            "route": route,
            "first_count": bounds[0],
            "last_count": bounds[1],
            "observed_event_count": bounds[2],
        }
        for (service, process_id, route), bounds in sorted(route_bounds.items())
    ]
    deprecated_counter_boundaries = [
        {
            "service": service,
            "process_instance_id": process_id,
            "first_count": bounds[0],
            "last_count": bounds[1],
            "observed_event_count": bounds[2],
        }
        for (service, process_id), bounds in sorted(deprecated_bounds.items())
    ]
    return {
        "schema_version": "1.0",
        "status": "PASS",
        "window_start": iso(window_start),
        "window_end": iso(window_end),
        "window_seconds": int((window_end - window_start).total_seconds()),
        "source_log_sha256": source_sha256,
        "event_count": len(timed),
        "process_instances": processes,
        "route_counter_boundaries": route_counter_boundaries,
        "deprecated_counter_boundaries": deprecated_counter_boundaries,
        "aggregates": aggregates,
        "safety": {
            "identity_ready": True,
            "payload_logged": False,
            "raw_network_identity_logged": False,
            "counter_continuity": "PASS",
        },
        "reset_required": False,
    }


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ObservationError(f"could not read JSON evidence: {path.name}") from exc
    if not isinstance(payload, dict):
        raise ObservationError(f"JSON evidence must be an object: {path.name}")
    return payload


def evaluate(
    daily: list[dict[str, Any]],
    *,
    caller_map: dict[str, Any],
    restart_ledger: dict[str, Any],
    minimum_days: int = 14,
) -> dict[str, Any]:
    if len(daily) < minimum_days:
        raise ObservationError(f"at least {minimum_days} complete daily summaries are required")
    ordered = sorted(daily, key=lambda item: parse_time(str(item.get("window_start", ""))))
    seen_source_hashes: set[str] = set()
    for index, day in enumerate(ordered):
        if day.get("schema_version") != "1.0":
            raise ObservationError("daily summary schema_version is not accepted")
        if day.get("status") != "PASS" or day.get("reset_required") is not False:
            raise ObservationError("a daily summary is not accepted PASS evidence")
        start = parse_time(str(day.get("window_start", "")))
        end = parse_time(str(day.get("window_end", "")))
        if int((end - start).total_seconds()) != 86_400:
            raise ObservationError("each daily summary must cover exactly 24 hours")
        if day.get("window_seconds") != 86_400:
            raise ObservationError("daily window_seconds is not exactly 24 hours")
        if index and parse_time(str(ordered[index - 1]["window_end"])) != start:
            raise ObservationError("daily summaries are not consecutive")
        source_hash = day.get("source_log_sha256")
        if not isinstance(source_hash, str) or not SHA256.fullmatch(source_hash):
            raise ObservationError("daily source log checksum is invalid")
        if source_hash in seen_source_hashes:
            raise ObservationError("a daily source log checksum was reused")
        seen_source_hashes.add(source_hash)
        event_count = day.get("event_count")
        if isinstance(event_count, bool) or not isinstance(event_count, int) or event_count < 1:
            raise ObservationError("daily event_count must be a positive integer")
        safety = day.get("safety")
        if not isinstance(safety, dict) or safety != {
            "identity_ready": True,
            "payload_logged": False,
            "raw_network_identity_logged": False,
            "counter_continuity": "PASS",
        }:
            raise ObservationError("daily safety contract is incomplete or unsafe")
        for field in (
            "aggregates",
            "process_instances",
            "route_counter_boundaries",
            "deprecated_counter_boundaries",
        ):
            if not isinstance(day.get(field), list) or not day[field]:
                raise ObservationError(f"daily {field} evidence is missing")
        aggregate_total = 0
        for aggregate in day["aggregates"]:
            count = aggregate.get("event_count") if isinstance(aggregate, dict) else None
            if isinstance(count, bool) or not isinstance(count, int) or count < 1:
                raise ObservationError("daily aggregate event_count is invalid")
            aggregate_total += count
        if aggregate_total != event_count:
            raise ObservationError("daily aggregate counts do not match event_count")

    mappings = caller_map.get("accepted_mappings")
    if not isinstance(mappings, list):
        raise ObservationError("caller map must contain accepted_mappings")
    accepted = {
        (
            item.get("service"),
            item.get("source_fingerprint"),
            item.get("client_fingerprint"),
            item.get("claimed_caller_id"),
            action,
        )
        for item in mappings
        if isinstance(item, dict) and item.get("accepted_by_owner") is True
        and (
            item.get("claimed_caller_id") is not None
            or (isinstance(item.get("owner_label"), str) and item["owner_label"].strip())
        )
        for action in item.get("allowed_actions", [])
    }
    unexplained_by_identity: dict[tuple[Any, ...], dict[str, Any]] = {}
    unattributed_by_identity: dict[tuple[Any, ...], dict[str, Any]] = {}
    accepted_path_coverage: set[str] = set()
    counter_boundary_gaps: list[dict[str, Any]] = []
    last_route_count: dict[tuple[str, str, str], int] = {}
    last_deprecated_count: dict[tuple[str, str], int] = {}
    processes_by_service: defaultdict[str, list[tuple[datetime, str]]] = defaultdict(list)
    seen_processes: set[tuple[str, str]] = set()
    for day in ordered:
        for boundary in day.get("route_counter_boundaries", []):
            if not isinstance(boundary, dict):
                raise ObservationError("route counter boundary must be an object")
            key = (
                str(boundary.get("service")),
                str(boundary.get("process_instance_id")),
                str(boundary.get("route")),
            )
            try:
                first_count = int(boundary.get("first_count", -1))
                last_count = int(boundary.get("last_count", -1))
                observed_count = int(boundary.get("observed_event_count", -1))
            except (TypeError, ValueError) as exc:
                raise ObservationError("route counter boundary contains an invalid count") from exc
            if first_count < 1 or last_count < first_count or observed_count != last_count - first_count + 1:
                raise ObservationError("route counter boundary is internally inconsistent")
            if key in last_route_count and first_count != last_route_count[key] + 1:
                counter_boundary_gaps.append(
                    {
                        "service": key[0],
                        "process_instance_id": key[1],
                        "route": key[2],
                    }
                )
            last_route_count[key] = last_count
        for boundary in day.get("deprecated_counter_boundaries", []):
            if not isinstance(boundary, dict):
                raise ObservationError("deprecated counter boundary must be an object")
            key = (str(boundary.get("service")), str(boundary.get("process_instance_id")))
            try:
                first_count = int(boundary.get("first_count", -1))
                last_count = int(boundary.get("last_count", -1))
            except (TypeError, ValueError) as exc:
                raise ObservationError("deprecated counter boundary contains an invalid count") from exc
            if first_count < 0 or last_count < first_count:
                raise ObservationError("deprecated counter boundary is internally inconsistent")
            if key in last_deprecated_count and first_count not in {
                last_deprecated_count[key],
                last_deprecated_count[key] + 1,
            }:
                counter_boundary_gaps.append(
                    {"service": key[0], "process_instance_id": key[1], "counter": "deprecated"}
                )
            last_deprecated_count[key] = last_count
        for aggregate in day.get("aggregates", []):
            if aggregate.get("action") == "health_probe":
                continue
            expected_attribution = attribution_status(aggregate.get("claimed_caller_id"))
            if aggregate.get("attribution_status") != expected_attribution:
                raise ObservationError("daily aggregate attribution_status is inconsistent")
            key = (
                aggregate.get("service"),
                aggregate.get("source_fingerprint"),
                aggregate.get("client_fingerprint"),
                aggregate.get("claimed_caller_id"),
                aggregate.get("action"),
            )
            record = {
                name: aggregate.get(name)
                for name in (
                    "service",
                    "route",
                    "action",
                    "claimed_caller_id",
                    "attribution_status",
                    "source_fingerprint",
                    "client_fingerprint",
                )
            }
            mapping_accepted = key in accepted
            coverage = path_coverage_label(aggregate.get("service"), aggregate.get("route"))
            if mapping_accepted and coverage is not None:
                accepted_path_coverage.add(coverage)
            if expected_attribution == "UNATTRIBUTED":
                unattributed_by_identity[key] = {
                    **record,
                    "owner_mapping_accepted": mapping_accepted,
                }
            if key not in accepted:
                unexplained_by_identity[key] = record
        for process in day.get("process_instances", []):
            identity = (str(process.get("service")), str(process.get("process_instance_id")))
            if identity not in seen_processes:
                seen_processes.add(identity)
                processes_by_service[identity[0]].append(
                    (parse_time(str(process.get("first_observed_at", ""))), identity[1])
                )

    accepted_restarts = {
        (item.get("service"), item.get("process_instance_id"))
        for item in restart_ledger.get("accepted_process_restarts", [])
        if isinstance(item, dict)
        and item.get("accepted_by_owner") is True
        and isinstance(item.get("reason"), str)
        and item["reason"].strip()
    }
    unaccepted_restarts: list[dict[str, str]] = []
    for service, processes in processes_by_service.items():
        for _, process_id in sorted(processes)[1:]:
            if (service, process_id) not in accepted_restarts:
                unaccepted_restarts.append({"service": service, "process_instance_id": process_id})

    missing_path_coverage = sorted(REQUIRED_ACCEPTANCE_PATHS - accepted_path_coverage)
    unexplained = list(unexplained_by_identity.values())
    unattributed = list(unattributed_by_identity.values())
    reset_required = bool(
        unexplained or unaccepted_restarts or counter_boundary_gaps or missing_path_coverage
    )
    return {
        "schema_version": "1.0",
        "status": "FAIL" if reset_required else "PASS",
        "complete_consecutive_days": len(ordered),
        "window_start": ordered[0]["window_start"],
        "window_end": ordered[-1]["window_end"],
        "unexplained_callers": unexplained,
        "unattributed_callers": unattributed,
        "path_coverage": {
            label: "PASS" if label in accepted_path_coverage else "FAIL"
            for label in sorted(REQUIRED_ACCEPTANCE_PATHS)
        },
        "missing_path_coverage": missing_path_coverage,
        "unaccepted_restarts": unaccepted_restarts,
        "counter_boundary_gaps": counter_boundary_gaps,
        "reset_required": reset_required,
        "ah03_authorized": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    summarize_parser = subparsers.add_parser("summarize")
    summarize_parser.add_argument("--window-start", required=True)
    summarize_parser.add_argument("--window-end", required=True)
    evaluate_parser = subparsers.add_parser("evaluate")
    evaluate_parser.add_argument("--daily-file", action="append", required=True)
    evaluate_parser.add_argument("--caller-map", required=True)
    evaluate_parser.add_argument("--restart-ledger", required=True)
    evaluate_parser.add_argument("--minimum-days", type=int, default=14)
    args = parser.parse_args(argv)
    try:
        if args.command == "summarize":
            report = summarize(
                sys.stdin,
                window_start=parse_time(args.window_start),
                window_end=parse_time(args.window_end),
            )
        else:
            report = evaluate(
                [_load_json(Path(path)) for path in args.daily_file],
                caller_map=_load_json(Path(args.caller_map)),
                restart_ledger=_load_json(Path(args.restart_ledger)),
                minimum_days=args.minimum_days,
            )
    except ObservationError as exc:
        sys.stderr.write(f"AH-T01 telemetry evidence failed: {exc}\n")
        return 2
    sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return 0 if report.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
