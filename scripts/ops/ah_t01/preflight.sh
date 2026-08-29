#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
BASE_COMPOSE="${AH_T01_BASE_COMPOSE:-$ROOT_DIR/docker-compose.yml}"
OVERLAY_COMPOSE="${AH_T01_OVERLAY_COMPOSE:-$ROOT_DIR/deploy/ah-t01/docker-compose.telemetry.yml}"
EXPECTED_COMMIT="${AH_T01_EXPECTED_COMMIT:-}"
SALT_FILE="${AH_T01_TELEMETRY_SALT_HOST_FILE:-}"
SNAPSHOT_FILE="${AH_T01_PREFLIGHT_SNAPSHOT:-}"
PHASE5_COMPOSE_FILE="${PHASE5_COMPOSE_FILE:-$ROOT_DIR/deploy/phase5/docker-compose.agent-hub.prod.yml}"
CADDYFILE="${N8N_CADDYFILE:-/opt/n8n/Caddyfile}"
CADDY_CONTAINER="${N8N_CADDY_CONTAINER:-n8n-marketing-caddy-1}"
readonly DEPLOY_TARGETS=(api renderer)
readonly IMMUTABLE_TARGETS=(worker agent-hub redis)

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

v1_container() { docker compose -f "$BASE_COMPOSE" ps -q "$1"; }
agent_hub_container() { docker compose -f "$PHASE5_COMPOSE_FILE" ps -q agent-hub; }
image_id() { docker inspect -f '{{.Image}}' "$1"; }
network_membership_digest() {
  docker inspect -f '{{range $name, $config := .NetworkSettings.Networks}}{{println $name}}{{end}}' "$1" \
    | LC_ALL=C sort | sha256sum | awk '{print $1}'
}
port_bindings_digest() {
  docker inspect -f '{{json .HostConfig.PortBindings}}' "$1" | sha256sum | awk '{print $1}'
}
file_digest() { sha256sum -- "$1" | awk '{print $1}'; }
baseline_digest() { printf '%s\0' "$@" | sha256sum | awk '{print $1}'; }
agent_redis_url_digest() {
  local value
  value="$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$1" \
    | awk 'index($0,"AGENT_REDIS_URL=")==1 {print substr($0,17); found=1} END {if (!found) print "__UNSET__"}')"
  printf '%s' "$value" | sha256sum | awk '{print $1}'
}
agent_redis_url_present() {
  if docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$1" \
    | grep -q '^AGENT_REDIS_URL='; then
    printf 'true'
  else
    printf 'false'
  fi
}

redis_container_before="$(v1_container redis)"
[[ -n "$redis_container_before" ]] || fail "V1 Redis container was not found"
[[ "$(docker inspect -f '{{.State.Running}}' "$redis_container_before")" == "true" ]] \
  || fail "V1 Redis is not running"
queue_length="$(docker exec "$redis_container_before" redis-cli -n 0 LLEN npd:video-jobs:queue | tr -d '\r')"
processing_length="$(docker exec "$redis_container_before" redis-cli -n 0 LLEN npd:video-jobs:processing | tr -d '\r')"
[[ "$queue_length" == "0" && "$processing_length" == "0" ]] \
  || fail "V1 queue or processing list is not empty"

for service in "${DEPLOY_TARGETS[@]}" worker; do
  container_id="$(v1_container "$service")"
  [[ -n "$container_id" ]] || fail "running V1 service not found: $service"
  [[ "$(docker inspect -f '{{.State.Running}}' "$container_id")" == "true" ]] \
    || fail "V1 service is not running: $service"
done

api_id="$(v1_container api)"
renderer_id="$(v1_container renderer)"
worker_id="$(v1_container worker)"
agent_hub_id="$(agent_hub_container)"
[[ -n "$agent_hub_id" ]] || fail "running production Agent Hub was not found"
[[ "$(docker inspect -f '{{.State.Running}}' "$agent_hub_id")" == "true" ]] \
  || fail "production Agent Hub is not running"
[[ -f "$CADDYFILE" ]] || fail "host Caddyfile was not found"
caddy_container_id="$(docker inspect -f '{{.Id}}' "$CADDY_CONTAINER" 2>/dev/null)" \
  || fail "production Caddy container was not found"
[[ "$(docker inspect -f '{{.State.Running}}' "$caddy_container_id")" == "true" ]] \
  || fail "production Caddy is not running"

worker_image_id="$(image_id "$worker_id")"
agent_hub_image_id="$(image_id "$agent_hub_id")"
redis_image_id="$(image_id "$redis_container_before")"
caddy_image_id="$(image_id "$caddy_container_id")"
caddyfile_sha256="$(file_digest "$CADDYFILE")"
agent_redis_url_sha256="$(agent_redis_url_digest "$agent_hub_id")"
agent_redis_url_is_present="$(agent_redis_url_present "$agent_hub_id")"
api_networks_sha256="$(network_membership_digest "$api_id")"
renderer_networks_sha256="$(network_membership_digest "$renderer_id")"
api_ports_sha256="$(port_bindings_digest "$api_id")"
renderer_ports_sha256="$(port_bindings_digest "$renderer_id")"
caddy_networks_sha256="$(network_membership_digest "$caddy_container_id")"
caddy_ports_sha256="$(port_bindings_digest "$caddy_container_id")"
baseline_sha256="$(baseline_digest \
  "$api_id" "$renderer_id" "$worker_id" "$agent_hub_id" "$redis_container_before" \
  "$caddy_container_id" "$worker_image_id" "$agent_hub_image_id" "$redis_image_id" \
  "$caddy_image_id" "$queue_length" "$processing_length" "$agent_redis_url_is_present" \
  "$agent_redis_url_sha256" "$api_networks_sha256" "$renderer_networks_sha256" \
  "$api_ports_sha256" "$renderer_ports_sha256" "$caddyfile_sha256" \
  "$caddy_networks_sha256" "$caddy_ports_sha256")"

if [[ -n "$SNAPSHOT_FILE" ]]; then
  [[ "$SNAPSHOT_FILE" == /* ]] || fail "preflight snapshot path must be absolute"
  [[ -d "$(dirname "$SNAPSHOT_FILE")" ]] || fail "preflight snapshot parent does not exist"
  [[ ! -e "$SNAPSHOT_FILE" ]] || fail "preflight snapshot already exists"
  python3 - "$SNAPSHOT_FILE" <<PY
import json
import sys
from pathlib import Path

payload = {
    "schema_version": "1.0",
    "change_id": "AH-T01",
    "source_remediation": "AH-T01B",
    "status": "PASS",
    "git_commit": "$EXPECTED_COMMIT",
    "baseline_sha256": "$baseline_sha256",
    "deploy_targets": ["api", "renderer"],
    "rollback_targets": ["api", "renderer"],
    "immutable_targets": ["worker", "agent-hub", "redis"],
    "container_ids": {
        "api": "$api_id",
        "renderer": "$renderer_id",
        "worker": "$worker_id",
        "agent-hub": "$agent_hub_id",
        "redis": "$redis_container_before",
        "caddy": "$caddy_container_id",
    },
    "immutable_image_ids": {
        "worker": "$worker_image_id",
        "agent-hub": "$agent_hub_image_id",
        "redis": "$redis_image_id",
    },
    "queue_length": int("$queue_length"),
    "processing_length": int("$processing_length"),
    "agent_redis_url": {
        "configured": "$agent_redis_url_is_present" == "true",
        "sha256": "$agent_redis_url_sha256",
        "raw_value_recorded": False,
    },
    "topology_sha256": {
        "api_network_membership": "$api_networks_sha256",
        "renderer_network_membership": "$renderer_networks_sha256",
        "api_port_bindings": "$api_ports_sha256",
        "renderer_port_bindings": "$renderer_ports_sha256",
        "caddyfile": "$caddyfile_sha256",
        "caddy_network_membership": "$caddy_networks_sha256",
        "caddy_port_bindings": "$caddy_ports_sha256",
    },
    "caddy_baseline": {
        "container_id": "$caddy_container_id",
        "image_id": "$caddy_image_id",
        "host_config_sha256": "$caddyfile_sha256",
        "raw_config_recorded": False,
    },
    "network_change_allowed": False,
    "port_change_allowed": False,
    "caddy_change_allowed": False,
    "queue_or_processing_change_allowed": False,
}
Path(sys.argv[1]).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
  chmod 600 "$SNAPSHOT_FILE"
fi

printf 'AH-T01B preflight ok: commit=%s queue=0 processing=0 salt_bytes=%s deploy=api,renderer immutable=worker,agent-hub,redis\n' \
  "$EXPECTED_COMMIT" "$salt_bytes"
