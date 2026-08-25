#!/usr/bin/env bash
set -euo pipefail

N8N_IMAGE="${N8N_IMAGE:-docker.n8n.io/n8nio/n8n:2.33.7}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
WORKFLOW_DIR="${REPO_ROOT}/workflows/n8n"

python3 - "${WORKFLOW_DIR}" <<'PY'
import json
import pathlib
import re
import sys

workflow_dir = pathlib.Path(sys.argv[1])
files = sorted(workflow_dir.glob("*.json"))
if not files:
    raise SystemExit("No n8n workflow JSON files found")

seen_ids: set[str] = set()
uuid_pattern = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
for path in files:
    workflow = json.loads(path.read_text(encoding="utf-8"))
    workflow_id = workflow.get("id", "")
    if not uuid_pattern.fullmatch(workflow_id):
        raise SystemExit(f"{path.name}: workflow id must be a UUID")
    if workflow_id in seen_ids:
        raise SystemExit(f"{path.name}: duplicate workflow id {workflow_id}")
    seen_ids.add(workflow_id)
    if workflow.get("active") is not False:
        raise SystemExit(f"{path.name}: source-controlled workflow must be inactive")
    serialized = json.dumps(workflow, ensure_ascii=False).lower()
    forbidden = ("access_token", "client_secret", "private_key", "bearer ey")
    if any(marker in serialized for marker in forbidden):
        raise SystemExit(f"{path.name}: possible inline credential material")

heartbeat = json.loads(
    (workflow_dir / "phase-8-8-lead-intake-heartbeat.json").read_text(encoding="utf-8")
)
triggers = [
    node
    for node in heartbeat.get("nodes", [])
    if node.get("type") == "n8n-nodes-base.executeWorkflowTrigger"
]
if len(triggers) != 1 or triggers[0].get("parameters", {}).get("inputSource") != "passthrough":
    raise SystemExit("Phase 8.8 heartbeat internal trigger must use inputSource=passthrough")

print(f"Static validation passed for {len(files)} n8n workflows")
PY

docker run --rm \
  --user root \
  --env N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS=false \
  --volume "${WORKFLOW_DIR}:/workflows:ro" \
  --entrypoint sh \
  "${N8N_IMAGE}" \
  -lc 'set -eu
    n8n import:workflow --separate --input=/workflows --activeState=false
    listed="$(n8n list:workflow)"
    printf "%s\n" "$listed"
    printf "%s\n" "$listed" | grep -F "8d29fc5a-3477-4e52-9cc7-23dd54ecbdf7|NPD Agent Hub - Approved Action Executor"
    printf "%s\n" "$listed" | grep -F "fd262c48-24c0-4ee3-a20a-09f2a417de88|NPD Phase 8.8 - Lead Intake Heartbeat"
    printf "%s\n" "$listed" | grep -F "019ffe50-ec05-7b13-b722-08bbb5e8482b|NPD AI Video Factory - Sprint 1 Smoke Test"'

echo "n8n 2.33.7 import validation passed"
