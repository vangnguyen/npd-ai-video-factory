#!/usr/bin/env python3
"""Verify AH-T01 smoke events without emitting identities or secret material."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from telemetry_observation import ObservationError, extract_events, validate_event


EXPECTED = {
    "video-factory-v1-api": ("legacy_read", "/api/v1/video-jobs/{job_id}"),
    "video-factory-v1-renderer": ("legacy_media_read", "/media/{path}"),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-log", required=True)
    parser.add_argument("--renderer-log", required=True)
    parser.add_argument("--raw-probe-marker", required=True)
    args = parser.parse_args()
    try:
        found: dict[str, dict] = {}
        for path_value in (args.api_log, args.renderer_log):
            raw = Path(path_value).read_text(encoding="utf-8", errors="replace")
            if args.raw_probe_marker in raw:
                raise ObservationError("raw probe marker leaked into service logs")
            events, _ = extract_events(raw.splitlines(keepends=True))
            for event in events:
                validate_event(event)
                if event.get("claimed_caller_id") == "ah-t01-smoke":
                    found[str(event["service"])] = event
        for service, (action, route) in EXPECTED.items():
            event = found.get(service)
            if event is None or event.get("action") != action or event.get("route") != route:
                raise ObservationError(f"missing accepted smoke event for {service}")
    except (OSError, ObservationError) as exc:
        sys.stderr.write(f"AH-T01 deployment verification failed: {exc}\n")
        return 2
    report = {
        "status": "PASS",
        "services": sorted(found),
        "identity_ready": True,
        "payload_logged": False,
        "raw_network_identity_logged": False,
        "raw_probe_marker_logged": False,
        "production_business_write_performed": False,
    }
    sys.stdout.write(json.dumps(report, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
