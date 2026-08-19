#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="${PHASE5_COMPOSE_FILE:-$ROOT_DIR/deploy/phase5/docker-compose.agent-hub.prod.yml}"
ENV_FILE="${AGENT_HUB_ENV_FILE:-/etc/npd-ai/agent-hub.env}"
BACKUP_DIR="${AGENT_HUB_BACKUP_DIR:-/var/backups/npd-agent-hub}"
TIMESTAMP="${PHASE5_TIMESTAMP:-$(date -u +%Y%m%dT%H%M%SZ)}"
OUTPUT="${1:-$BACKUP_DIR/agent-hub-$TIMESTAMP.json}"

[[ -f "$ENV_FILE" ]] || { printf 'backup error: env file not found: %s\n' "$ENV_FILE" >&2; exit 2; }
mkdir -p "$(dirname "$OUTPUT")"

export AGENT_HUB_ENV_FILE="$ENV_FILE"
container_id="$(docker compose -f "$COMPOSE_FILE" ps -q agent-hub 2>/dev/null || true)"
[[ -n "$container_id" ]] || { printf 'backup error: Agent Hub is not currently deployed\n' >&2; exit 3; }

running="$(docker inspect -f '{{.State.Running}}' "$container_id")"
[[ "$running" == "true" ]] || { printf 'backup error: Agent Hub container is not running\n' >&2; exit 3; }

docker compose -f "$COMPOSE_FILE" exec -T agent-hub \
  python -m npd_agent_hub.maintenance backup --output - > "$OUTPUT"
chmod 600 "$OUTPUT"

python3 - "$OUTPUT" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding='utf-8'))
assert payload.get('version') == 1
assert isinstance(payload.get('items'), list)
print(f"backup ok: path={sys.argv[1]} namespace={payload.get('namespace')} keys={payload.get('key_count')}")
PY
