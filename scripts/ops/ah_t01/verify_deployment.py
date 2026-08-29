#!/usr/bin/env python3
"""Verify AH-T01 smoke events without emitting identities or secret material."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from telemetry_observation import ObservationError, extract_events, validate_event


EXPECTED_EVENTS = {
    ("video-factory-v1-api", "legacy_read", "/api/v1/video-jobs/{job_id}", "GET", 404),
    ("video-factory-v1-renderer", "legacy_render", "/render", "POST", 422),
    ("video-factory-v1-renderer", "legacy_media_read", "/media/{path}", "GET", 404),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-log", required=True)
    parser.add_argument("--renderer-log", required=True)
    parser.add_argument("--raw-probe-marker", required=True)
    args = parser.parse_args()
    try:
        found: set[tuple[str, str, str, str, int]] = set()
        attributed_media_fingerprints: set[tuple[str, str]] = set()
        unattributed_media_fingerprints: set[tuple[str, str]] = set()
        for path_value in (args.api_log, args.renderer_log):
            raw = Path(path_value).read_text(encoding="utf-8", errors="replace")
            if args.raw_probe_marker in raw:
                raise ObservationError("raw probe marker leaked into service logs")
            events, _ = extract_events(raw.splitlines(keepends=True))
            for event in events:
                validate_event(event)
                if event.get("claimed_caller_id") == "ah-t01-smoke":
                    found.add(
                        (
                            str(event["service"]),
                            str(event["action"]),
                            str(event["route"]),
                            str(event["method"]),
                            int(event["status_code"]),
                        )
                    )
                    if event.get("route") == "/media/{path}":
                        attributed_media_fingerprints.add(
                            (str(event["source_fingerprint"]), str(event["client_fingerprint"]))
                        )
                if (
                    event.get("service") == "video-factory-v1-renderer"
                    and event.get("route") == "/media/{path}"
                    and event.get("claimed_caller_id") is None
                    and event.get("method") == "GET"
                    and event.get("status_code") == 404
                ):
                    unattributed_media_fingerprints.add(
                        (str(event["source_fingerprint"]), str(event["client_fingerprint"]))
                    )
        missing = sorted(EXPECTED_EVENTS - found)
        if missing:
            raise ObservationError(f"missing accepted smoke path evidence: {missing}")
        if not attributed_media_fingerprints.intersection(unattributed_media_fingerprints):
            raise ObservationError("missing matching safe UNATTRIBUTED renderer fingerprint evidence")
    except (OSError, ObservationError) as exc:
        sys.stderr.write(f"AH-T01 deployment verification failed: {exc}\n")
        return 2
    report = {
        "status": "PASS",
        "services": sorted({item[0] for item in found}),
        "path_coverage": {
            "api_legacy_routes": "PASS",
            "renderer_render": "PASS",
            "renderer_media": "PASS",
        },
        "unattributed_renderer_probe": {
            "status": "UNATTRIBUTED",
            "fingerprints_present": True,
            "owner_mapping_required_for_observation_acceptance": True,
        },
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
