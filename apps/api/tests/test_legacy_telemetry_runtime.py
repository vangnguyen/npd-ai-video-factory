from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1]


def test_uvicorn_runtime_emits_parseable_events_from_real_http_middleware() -> None:
    """Exercise the real middleware under Uvicorn's actual logging hierarchy.

    A subprocess isolates ``dictConfig`` from pytest's own logging handlers. The
    default Uvicorn handler is retained; only its stream is redirected so the
    assertions inspect exactly what the production logger would emit.
    """

    probe = textwrap.dedent(
        r"""
        import io
        import json
        import logging
        import logging.config
        import tempfile
        from copy import deepcopy
        from pathlib import Path

        from fastapi.testclient import TestClient
        from uvicorn.config import LOGGING_CONFIG

        from app.config import settings
        from app.legacy_telemetry import LOGGER, LegacyTelemetry
        from app.main import app


        class HealthyRedis:
            async def ping(self):
                return True


        class MissingJobStore:
            async def get(self, _job_id):
                return None


        stream = io.StringIO()
        config = deepcopy(LOGGING_CONFIG)
        config["formatters"]["default"]["use_colors"] = False
        config["handlers"]["default"]["stream"] = stream
        logging.config.dictConfig(config)

        assert LOGGER.getEffectiveLevel() <= logging.INFO
        assert LOGGER.isEnabledFor(logging.INFO)
        assert LOGGER.hasHandlers()

        with tempfile.TemporaryDirectory() as temporary_root:
            settings.job_storage_root = Path(temporary_root) / "jobs"
            app.state.redis = HealthyRedis()
            app.state.job_store = MissingJobStore()
            app.state.legacy_telemetry = LegacyTelemetry(salt="runtime-test-salt-0123456789abcdef")

            client = TestClient(app)
            try:
                health = client.get(
                    "/healthz",
                    headers={"X-NPD-Caller-ID": "runtime-health", "User-Agent": "private-health-agent"},
                )
                ready = client.get(
                    "/readyz",
                    headers={"X-NPD-Caller-ID": "runtime-ready", "User-Agent": "private-ready-agent"},
                )
                missing = client.get(
                    "/api/v1/video-jobs/vid_runtime_missing",
                    headers={"X-NPD-Caller-ID": "runtime-missing", "User-Agent": "private-missing-agent"},
                )
            finally:
                client.close()

        assert health.status_code == 200
        assert ready.status_code == 200
        assert missing.status_code == 404

        rendered = stream.getvalue()
        assert "private-health-agent" not in rendered
        assert "private-ready-agent" not in rendered
        assert "private-missing-agent" not in rendered
        assert "runtime-test-salt" not in rendered

        events = []
        for line in rendered.splitlines():
            marker = line.find("{")
            if marker < 0:
                continue
            event = json.loads(line[marker:])
            if event.get("event") == "legacy_route_access":
                events.append(event)

        assert [(event["route"], event["status_code"]) for event in events] == [
            ("/healthz", 200),
            ("/readyz", 200),
            ("/api/v1/video-jobs/{job_id}", 404),
        ]
        assert all(event["payload_logged"] is False for event in events)
        assert all(event["raw_network_identity_logged"] is False for event in events)
        assert all(event["identity_ready"] is True for event in events)
        print(json.dumps(events, separators=(",", ":")))
        """
    )

    completed = subprocess.run(
        [sys.executable, "-c", probe],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=API_ROOT,
    )

    assert completed.returncode == 0, completed.stderr
    events = json.loads(completed.stdout)
    assert len(events) == 3
