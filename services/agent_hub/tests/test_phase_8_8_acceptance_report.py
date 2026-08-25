from datetime import datetime, timedelta, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SPEC = spec_from_file_location(
    "phase_8_8_acceptance_report",
    ROOT / "scripts/phase8/report-heartbeat-acceptance.py",
)
assert SPEC and SPEC.loader
REPORT = module_from_spec(SPEC)
SPEC.loader.exec_module(REPORT)


def test_acceptance_report_separates_heartbeat_from_lead_activity():
    now = datetime(2026, 8, 22, 16, 0, tzinfo=timezone.utc)
    heartbeats = [
        {
            "producer": "n8n_lead_intake",
            "received_at": (now - timedelta(minutes=offset)).isoformat(),
        }
        for offset in (10, 5, 0)
    ]
    status = {
        "latest_snapshot": {
            "providers": [
                {
                    "provider": "n8n_lead_intake",
                    "freshness_evidence": "heartbeat",
                    "freshness_state": "fresh",
                    "heartbeat_age_minutes": 0,
                    "activity_age_minutes": 90,
                    "target_minutes": 15,
                }
            ]
        },
        "external_notifications_enabled": False,
        "production_write_enabled": False,
    }
    scheduler = {
        "enabled": True,
        "state": "idle",
        "interval_seconds": 300,
        "run_count": 3,
        "skipped_lease_count": 0,
        "last_finished_at": now.isoformat(),
        "evaluates_cached_state_only": True,
    }

    report = REPORT.build_report(
        now=now,
        window_hours=48,
        interval_seconds=300,
        heartbeats=heartbeats,
        alerts=[],
        provider_status=status,
        scheduler=scheduler,
        redis_baseline_bytes=1000,
        redis_current_bytes=1300,
    )

    assert report["window_complete"] is False
    assert report["heartbeat"]["count"] == 3
    assert report["heartbeat"]["success_rate_percent"] == 100
    assert report["heartbeat"]["max_gap_seconds"] == 300
    assert report["lead_activity"]["pipeline_alive_without_new_lead"] is True
    assert report["redis"]["growth_bytes"] == 300
    assert report["safety"]["production_write_enabled"] is False
