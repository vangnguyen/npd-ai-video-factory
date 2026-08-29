from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from telemetry_observation import ObservationError, evaluate, summarize


def event(*, observed_at: datetime, action: str = "legacy_read", count: int = 1) -> dict:
    return {
        "event": "legacy_route_access",
        "observed_at": observed_at.isoformat(),
        "process_instance_id": "84b9a7e6-67ac-4838-ac70-f131dfe4c881",
        "service": "video-factory-v1-api",
        "route": "/api/v1/video-jobs/{job_id}",
        "method": "GET",
        "status_code": 200,
        "action": action,
        "deprecated_attempt": action != "health_probe",
        "claimed_caller_id": "accepted-reader",
        "source_fingerprint": "hmac-sha256:" + "a" * 24,
        "client_fingerprint": "hmac-sha256:" + "b" * 24,
        "identity_ready": True,
        "route_request_count": count,
        "deprecated_attempt_count": count,
        "payload_logged": False,
        "raw_network_identity_logged": False,
    }


def test_summarize_keeps_only_identity_safe_aggregates():
    start = datetime(2026, 8, 29, tzinfo=timezone.utc)
    lines = [
        "prefix " + json.dumps(event(observed_at=start + timedelta(hours=1)), separators=(",", ":")) + "\n",
        "prefix " + json.dumps(event(observed_at=start + timedelta(hours=2), count=2), separators=(",", ":")) + "\n",
    ]
    report = summarize(lines, window_start=start, window_end=start + timedelta(days=1))

    assert report["status"] == "PASS"
    assert report["event_count"] == 2
    assert report["aggregates"][0]["event_count"] == 2
    rendered = json.dumps(report)
    assert "raw.example" not in rendered
    assert report["safety"]["counter_continuity"] == "PASS"


def test_summarize_fails_when_identity_is_disabled():
    start = datetime(2026, 8, 29, tzinfo=timezone.utc)
    invalid = event(observed_at=start + timedelta(hours=1))
    invalid["identity_ready"] = False
    line = json.dumps(invalid, separators=(",", ":")) + "\n"
    with pytest.raises(ObservationError, match="identity_ready"):
        summarize([line], window_start=start, window_end=start + timedelta(days=1))


def test_summarize_rejects_a_concrete_route_that_could_leak_an_identifier():
    start = datetime(2026, 8, 29, tzinfo=timezone.utc)
    invalid = event(observed_at=start + timedelta(hours=1))
    invalid["route"] = "/api/v1/video-jobs/customer-job-123"
    with pytest.raises(ObservationError, match="fixed telemetry label"):
        summarize(
            [json.dumps(invalid, separators=(",", ":")) + "\n"],
            window_start=start,
            window_end=start + timedelta(days=1),
        )


def test_evaluate_requires_owner_mapped_non_health_callers():
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    daily = []
    for index in range(14):
        day_start = start + timedelta(days=index)
        daily.append(
            summarize(
                [json.dumps(event(observed_at=day_start + timedelta(hours=1), count=index + 1)) + "\n"],
                window_start=day_start,
                window_end=day_start + timedelta(days=1),
            )
        )
    caller_map = {
        "accepted_mappings": [
            {
                "service": "video-factory-v1-api",
                "source_fingerprint": "hmac-sha256:" + "a" * 24,
                "client_fingerprint": "hmac-sha256:" + "b" * 24,
                "claimed_caller_id": "accepted-reader",
                "allowed_actions": ["legacy_read"],
                "accepted_by_owner": True,
            }
        ]
    }
    result = evaluate(daily, caller_map=caller_map, restart_ledger={"accepted_process_restarts": []})
    assert result["status"] == "PASS"
    assert result["reset_required"] is False
    assert result["ah03_authorized"] is False

    caller_map["accepted_mappings"] = []
    failed = evaluate(daily, caller_map=caller_map, restart_ledger={"accepted_process_restarts": []})
    assert failed["status"] == "FAIL"
    assert failed["reset_required"] is True


def test_evaluate_rejects_tampered_or_discontinuous_daily_evidence():
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    daily = []
    for index in range(14):
        day_start = start + timedelta(days=index)
        daily.append(
            summarize(
                [json.dumps(event(observed_at=day_start + timedelta(hours=1), count=index + 1)) + "\n"],
                window_start=day_start,
                window_end=day_start + timedelta(days=1),
            )
        )
    caller_map = {
        "accepted_mappings": [
            {
                "service": "video-factory-v1-api",
                "source_fingerprint": "hmac-sha256:" + "a" * 24,
                "client_fingerprint": "hmac-sha256:" + "b" * 24,
                "claimed_caller_id": "accepted-reader",
                "allowed_actions": ["legacy_read"],
                "accepted_by_owner": True,
            }
        ]
    }

    daily[5]["route_counter_boundaries"][0].update(
        {"first_count": 99, "last_count": 99, "observed_event_count": 1}
    )
    discontinuous = evaluate(
        daily, caller_map=caller_map, restart_ledger={"accepted_process_restarts": []}
    )
    assert discontinuous["status"] == "FAIL"
    assert discontinuous["reset_required"] is True
    assert discontinuous["counter_boundary_gaps"]

    daily[5] = summarize(
        [json.dumps(event(observed_at=start + timedelta(days=5, hours=1), count=6)) + "\n"],
        window_start=start + timedelta(days=5),
        window_end=start + timedelta(days=6),
    )
    daily[7]["safety"]["identity_ready"] = False
    with pytest.raises(ObservationError, match="safety contract"):
        evaluate(daily, caller_map=caller_map, restart_ledger={"accepted_process_restarts": []})
