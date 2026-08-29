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


def renderer_event(
    *,
    observed_at: datetime,
    route: str,
    action: str,
    route_count: int,
    deprecated_count: int,
    claimed_caller_id: str | None = "video-factory-v1-worker",
) -> dict:
    return {
        "event": "legacy_route_access",
        "observed_at": observed_at.isoformat(),
        "process_instance_id": "f57d39eb-f2d0-46e0-92f4-7982b76a1c81",
        "service": "video-factory-v1-renderer",
        "route": route,
        "method": "POST" if route == "/render" else "GET",
        "status_code": 200,
        "action": action,
        "deprecated_attempt": True,
        "claimed_caller_id": claimed_caller_id,
        "source_fingerprint": "hmac-sha256:" + "c" * 24,
        "client_fingerprint": "hmac-sha256:" + "d" * 24,
        "identity_ready": True,
        "route_request_count": route_count,
        "deprecated_attempt_count": deprecated_count,
        "payload_logged": False,
        "raw_network_identity_logged": False,
    }


def complete_day(
    day_start: datetime,
    index: int,
    *,
    include_media: bool = True,
    media_caller_id: str | None = "video-factory-v1-worker",
) -> dict:
    renderer_events_per_day = 2 if include_media else 1
    lines = [
        json.dumps(event(observed_at=day_start + timedelta(hours=1), count=index + 1)) + "\n",
        json.dumps(
            renderer_event(
                observed_at=day_start + timedelta(hours=2),
                route="/render",
                action="legacy_render",
                route_count=index + 1,
                deprecated_count=index * renderer_events_per_day + 1,
            )
        )
        + "\n",
    ]
    if include_media:
        lines.append(
            json.dumps(
                renderer_event(
                    observed_at=day_start + timedelta(hours=3),
                    route="/media/{path}",
                    action="legacy_media_read",
                    route_count=index + 1,
                    deprecated_count=index * renderer_events_per_day + 2,
                    claimed_caller_id=media_caller_id,
                )
            )
            + "\n"
        )
    return summarize(lines, window_start=day_start, window_end=day_start + timedelta(days=1))


def accepted_caller_map(*, include_unattributed_media: bool = False) -> dict:
    mappings = [
        {
            "service": "video-factory-v1-api",
            "source_fingerprint": "hmac-sha256:" + "a" * 24,
            "client_fingerprint": "hmac-sha256:" + "b" * 24,
            "claimed_caller_id": "accepted-reader",
            "allowed_actions": ["legacy_read"],
            "accepted_by_owner": True,
        },
        {
            "service": "video-factory-v1-renderer",
            "source_fingerprint": "hmac-sha256:" + "c" * 24,
            "client_fingerprint": "hmac-sha256:" + "d" * 24,
            "claimed_caller_id": "video-factory-v1-worker",
            "allowed_actions": ["legacy_render", "legacy_media_read"],
            "accepted_by_owner": True,
        },
    ]
    if include_unattributed_media:
        mappings.append(
            {
                "service": "video-factory-v1-renderer",
                "source_fingerprint": "hmac-sha256:" + "c" * 24,
                "client_fingerprint": "hmac-sha256:" + "d" * 24,
                "claimed_caller_id": None,
                "allowed_actions": ["legacy_media_read"],
                "owner_label": "owner-explained renderer caller without a fixed label",
                "accepted_by_owner": True,
            }
        )
    return {"accepted_mappings": mappings}


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
    assert report["aggregates"][0]["attribution_status"] == "ATTRIBUTED"
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
    daily = [complete_day(start + timedelta(days=index), index) for index in range(14)]
    caller_map = accepted_caller_map()
    result = evaluate(daily, caller_map=caller_map, restart_ledger={"accepted_process_restarts": []})
    assert result["status"] == "PASS"
    assert result["reset_required"] is False
    assert set(result["path_coverage"].values()) == {"PASS"}
    assert result["ah03_authorized"] is False

    caller_map["accepted_mappings"] = []
    failed = evaluate(daily, caller_map=caller_map, restart_ledger={"accepted_process_restarts": []})
    assert failed["status"] == "FAIL"
    assert failed["reset_required"] is True


def test_evaluate_rejects_tampered_or_discontinuous_daily_evidence():
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    daily = [complete_day(start + timedelta(days=index), index) for index in range(14)]
    caller_map = accepted_caller_map()

    api_boundary = next(
        boundary
        for boundary in daily[5]["route_counter_boundaries"]
        if boundary["service"] == "video-factory-v1-api"
    )
    api_boundary.update(
        {"first_count": 99, "last_count": 99, "observed_event_count": 1}
    )
    discontinuous = evaluate(
        daily, caller_map=caller_map, restart_ledger={"accepted_process_restarts": []}
    )
    assert discontinuous["status"] == "FAIL"
    assert discontinuous["reset_required"] is True
    assert discontinuous["counter_boundary_gaps"]

    daily[5] = complete_day(start + timedelta(days=5), 5)
    daily[7]["safety"]["identity_ready"] = False
    with pytest.raises(ObservationError, match="safety contract"):
        evaluate(daily, caller_map=caller_map, restart_ledger={"accepted_process_restarts": []})


def test_unattributed_renderer_requires_an_owner_mapping_before_pass():
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    daily = [
        complete_day(start + timedelta(days=index), index, media_caller_id=None)
        for index in range(14)
    ]

    failed = evaluate(
        daily,
        caller_map=accepted_caller_map(),
        restart_ledger={"accepted_process_restarts": []},
    )
    assert failed["status"] == "FAIL"
    assert failed["reset_required"] is True
    assert failed["path_coverage"]["renderer_media"] == "FAIL"
    assert failed["unattributed_callers"] == [
        {
            "service": "video-factory-v1-renderer",
            "route": "/media/{path}",
            "action": "legacy_media_read",
            "claimed_caller_id": None,
            "attribution_status": "UNATTRIBUTED",
            "source_fingerprint": "hmac-sha256:" + "c" * 24,
            "client_fingerprint": "hmac-sha256:" + "d" * 24,
            "owner_mapping_accepted": False,
        }
    ]

    unexplained_map = accepted_caller_map(include_unattributed_media=True)
    unexplained_map["accepted_mappings"][-1]["owner_label"] = ""
    still_failed = evaluate(
        daily,
        caller_map=unexplained_map,
        restart_ledger={"accepted_process_restarts": []},
    )
    assert still_failed["status"] == "FAIL"
    assert still_failed["unattributed_callers"][0]["owner_mapping_accepted"] is False

    explained = evaluate(
        daily,
        caller_map=accepted_caller_map(include_unattributed_media=True),
        restart_ledger={"accepted_process_restarts": []},
    )
    assert explained["status"] == "PASS"
    assert explained["unattributed_callers"][0]["owner_mapping_accepted"] is True
    assert explained["path_coverage"]["renderer_media"] == "PASS"


def test_evaluate_requires_api_render_and_media_path_coverage():
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    daily = [
        complete_day(start + timedelta(days=index), index, include_media=False)
        for index in range(14)
    ]
    result = evaluate(
        daily,
        caller_map=accepted_caller_map(),
        restart_ledger={"accepted_process_restarts": []},
    )
    assert result["status"] == "FAIL"
    assert result["missing_path_coverage"] == ["renderer_media"]
    assert result["path_coverage"] == {
        "api_legacy_routes": "PASS",
        "renderer_media": "FAIL",
        "renderer_render": "PASS",
    }
