"""Read-only strict protected-service representation for the Owner-fence gate."""
import json
import re
import subprocess
import sys

# __SHARED_REPRESENTATION_SOURCE__

PROJECT = "npd-agent-hub-prod"
SERVICE = "agent-hub"
RELEVANT = re.compile("agent|redis|caddy|n8n|espo|wordpress|salehub|people|(?:^|[-_])hr(?:[-_]|$)|api|worker|renderer", re.I)

def read(argv):
    result = subprocess.run(argv, capture_output=True, timeout=30, check=False)
    if result.returncode or result.stderr:
        raise RuntimeError("DOCKER_READ_FAILED")
    return result.stdout

try:
    ids = read(["docker", "ps", "-q", "--no-trunc"]).decode("ascii").split()
    if not ids:
        raise RuntimeError("NO_RUNNING_SERVICES")
    items = json.loads(read(["docker", "inspect", *ids]))
    digest, count = strict_protected_digest(items, PROJECT, SERVICE, RELEVANT)
    if count != 18:
        raise RuntimeError("PROTECTED_COUNT_DRIFT")
    print(json.dumps({"status": "PASS_STRICT_PROTECTED_READONLY", "protected_count": count,
                      "strict_protected_sha256": digest, "production_writes": 0}, sort_keys=True))
except Exception:
    print(json.dumps({"status": "HOLD_STRICT_PROTECTED_READONLY", "production_writes": 0}))
    sys.exit(2)
