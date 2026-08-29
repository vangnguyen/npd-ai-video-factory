import json
import logging
from pathlib import Path

import pytest

from app.legacy_telemetry import LegacyTelemetry


def test_telemetry_hashes_identity_and_counts_deprecated_routes(caplog):
    telemetry = LegacyTelemetry(salt="test-only-salt")

    with caplog.at_level(logging.INFO, logger="npd.legacy_telemetry"):
        first = telemetry.record(
            route="/api/v1/video-jobs/{job_id}",
            method="GET",
            status_code=200,
            peer_host="203.0.113.42",
            claimed_caller_id="agent-hub-v1-tool",
            user_agent="sensitive-agent/1.0",
        )
        second = telemetry.record(
            route="/api/v1/video-jobs/{job_id}",
            method="GET",
            status_code=404,
            peer_host="203.0.113.42",
            claimed_caller_id="bad caller with spaces",
            user_agent="sensitive-agent/1.0",
        )

    assert first is not None and second is not None
    assert first["source_fingerprint"] == second["source_fingerprint"]
    assert first["source_fingerprint"].startswith("hmac-sha256:")
    assert first["route_request_count"] == 1
    assert second["route_request_count"] == 2
    assert second["deprecated_attempt_count"] == 2
    assert second["claimed_caller_id"] == "invalid"
    assert first["process_instance_id"] == second["process_instance_id"]
    assert first["observed_at"].endswith("+00:00")
    rendered = "\n".join(record.message for record in caplog.records)
    assert "203.0.113.42" not in rendered
    assert "sensitive-agent/1.0" not in rendered
    assert "test-only-salt" not in rendered
    assert all(json.loads(record.message)["payload_logged"] is False for record in caplog.records)


def test_missing_salt_disables_identity_instead_of_logging_raw_values(caplog):
    telemetry = LegacyTelemetry(salt=None)

    with caplog.at_level(logging.INFO, logger="npd.legacy_telemetry"):
        event = telemetry.record(
            route="/healthz",
            method="GET",
            status_code=200,
            peer_host="198.51.100.9",
            claimed_caller_id=None,
            user_agent="probe-secret",
        )

    assert event is not None
    assert event["identity_ready"] is False
    assert event["source_fingerprint"] is None
    assert event["client_fingerprint"] is None
    assert event["deprecated_attempt"] is False
    assert "198.51.100.9" not in caplog.text
    assert "probe-secret" not in caplog.text


def test_unmatched_route_is_not_logged(caplog):
    telemetry = LegacyTelemetry(salt="test-only-salt")
    with caplog.at_level(logging.INFO, logger="npd.legacy_telemetry"):
        event = telemetry.record(
            route=None,
            method="GET",
            status_code=404,
            peer_host="192.0.2.1",
            claimed_caller_id=None,
            user_agent=None,
        )
    assert event is None
    assert caplog.records == []


def test_environment_loads_salt_from_absolute_secret_file(monkeypatch, tmp_path: Path):
    salt_file = tmp_path / "telemetry-salt"
    salt_file.write_text("s" * 32 + "\n", encoding="utf-8")
    monkeypatch.delenv("LEGACY_TELEMETRY_SALT", raising=False)
    monkeypatch.setenv("LEGACY_TELEMETRY_SALT_FILE", str(salt_file.resolve()))

    assert LegacyTelemetry.from_environment().identity_ready is True


def test_environment_fails_closed_on_conflict_or_weak_file(monkeypatch, tmp_path: Path):
    salt_file = tmp_path / "telemetry-salt"
    salt_file.write_text("short", encoding="utf-8")
    monkeypatch.setenv("LEGACY_TELEMETRY_SALT", "d" * 32)
    monkeypatch.setenv("LEGACY_TELEMETRY_SALT_FILE", str(salt_file.resolve()))
    with pytest.raises(RuntimeError, match="only one"):
        LegacyTelemetry.from_environment()

    monkeypatch.delenv("LEGACY_TELEMETRY_SALT")
    with pytest.raises(RuntimeError, match="at least 32 bytes"):
        LegacyTelemetry.from_environment()
