"""Read-only exact host/topology/attempt bindings for Owner-fence rebind."""
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

# __SHARED_REPRESENTATION_SOURCE__

TARGET = "d61f0994a0c84d0ab4687211f0c15b077fb360a6241f7493b94b59f36341b344"
CONTROL = Path("/var/lib/npd-ai/agent-hub-deployments/phase9-owner-fence-rebind/attempts/91fda8b6-e9d1-49a2-9e66-156c16ef2835")
HOSTS = {
    "/etc/npd-ai/ga4-agent-hub-readonly.json": "36519be007706e8d0245c6cfef1ed2cf37ef992c2fc2dacdc4290d2fe6c895a7",
    "/etc/npd-ai/agent-attribution-verification-keys.json": "ea6346727e1237e078e45efd5e055b747aa506b01b0e38d9c0b6164afc157922",
}
EXPECTED_TOPOLOGY = "24947dc3fe36b785f9d4eca3b952d84ca1a47dbe6a32c89d80323a9489d0bd5a"

def run(argv):
    result = subprocess.run(argv, capture_output=True, timeout=20)
    if result.returncode or result.stderr:
        raise RuntimeError("READONLY_CHILD_FAILED")
    return result.stdout

try:
    assert not os.path.lexists(CONTROL)
    files = {}
    for name, expected in HOSTS.items():
        path = Path(name)
        assert path.is_file() and not path.is_symlink()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        with path.open("rb") as stream:
            observed = hashlib.file_digest(stream, "sha256").hexdigest()
        assert observed == expected
        files[name] = {"sha256": observed, "mode": "0600"}
    item = json.loads(run(["docker", "inspect", TARGET]))[0]
    assert item["Id"] == TARGET
    observed = semantic_topology_digest(item)
    assert observed == EXPECTED_TOPOLOGY
    print(json.dumps({"status": "PASS_HOST_TOPOLOGY_ATTEMPT_READONLY", "target": TARGET,
                      "topology_sha256": observed, "host_files": files,
                      "attempt_control_absent": True, "production_writes": 0}, sort_keys=True))
except Exception:
    print(json.dumps({"status": "HOLD_HOST_TOPOLOGY_ATTEMPT_READONLY", "production_writes": 0}))
    sys.exit(2)
