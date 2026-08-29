#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
BASE_COMPOSE="${AH_T01_BASE_COMPOSE:-$ROOT_DIR/docker-compose.yml}"
OVERLAY_COMPOSE="${AH_T01_OVERLAY_COMPOSE:-$ROOT_DIR/deploy/ah-t01/docker-compose.telemetry.yml}"
PHASE5_COMPOSE_FILE="${PHASE5_COMPOSE_FILE:-$ROOT_DIR/deploy/phase5/docker-compose.agent-hub.prod.yml}"
RECEIPT_ROOT="${AH_T01_RECEIPT_ROOT:-/var/lib/npd-ai/ah-t01}"
EXPECTED_COMMIT=""
CONFIRM=""

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

bash "$ROOT_DIR/scripts/ops/ah_t01/preflight.sh"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
receipt_dir="$RECEIPT_ROOT/$timestamp"
mkdir -p "$receipt_dir/config"
chmod 700 "$receipt_dir" "$receipt_dir/config"

v1_container() { docker compose -f "$BASE_COMPOSE" ps -q "$1"; }
agent_hub_container() { docker compose -f "$PHASE5_COMPOSE_FILE" ps -q agent-hub; }
image_id() { docker inspect -f '{{.Image}}' "$1"; }
image_ref() { docker inspect -f '{{.Config.Image}}' "$1"; }

api_before="$(v1_container api)"
worker_before="$(v1_container worker)"
renderer_before="$(v1_container renderer)"
agent_hub_before="$(agent_hub_container)"
redis_container_before="$(v1_container redis)"

api_image_before="$(image_id "$api_before")"; api_ref="$(image_ref "$api_before")"
worker_image_before="$(image_id "$worker_before")"; worker_ref="$(image_ref "$worker_before")"
renderer_image_before="$(image_id "$renderer_before")"; renderer_ref="$(image_ref "$renderer_before")"
agent_hub_image_before="$(image_id "$agent_hub_before")"; agent_hub_ref="$(image_ref "$agent_hub_before")"

for ref in "$api_ref" "$worker_ref" "$renderer_ref" "$agent_hub_ref"; do
  [[ "$ref" =~ ^[A-Za-z0-9._/@:-]+$ ]] || { printf 'AH-T01 deploy error: unsafe image reference\n' >&2; exit 2; }
done

cp -- "$BASE_COMPOSE" "$receipt_dir/config/docker-compose.yml"
cp -- "$OVERLAY_COMPOSE" "$receipt_dir/config/docker-compose.telemetry.yml"
cp -- "$PHASE5_COMPOSE_FILE" "$receipt_dir/config/docker-compose.agent-hub.prod.yml"
if [[ -f "$ROOT_DIR/.env" ]]; then cp -- "$ROOT_DIR/.env" "$receipt_dir/config/v1.env"; fi
if [[ -f "${AGENT_HUB_ENV_FILE:-/etc/npd-ai/agent-hub.env}" ]]; then
  cp -- "${AGENT_HUB_ENV_FILE:-/etc/npd-ai/agent-hub.env}" "$receipt_dir/config/agent-hub.env"
fi
find "$receipt_dir/config" -type f -exec chmod 600 {} +
sha256sum "$receipt_dir"/config/* > "$receipt_dir/config.sha256"

rollback_on_failure() {
  exit_code=$?
  if [[ $exit_code -eq 0 ]]; then return; fi
  printf 'AH-T01 deploy failed; restoring the four previous image identities\n' >&2
  docker tag "$api_image_before" "$api_ref" || true
  docker tag "$worker_image_before" "$worker_ref" || true
  docker tag "$renderer_image_before" "$renderer_ref" || true
  docker tag "$agent_hub_image_before" "$agent_hub_ref" || true
  docker compose -f "$BASE_COMPOSE" up -d --no-deps --force-recreate api worker renderer || true
  docker compose -f "$PHASE5_COMPOSE_FILE" up -d --no-deps --force-recreate agent-hub || true
  exit "$exit_code"
}
trap rollback_on_failure EXIT

AH_T01_TELEMETRY_SALT_HOST_FILE="$AH_T01_TELEMETRY_SALT_HOST_FILE" \
  docker compose -f "$BASE_COMPOSE" -f "$OVERLAY_COMPOSE" build api worker renderer
docker compose -f "$PHASE5_COMPOSE_FILE" build agent-hub

AH_T01_TELEMETRY_SALT_HOST_FILE="$AH_T01_TELEMETRY_SALT_HOST_FILE" \
  docker compose -f "$BASE_COMPOSE" -f "$OVERLAY_COMPOSE" up -d --no-deps --force-recreate api worker renderer
docker compose -f "$PHASE5_COMPOSE_FILE" up -d --no-deps --force-recreate agent-hub

for _ in $(seq 1 30); do
  curl --fail --silent http://127.0.0.1:8000/readyz >/dev/null \
    && curl --fail --silent http://127.0.0.1:3001/healthz >/dev/null \
    && curl --fail --silent http://127.0.0.1:8010/readyz >/dev/null \
    && break
  sleep 2
done
curl --fail --silent http://127.0.0.1:8000/readyz >/dev/null
curl --fail --silent http://127.0.0.1:3001/healthz >/dev/null
curl --fail --silent http://127.0.0.1:8010/readyz >/dev/null

raw_probe_marker="ah-t01-raw-probe-$timestamp"
api_code="$(curl --silent --output /dev/null --write-out '%{http_code}' \
  -H 'X-NPD-Caller-ID: ah-t01-smoke' -H "User-Agent: $raw_probe_marker" \
  http://127.0.0.1:8000/api/v1/video-jobs/ah-t01-smoke-missing)"
renderer_code="$(curl --silent --output /dev/null --write-out '%{http_code}' \
  -H 'X-NPD-Caller-ID: ah-t01-smoke' -H "User-Agent: $raw_probe_marker" \
  http://127.0.0.1:3001/media/jobs/ah-t01-smoke-missing/final.mp4)"
[[ "$api_code" == "404" && "$renderer_code" == "404" ]] \
  || { printf 'AH-T01 deploy error: mock-only read probes did not return 404\n' >&2; exit 3; }

sleep 1
api_after="$(v1_container api)"; worker_after="$(v1_container worker)"; renderer_after="$(v1_container renderer)"
agent_hub_after="$(agent_hub_container)"
docker logs --since "$started_at" "$api_after" > "$receipt_dir/api.log" 2>&1
docker logs --since "$started_at" "$renderer_after" > "$receipt_dir/renderer.log" 2>&1
python3 "$ROOT_DIR/scripts/ops/ah_t01/verify_deployment.py" \
  --api-log "$receipt_dir/api.log" \
  --renderer-log "$receipt_dir/renderer.log" \
  --raw-probe-marker "$raw_probe_marker" > "$receipt_dir/telemetry-verification.json"
rm -f "$receipt_dir/api.log" "$receipt_dir/renderer.log"

redis_container_after="$(v1_container redis)"
[[ "$redis_container_after" == "$redis_container_before" ]] \
  || { printf 'AH-T01 deploy error: V1 Redis container identity changed\n' >&2; exit 3; }

verified_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
python3 - "$receipt_dir/deployment-receipt.json" <<PY
import json
from pathlib import Path

payload = {
    "schema_version": "1.0",
    "status": "PASS",
    "change_id": "AH-T01",
    "started_at": "$started_at",
    "verified_at": "$verified_at",
    "observation_window_start": "$verified_at",
    "git_commit": "$EXPECTED_COMMIT",
    "services_recreated": ["api", "worker", "renderer", "agent-hub"],
    "previous_image_ids": {
        "api": "$api_image_before",
        "worker": "$worker_image_before",
        "renderer": "$renderer_image_before",
        "agent-hub": "$agent_hub_image_before",
    },
    "new_image_ids": {
        "api": "$(image_id "$api_after")",
        "worker": "$(image_id "$worker_after")",
        "renderer": "$(image_id "$renderer_after")",
        "agent-hub": "$(image_id "$agent_hub_after")",
    },
    "redis_container_unchanged": True,
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
