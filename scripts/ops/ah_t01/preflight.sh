#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
BASE_COMPOSE="${AH_T01_BASE_COMPOSE:-$ROOT_DIR/docker-compose.yml}"
OVERLAY_COMPOSE="${AH_T01_OVERLAY_COMPOSE:-$ROOT_DIR/deploy/ah-t01/docker-compose.telemetry.yml}"
EXPECTED_COMMIT="${AH_T01_EXPECTED_COMMIT:-}"
SALT_FILE="${AH_T01_TELEMETRY_SALT_HOST_FILE:-}"

fail() { printf 'AH-T01 preflight error: %s\n' "$*" >&2; exit 2; }

[[ "$EXPECTED_COMMIT" =~ ^[0-9a-f]{40}$ ]] || fail "AH_T01_EXPECTED_COMMIT must be a 40-character SHA"
[[ "$(git -C "$ROOT_DIR" rev-parse HEAD)" == "$EXPECTED_COMMIT" ]] || fail "repository commit does not match the approved SHA"
git -C "$ROOT_DIR" diff --quiet || fail "tracked working tree has unstaged changes"
git -C "$ROOT_DIR" diff --cached --quiet || fail "tracked working tree has staged changes"
[[ "$SALT_FILE" == /* && -f "$SALT_FILE" ]] || fail "telemetry salt must be an absolute regular file"

if mode="$(stat -c '%a' "$SALT_FILE" 2>/dev/null)"; then
  (( 8#$mode & 0077 )) && fail "telemetry salt permissions must be 0600 or stricter"
fi
salt_bytes="$(python3 - "$SALT_FILE" <<'PY'
from pathlib import Path
import sys
value = Path(sys.argv[1]).read_text(encoding="utf-8").strip()
print(len(value.encode("utf-8")))
PY
)"
(( salt_bytes >= 32 )) || fail "telemetry salt must contain at least 32 bytes"

docker compose version >/dev/null 2>&1 || fail "docker compose plugin is unavailable"
AH_T01_TELEMETRY_SALT_HOST_FILE="$SALT_FILE" \
  docker compose -f "$BASE_COMPOSE" -f "$OVERLAY_COMPOSE" config --quiet

redis_container_before="$(docker compose -f "$BASE_COMPOSE" ps -q redis)"
[[ -n "$redis_container_before" ]] || fail "V1 Redis container was not found"
[[ "$(docker inspect -f '{{.State.Running}}' "$redis_container_before")" == "true" ]] \
  || fail "V1 Redis is not running"
queue_length="$(docker exec "$redis_container_before" redis-cli -n 0 LLEN npd:video-jobs:queue | tr -d '\r')"
processing_length="$(docker exec "$redis_container_before" redis-cli -n 0 LLEN npd:video-jobs:processing | tr -d '\r')"
[[ "$queue_length" == "0" && "$processing_length" == "0" ]] \
  || fail "V1 queue or processing list is not empty"

for service in api worker renderer; do
  container_id="$(docker compose -f "$BASE_COMPOSE" ps -q "$service")"
  [[ -n "$container_id" ]] || fail "running V1 service not found: $service"
done

PHASE5_COMPOSE_FILE="${PHASE5_COMPOSE_FILE:-$ROOT_DIR/deploy/phase5/docker-compose.agent-hub.prod.yml}"
agent_hub_id="$(docker compose -f "$PHASE5_COMPOSE_FILE" ps -q agent-hub)"
[[ -n "$agent_hub_id" ]] || fail "running production Agent Hub was not found"

printf 'AH-T01 preflight ok: commit=%s queue=0 processing=0 salt_bytes=%s services=api,worker,renderer,agent-hub redis_unchanged_required=true\n' \
  "$EXPECTED_COMMIT" "$salt_bytes"
