from __future__ import annotations

import json
import sys
from pathlib import Path

from verify_deployment import main


SOURCE = "hmac-sha256:" + "a" * 24
CLIENT = "hmac-sha256:" + "b" * 24


def telemetry_event(
    *,
    service: str,
    route: str,
    action: str,
    method: str,
    status_code: int,
    caller: str | None,
    source: str = SOURCE,
    client: str = CLIENT,
    route_count: int = 1,
    deprecated_count: int = 1,
) -> dict:
    return {
        "event": "legacy_route_access",
        "observed_at": "2026-08-29T01:00:00Z",
        "process_instance_id": "84b9a7e6-67ac-4838-ac70-f131dfe4c881",
        "service": service,
        "route": route,
        "method": method,
        "status_code": status_code,
        "action": action,
        "deprecated_attempt": True,
        "claimed_caller_id": caller,
        "source_fingerprint": source,
        "client_fingerprint": client,
        "identity_ready": True,
        "route_request_count": route_count,
        "deprecated_attempt_count": deprecated_count,
        "payload_logged": False,
        "raw_network_identity_logged": False,
    }


def write_logs(tmp_path: Path, *, unattributed_client: str = CLIENT) -> tuple[Path, Path]:
    api_log = tmp_path / "api.log"
    renderer_log = tmp_path / "renderer.log"
    api_log.write_text(
        json.dumps(
            telemetry_event(
                service="video-factory-v1-api",
                route="/api/v1/video-jobs/{job_id}",
                action="legacy_read",
                method="GET",
                status_code=404,
                caller="ah-t01-smoke",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    renderer_events = [
        telemetry_event(
            service="video-factory-v1-renderer",
            route="/render",
            action="legacy_render",
            method="POST",
            status_code=422,
            caller="ah-t01-smoke",
            route_count=1,
            deprecated_count=1,
        ),
        telemetry_event(
            service="video-factory-v1-renderer",
            route="/media/{path}",
            action="legacy_media_read",
            method="GET",
            status_code=404,
            caller="ah-t01-smoke",
            route_count=1,
            deprecated_count=2,
        ),
        telemetry_event(
            service="video-factory-v1-renderer",
            route="/media/{path}",
            action="legacy_media_read",
            method="GET",
            status_code=404,
            caller=None,
            client=unattributed_client,
            route_count=2,
            deprecated_count=3,
        ),
    ]
    renderer_log.write_text(
        "".join(json.dumps(event) + "\n" for event in renderer_events), encoding="utf-8"
    )
    return api_log, renderer_log


def invoke(monkeypatch, api_log: Path, renderer_log: Path) -> int:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_deployment.py",
            "--api-log",
            str(api_log),
            "--renderer-log",
            str(renderer_log),
            "--raw-probe-marker",
            "ah-t01-raw-probe-test",
        ],
    )
    return main()


def test_verification_requires_all_paths_and_matching_unattributed_fingerprints(
    tmp_path, monkeypatch, capsys
) -> None:
    api_log, renderer_log = write_logs(tmp_path)
    assert invoke(monkeypatch, api_log, renderer_log) == 0
    report = json.loads(capsys.readouterr().out)
    assert set(report["path_coverage"].values()) == {"PASS"}
    assert report["unattributed_renderer_probe"] == {
        "status": "UNATTRIBUTED",
        "fingerprints_present": True,
        "owner_mapping_required_for_observation_acceptance": True,
    }


def test_verification_rejects_an_unrelated_unattributed_event(
    tmp_path, monkeypatch, capsys
) -> None:
    api_log, renderer_log = write_logs(
        tmp_path, unattributed_client="hmac-sha256:" + "c" * 24
    )
    assert invoke(monkeypatch, api_log, renderer_log) == 2
    assert "matching safe UNATTRIBUTED" in capsys.readouterr().err
