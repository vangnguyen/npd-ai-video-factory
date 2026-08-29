#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
BASE_COMPOSE="${AH_T01_BASE_COMPOSE:-$ROOT_DIR/docker-compose.yml}"
OVERLAY_COMPOSE="${AH_T01_OVERLAY_COMPOSE:-$ROOT_DIR/deploy/ah-t01/docker-compose.telemetry.yml}"
PHASE5_COMPOSE_FILE="${PHASE5_COMPOSE_FILE:-$ROOT_DIR/deploy/phase5/docker-compose.agent-hub.prod.yml}"
CADDYFILE="${N8N_CADDYFILE:-/opt/n8n/Caddyfile}"
CADDY_CONTAINER="${N8N_CADDY_CONTAINER:-n8n-marketing-caddy-1}"
RECEIPT_ROOT="${AH_T01_RECEIPT_ROOT:-/var/lib/npd-ai/ah-t01}"
EXPECTED_COMMIT=""
CONFIRM=""
readonly DEPLOY_TARGETS=(api renderer)
readonly ROLLBACK_TARGETS=(api renderer)
readonly FORBIDDEN_TARGETS=(worker agent-hub redis)

usage() {
  printf 'Usage: bash scripts/ops/ah_t01/deploy.sh --expected-commit <sha> --confirm DEPLOY_AH_T01_TELEMETRY\n' >&2
  exit 2
}

while (($#)); do
  case "$1" in
    --expected-commit) EXPECTED_COMMIT="${2:-}"; shift 2 ;;
    --confirm) CONFIRM="${2:-}"; shift 2 ;;
    *) usage ;;
  esac
done

[[ "$CONFIRM" == "DEPLOY_AH_T01_TELEMETRY" ]] || usage
[[ "$EXPECTED_COMMIT" =~ ^[0-9a-f]{40}$ ]] || usage
export AH_T01_EXPECTED_COMMIT="$EXPECTED_COMMIT"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
receipt_dir="$RECEIPT_ROOT/$timestamp"
mkdir -p "$receipt_dir/config"
chmod 700 "$receipt_dir" "$receipt_dir/config"
AH_T01_PREFLIGHT_SNAPSHOT="$receipt_dir/preflight-baseline.json" \
  bash "$ROOT_DIR/scripts/ops/ah_t01/preflight.sh"

v1_container() { docker compose -f "$BASE_COMPOSE" ps -q "$1"; }
agent_hub_container() { docker compose -f "$PHASE5_COMPOSE_FILE" ps -q agent-hub; }
image_id() { docker inspect -f '{{.Image}}' "$1"; }
image_ref() { docker inspect -f '{{.Config.Image}}' "$1"; }
container_running() { docker inspect -f '{{.State.Running}}' "$1"; }
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
queue_length() { docker exec "$1" redis-cli -n 0 LLEN npd:video-jobs:queue | tr -d '\r'; }
processing_length() { docker exec "$1" redis-cli -n 0 LLEN npd:video-jobs:processing | tr -d '\r'; }
api_renderer_ready() {
  curl --fail --silent http://127.0.0.1:8000/readyz >/dev/null \
    && curl --fail --silent http://127.0.0.1:3001/healthz >/dev/null
}
wait_for_api_renderer_ready() {
  local attempt
  for attempt in $(seq 1 30); do
    if api_renderer_ready; then return 0; fi
    sleep 2
  done
  return 1
}
rollback_images_restored() {
  local api_current renderer_current api_current_image renderer_current_image
  api_current="$(v1_container api)" || return 1
  renderer_current="$(v1_container renderer)" || return 1
  api_current_image="$(image_id "$api_current")" || return 1
  renderer_current_image="$(image_id "$renderer_current")" || return 1
  [[ "$(container_running "$api_current")" == "true" \
    && "$(container_running "$renderer_current")" == "true" \
    && "$api_current_image" == "$api_image_before" \
    && "$renderer_current_image" == "$renderer_image_before" ]]
}

api_before="$(v1_container api)"
worker_before="$(v1_container worker)"
renderer_before="$(v1_container renderer)"
agent_hub_before="$(agent_hub_container)"
redis_container_before="$(v1_container redis)"
caddy_container_before="$(docker inspect -f '{{.Id}}' "$CADDY_CONTAINER")"

api_image_before="$(image_id "$api_before")"; api_ref="$(image_ref "$api_before")"
renderer_image_before="$(image_id "$renderer_before")"; renderer_ref="$(image_ref "$renderer_before")"
worker_image_before="$(image_id "$worker_before")"
agent_hub_image_before="$(image_id "$agent_hub_before")"
redis_image_before="$(image_id "$redis_container_before")"
caddy_image_before="$(image_id "$caddy_container_before")"
caddyfile_sha256_before="$(file_digest "$CADDYFILE")"
agent_redis_url_sha256_before="$(agent_redis_url_digest "$agent_hub_before")"
agent_redis_url_present_before="$(agent_redis_url_present "$agent_hub_before")"
queue_length_before="$(queue_length "$redis_container_before")"
processing_length_before="$(processing_length "$redis_container_before")"
api_networks_before="$(network_membership_digest "$api_before")"
renderer_networks_before="$(network_membership_digest "$renderer_before")"
api_ports_before="$(port_bindings_digest "$api_before")"
renderer_ports_before="$(port_bindings_digest "$renderer_before")"
caddy_networks_before="$(network_membership_digest "$caddy_container_before")"
caddy_ports_before="$(port_bindings_digest "$caddy_container_before")"
preflight_baseline_sha256="$(python3 - "$receipt_dir/preflight-baseline.json" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
value = payload.get("baseline_sha256")
if not isinstance(value, str):
    raise SystemExit("preflight baseline digest is missing")
print(value)
PY
)"
deploy_baseline_sha256="$(baseline_digest \
  "$api_before" "$renderer_before" "$worker_before" "$agent_hub_before" "$redis_container_before" \
  "$caddy_container_before" "$worker_image_before" "$agent_hub_image_before" "$redis_image_before" \
  "$caddy_image_before" "$queue_length_before" "$processing_length_before" \
  "$agent_redis_url_present_before" "$agent_redis_url_sha256_before" "$api_networks_before" \
  "$renderer_networks_before" "$api_ports_before" "$renderer_ports_before" \
  "$caddyfile_sha256_before" "$caddy_networks_before" "$caddy_ports_before")"

for ref in "$api_ref" "$renderer_ref"; do
  [[ "$ref" =~ ^[A-Za-z0-9._/@:-]+$ ]] || { printf 'AH-T01 deploy error: unsafe image reference\n' >&2; exit 2; }
done
[[ "$queue_length_before" == "0" && "$processing_length_before" == "0" ]] \
  || { printf 'AH-T01 deploy error: queue/processing changed after preflight\n' >&2; exit 3; }
[[ "$deploy_baseline_sha256" == "$preflight_baseline_sha256" ]] \
  || { printf 'AH-T01 deploy error: runtime baseline changed after preflight\n' >&2; exit 3; }

cp -- "$BASE_COMPOSE" "$receipt_dir/config/docker-compose.yml"
cp -- "$OVERLAY_COMPOSE" "$receipt_dir/config/docker-compose.telemetry.yml"
if [[ -f "$ROOT_DIR/.env" ]]; then cp -- "$ROOT_DIR/.env" "$receipt_dir/config/v1.env"; fi
find "$receipt_dir/config" -type f -exec chmod 600 {} +
sha256sum "$receipt_dir"/config/* > "$receipt_dir/config.sha256"

rollback_on_failure() {
  local exit_code=$?
  local rollback_ok=true
  trap - EXIT
  if [[ $exit_code -eq 0 ]]; then return; fi
  printf 'AH-T01 deploy failed; restoring only the previous API and renderer image identities\n' >&2
  docker tag "$api_image_before" "$api_ref" || rollback_ok=false
  docker tag "$renderer_image_before" "$renderer_ref" || rollback_ok=false
  docker compose -f "$BASE_COMPOSE" up -d --no-deps --force-recreate "${ROLLBACK_TARGETS[@]}" \
    || rollback_ok=false
  if [[ "$rollback_ok" == "true" ]] && ! wait_for_api_renderer_ready; then
    printf 'AH-T01 rollback health/readiness verification failed after bounded wait\n' >&2
    rollback_ok=false
  fi
  if [[ "$rollback_ok" == "true" ]] && ! rollback_images_restored; then
    printf 'AH-T01 rollback image identity verification failed\n' >&2
    rollback_ok=false
  fi
  if [[ "$rollback_ok" == "true" ]]; then
    printf 'AH-T01 rollback verified: API and renderer baseline images are healthy\n' >&2
  else
    printf 'AH-T01 rollback requires manual operator attention; immutable services were not restarted\n' >&2
  fi
  exit "$exit_code"
}
trap rollback_on_failure EXIT

AH_T01_TELEMETRY_SALT_HOST_FILE="$AH_T01_TELEMETRY_SALT_HOST_FILE" \
  docker compose -f "$BASE_COMPOSE" -f "$OVERLAY_COMPOSE" build "${DEPLOY_TARGETS[@]}"

AH_T01_TELEMETRY_SALT_HOST_FILE="$AH_T01_TELEMETRY_SALT_HOST_FILE" \
  docker compose -f "$BASE_COMPOSE" -f "$OVERLAY_COMPOSE" up -d --no-deps --force-recreate "${DEPLOY_TARGETS[@]}"

wait_for_api_renderer_ready \
  || { printf 'AH-T01 deploy error: API/renderer readiness timed out\n' >&2; exit 3; }

raw_probe_marker="ah-t01-raw-probe-$timestamp"
api_code="$(curl --silent --output /dev/null --write-out '%{http_code}' \
  -H 'X-NPD-Caller-ID: ah-t01-smoke' -H "User-Agent: $raw_probe_marker" \
  http://127.0.0.1:8000/api/v1/video-jobs/ah-t01-smoke-missing)"
renderer_render_code="$(curl --silent --output /dev/null --write-out '%{http_code}' \
  -X POST -H 'Content-Type: application/json' \
  -H 'X-NPD-Caller-ID: ah-t01-smoke' -H "User-Agent: $raw_probe_marker" \
  --data '{}' http://127.0.0.1:3001/render)"
renderer_media_code="$(curl --silent --output /dev/null --write-out '%{http_code}' \
  -H 'X-NPD-Caller-ID: ah-t01-smoke' -H "User-Agent: $raw_probe_marker" \
  http://127.0.0.1:3001/media/jobs/ah-t01-smoke-missing/final.mp4)"
renderer_unattributed_code="$(curl --silent --output /dev/null --write-out '%{http_code}' \
  -H "User-Agent: $raw_probe_marker" \
  http://127.0.0.1:3001/media/jobs/ah-t01-unattributed-missing/final.mp4)"
[[ "$api_code" == "404" && "$renderer_render_code" == "422" \
  && "$renderer_media_code" == "404" && "$renderer_unattributed_code" == "404" ]] \
  || { printf 'AH-T01 deploy error: telemetry-only probes returned unexpected status codes\n' >&2; exit 3; }

sleep 1
api_after="$(v1_container api)"
renderer_after="$(v1_container renderer)"
worker_after="$(v1_container worker)"
agent_hub_after="$(agent_hub_container)"
redis_container_after="$(v1_container redis)"
caddy_container_after="$(docker inspect -f '{{.Id}}' "$CADDY_CONTAINER")"

worker_image_after="$(image_id "$worker_after")"
agent_hub_image_after="$(image_id "$agent_hub_after")"
redis_image_after="$(image_id "$redis_container_after")"
caddy_image_after="$(image_id "$caddy_container_after")"
caddyfile_sha256_after="$(file_digest "$CADDYFILE")"
agent_redis_url_sha256_after="$(agent_redis_url_digest "$agent_hub_after")"
agent_redis_url_present_after="$(agent_redis_url_present "$agent_hub_after")"
queue_length_after="$(queue_length "$redis_container_after")"
processing_length_after="$(processing_length "$redis_container_after")"
api_networks_after="$(network_membership_digest "$api_after")"
renderer_networks_after="$(network_membership_digest "$renderer_after")"
api_ports_after="$(port_bindings_digest "$api_after")"
renderer_ports_after="$(port_bindings_digest "$renderer_after")"
caddy_networks_after="$(network_membership_digest "$caddy_container_after")"
caddy_ports_after="$(port_bindings_digest "$caddy_container_after")"

[[ "$worker_after" == "$worker_before" ]] \
  || { printf 'AH-T01 deploy error: worker container identity changed\n' >&2; exit 3; }
[[ "$worker_image_after" == "$worker_image_before" ]] \
  || { printf 'AH-T01 deploy error: worker image identity changed\n' >&2; exit 3; }
[[ "$agent_hub_after" == "$agent_hub_before" ]] \
  || { printf 'AH-T01 deploy error: Agent Hub container identity changed\n' >&2; exit 3; }
[[ "$agent_hub_image_after" == "$agent_hub_image_before" ]] \
  || { printf 'AH-T01 deploy error: Agent Hub image identity changed\n' >&2; exit 3; }
[[ "$redis_container_after" == "$redis_container_before" ]] \
  || { printf 'AH-T01 deploy error: V1 Redis container identity changed\n' >&2; exit 3; }
[[ "$redis_image_after" == "$redis_image_before" ]] \
  || { printf 'AH-T01 deploy error: V1 Redis image identity changed\n' >&2; exit 3; }
[[ "$caddy_container_after" == "$caddy_container_before" \
  && "$caddy_image_after" == "$caddy_image_before" \
  && "$caddyfile_sha256_after" == "$caddyfile_sha256_before" ]] \
  || { printf 'AH-T01 deploy error: Caddy identity or configuration changed\n' >&2; exit 3; }
[[ "$(container_running "$worker_after")" == "true" \
  && "$(container_running "$agent_hub_after")" == "true" \
  && "$(container_running "$redis_container_after")" == "true" \
  && "$(container_running "$caddy_container_after")" == "true" ]] \
  || { printf 'AH-T01 deploy error: an immutable service or Caddy is not running\n' >&2; exit 3; }
[[ "$agent_redis_url_sha256_after" == "$agent_redis_url_sha256_before" \
  && "$agent_redis_url_present_after" == "$agent_redis_url_present_before" ]] \
  || { printf 'AH-T01 deploy error: AGENT_REDIS_URL fingerprint changed\n' >&2; exit 3; }
[[ "$queue_length_after" == "$queue_length_before" \
  && "$processing_length_after" == "$processing_length_before" ]] \
  || { printf 'AH-T01 deploy error: V1 queue/processing state changed\n' >&2; exit 3; }
[[ "$api_networks_after" == "$api_networks_before" \
  && "$renderer_networks_after" == "$renderer_networks_before" \
  && "$caddy_networks_after" == "$caddy_networks_before" ]] \
  || { printf 'AH-T01 deploy error: API/renderer/Caddy network membership changed\n' >&2; exit 3; }
[[ "$api_ports_after" == "$api_ports_before" \
  && "$renderer_ports_after" == "$renderer_ports_before" \
  && "$caddy_ports_after" == "$caddy_ports_before" ]] \
  || { printf 'AH-T01 deploy error: API/renderer/Caddy port bindings changed\n' >&2; exit 3; }

docker logs --since "$started_at" "$api_after" > "$receipt_dir/api.log" 2>&1
docker logs --since "$started_at" "$renderer_after" > "$receipt_dir/renderer.log" 2>&1
python3 "$ROOT_DIR/scripts/ops/ah_t01/verify_deployment.py" \
  --api-log "$receipt_dir/api.log" \
  --renderer-log "$receipt_dir/renderer.log" \
  --raw-probe-marker "$raw_probe_marker" > "$receipt_dir/telemetry-verification.json"
rm -f "$receipt_dir/api.log" "$receipt_dir/renderer.log"

verified_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
python3 - "$receipt_dir/deployment-receipt.json" <<PY
import json
from pathlib import Path

payload = {
    "schema_version": "1.0",
    "status": "PASS",
    "change_id": "AH-T01",
    "source_remediation": "AH-T01B",
    "started_at": "$started_at",
    "verified_at": "$verified_at",
    "observation_window_start": "$verified_at",
    "git_commit": "$EXPECTED_COMMIT",
    "preflight_baseline_sha256": "$preflight_baseline_sha256",
    "preflight_baseline_match": True,
    "services_recreated": ["api", "renderer"],
    "rollback_targets": ["api", "renderer"],
    "forbidden_services_recreated": [],
    "previous_image_ids": {
        "api": "$api_image_before",
        "renderer": "$renderer_image_before",
    },
    "new_image_ids": {
        "api": "$(image_id "$api_after")",
        "renderer": "$(image_id "$renderer_after")",
    },
    "immutable_service_evidence": {
        "worker": {
            "container_id_before": "$worker_before",
            "container_id_after": "$worker_after",
            "image_id_before": "$worker_image_before",
            "image_id_after": "$worker_image_after",
            "container_unchanged": True,
            "image_unchanged": True,
        },
        "agent-hub": {
            "container_id_before": "$agent_hub_before",
            "container_id_after": "$agent_hub_after",
            "image_id_before": "$agent_hub_image_before",
            "image_id_after": "$agent_hub_image_after",
            "container_unchanged": True,
            "image_unchanged": True,
        },
        "redis": {
            "container_id_before": "$redis_container_before",
            "container_id_after": "$redis_container_after",
            "image_id_before": "$redis_image_before",
            "image_id_after": "$redis_image_after",
            "container_unchanged": True,
            "image_unchanged": True,
        },
    },
    "queue_processing_evidence": {
        "queue_before": int("$queue_length_before"),
        "queue_after": int("$queue_length_after"),
        "processing_before": int("$processing_length_before"),
        "processing_after": int("$processing_length_after"),
        "unchanged": True,
    },
    "agent_redis_url_evidence": {
        "configured": "$agent_redis_url_present_before" == "true",
        "sha256_before": "$agent_redis_url_sha256_before",
        "sha256_after": "$agent_redis_url_sha256_after",
        "unchanged": True,
        "raw_value_recorded": False,
    },
    "topology_evidence": {
        "api_network_membership_sha256_before": "$api_networks_before",
        "api_network_membership_sha256_after": "$api_networks_after",
        "renderer_network_membership_sha256_before": "$renderer_networks_before",
        "renderer_network_membership_sha256_after": "$renderer_networks_after",
        "api_port_bindings_sha256_before": "$api_ports_before",
        "api_port_bindings_sha256_after": "$api_ports_after",
        "renderer_port_bindings_sha256_before": "$renderer_ports_before",
        "renderer_port_bindings_sha256_after": "$renderer_ports_after",
        "caddy_container_id_before": "$caddy_container_before",
        "caddy_container_id_after": "$caddy_container_after",
        "caddy_image_id_before": "$caddy_image_before",
        "caddy_image_id_after": "$caddy_image_after",
        "caddyfile_sha256_before": "$caddyfile_sha256_before",
        "caddyfile_sha256_after": "$caddyfile_sha256_after",
        "caddy_network_membership_sha256_before": "$caddy_networks_before",
        "caddy_network_membership_sha256_after": "$caddy_networks_after",
        "caddy_port_bindings_sha256_before": "$caddy_ports_before",
        "caddy_port_bindings_sha256_after": "$caddy_ports_after",
        "caddy_running_after": True,
        "networks_unchanged": True,
        "ports_unchanged": True,
        "caddy_unchanged": True,
    },
    "production_service_recreate_performed": True,
    "production_business_write_performed": False,
    "write_blocking_enabled": False,
    "ports_changed": False,
    "routes_changed": False,
    "traffic_switched": False,
    "ah03_authorized": False,
}
Path("$receipt_dir/deployment-receipt.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
chmod 600 "$receipt_dir"/*.json "$receipt_dir"/*.sha256

trap - EXIT
printf 'AH-T01 deploy PASS: receipt=%s observation_window_start=%s production_business_write=false\n' \
  "$receipt_dir/deployment-receipt.json" "$verified_at"
