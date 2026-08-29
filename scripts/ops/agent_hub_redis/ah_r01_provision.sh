#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
BASE_COMPOSE="${PHASE5_COMPOSE_FILE:-$ROOT_DIR/deploy/phase5/docker-compose.agent-hub.prod.yml}"
OVERLAY_COMPOSE="${AH_R01_OVERLAY_COMPOSE:-$ROOT_DIR/deploy/ah-r01/docker-compose.redis-independent.yml}"
V1_COMPOSE="${V1_COMPOSE_FILE:-$ROOT_DIR/docker-compose.yml}"
RECEIPT_ROOT="${AH_R01_RECEIPT_ROOT:-/var/lib/npd-ai/ah-r01}"
TARGET_NETWORK="${AH_R01_REDIS_NETWORK_NAME:-npd-agent-hub-data}"
TARGET_VOLUME="${AH_R01_REDIS_VOLUME_NAME:-npd-agent-hub-redis-data}"
EXPECTED_COMMIT=""
CONFIRM=""

usage() {
  printf 'Usage: bash scripts/ops/agent_hub_redis/ah_r01_provision.sh --expected-commit <sha> --confirm PROVISION_AH_R01_REDIS\n' >&2
  exit 2
}

while (($#)); do
  case "$1" in
    --expected-commit) EXPECTED_COMMIT="${2:-}"; shift 2 ;;
    --confirm) CONFIRM="${2:-}"; shift 2 ;;
    *) usage ;;
  esac
done
[[ "$CONFIRM" == "PROVISION_AH_R01_REDIS" ]] || usage
[[ "$EXPECTED_COMMIT" =~ ^[0-9a-f]{40}$ ]] || usage
export AH_R01_EXPECTED_COMMIT="$EXPECTED_COMMIT"

bash "$ROOT_DIR/scripts/ops/agent_hub_redis/ah_r01_preflight.sh"

[[ "$RECEIPT_ROOT" == /* && "$RECEIPT_ROOT" != "/" ]] \
  || { printf 'AH-R01 provisioning error: receipt root must be a narrow absolute path\n' >&2; exit 2; }
case "$(realpath -m "$RECEIPT_ROOT")" in
  "$ROOT_DIR"|"$ROOT_DIR"/*) printf 'AH-R01 provisioning error: receipt root must be outside Git\n' >&2; exit 2 ;;
esac

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
receipt_dir="$RECEIPT_ROOT/provision-$timestamp"
mkdir -p "$receipt_dir"
chmod 700 "$receipt_dir"
cp -- "$BASE_COMPOSE" "$receipt_dir/docker-compose.agent-hub.prod.yml"
cp -- "$OVERLAY_COMPOSE" "$receipt_dir/docker-compose.redis-independent.yml"
chmod 600 "$receipt_dir"/*.yml
sha256sum "$receipt_dir"/*.yml > "$receipt_dir/config.sha256"

v1_redis_before="$(docker compose -f "$V1_COMPOSE" ps -q redis)"
agent_hub_before="$(docker compose -f "$BASE_COMPOSE" ps -q agent-hub)"
created=false

rollback_on_failure() {
  exit_code=$?
  if [[ $exit_code -eq 0 || "$created" != "true" ]]; then return; fi
  printf 'AH-R01 provisioning failed; removing only the newly labelled empty target resources\n' >&2
  target_id="$(AH_R01_REDIS_PASSWORD_HOST_FILE="$AH_R01_REDIS_PASSWORD_HOST_FILE" \
    docker compose -f "$BASE_COMPOSE" -f "$OVERLAY_COMPOSE" ps -aq agent-redis 2>/dev/null || true)"
  target_empty_for_cleanup=false
  if [[ -n "$target_id" && "$(docker inspect -f '{{.State.Running}}' "$target_id" 2>/dev/null || true)" == "true" ]]; then
    if [[ "$(docker exec "$target_id" sh -ec '
      REDISCLI_AUTH="$(tr -d "\r\n" < /run/secrets/agent_redis_password)"; export REDISCLI_AUTH
      redis-cli --no-auth-warning dbsize
    ' 2>/dev/null || true)" == "0" ]]; then
      target_empty_for_cleanup=true
    fi
  fi
  if [[ -n "$target_id" && "$(docker inspect -f '{{ index .Config.Labels "npd.change" }}' "$target_id" 2>/dev/null)" == "ah-r01" ]]; then
    AH_R01_REDIS_PASSWORD_HOST_FILE="$AH_R01_REDIS_PASSWORD_HOST_FILE" \
      docker compose -f "$BASE_COMPOSE" -f "$OVERLAY_COMPOSE" rm -sf agent-redis || true
  fi
  if [[ "$target_empty_for_cleanup" == "true" && "$(docker volume inspect -f '{{ index .Labels "npd.change" }}' "$TARGET_VOLUME" 2>/dev/null || true)" == "ah-r01" ]]; then
    docker volume rm "$TARGET_VOLUME" >/dev/null 2>&1 || true
  elif docker volume inspect "$TARGET_VOLUME" >/dev/null 2>&1; then
    printf 'AH-R01 rollback preserved the target volume because emptiness was not proven\n' >&2
  fi
  if [[ "$(docker network inspect -f '{{ index .Labels "npd.change" }}' "$TARGET_NETWORK" 2>/dev/null || true)" == "ah-r01" ]]; then
    docker network rm "$TARGET_NETWORK" >/dev/null 2>&1 || true
  fi
  exit "$exit_code"
}
trap rollback_on_failure EXIT

created=true
AH_R01_REDIS_PASSWORD_HOST_FILE="$AH_R01_REDIS_PASSWORD_HOST_FILE" \
  docker compose -f "$BASE_COMPOSE" -f "$OVERLAY_COMPOSE" \
  up -d --no-deps --pull never agent-redis
target_id="$(AH_R01_REDIS_PASSWORD_HOST_FILE="$AH_R01_REDIS_PASSWORD_HOST_FILE" \
  docker compose -f "$BASE_COMPOSE" -f "$OVERLAY_COMPOSE" ps -q agent-redis)"
[[ -n "$target_id" ]] || { printf 'AH-R01 provisioning error: target container missing\n' >&2; exit 3; }

for _ in $(seq 1 40); do
  [[ "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$target_id")" == "healthy" ]] && break
  sleep 1
done
[[ "$(docker inspect -f '{{.State.Health.Status}}' "$target_id")" == "healthy" ]] \
  || { printf 'AH-R01 provisioning error: target health failed\n' >&2; exit 3; }
[[ "$(docker inspect -f '{{json .HostConfig.PortBindings}}' "$target_id")" =~ ^(null|\{\})$ ]] \
  || { printf 'AH-R01 provisioning error: target has a host port binding\n' >&2; exit 3; }
[[ "$(docker inspect -f '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}}{{"\n"}}{{end}}' "$target_id")" == "$TARGET_NETWORK" ]] \
  || { printf 'AH-R01 provisioning error: target network boundary mismatch\n' >&2; exit 3; }
[[ "$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}' "$target_id")" == "$TARGET_VOLUME" ]] \
  || { printf 'AH-R01 provisioning error: target volume boundary mismatch\n' >&2; exit 3; }
[[ "$(docker exec "$target_id" sh -c "sed -n 's/^Uid:[[:space:]]*\\([0-9]*\\).*/\\1/p' /proc/1/status")" == "999" ]] \
  || { printf 'AH-R01 provisioning error: Redis process is not uid 999\n' >&2; exit 3; }

unauthenticated="$(docker exec "$target_id" redis-cli ping 2>&1 || true)"
[[ "$unauthenticated" == *NOAUTH* ]] \
  || { printf 'AH-R01 provisioning error: unauthenticated Redis command was not rejected\n' >&2; exit 3; }
docker exec "$target_id" sh -ec '
  REDISCLI_AUTH="$(tr -d "\r\n" < /run/secrets/agent_redis_password)"; export REDISCLI_AUTH
  test "$(redis-cli --no-auth-warning ping)" = PONG
  test "$(redis-cli --no-auth-warning dbsize)" = 0
  redis-cli --no-auth-warning info persistence | tr -d "\r" | grep -qx "aof_enabled:1"
  redis-cli --no-auth-warning info persistence | tr -d "\r" | grep -qx "aof_last_write_status:ok"
'

v1_redis_after="$(docker compose -f "$V1_COMPOSE" ps -q redis)"
agent_hub_after="$(docker compose -f "$BASE_COMPOSE" ps -q agent-hub)"
[[ "$v1_redis_after" == "$v1_redis_before" && "$agent_hub_after" == "$agent_hub_before" ]] \
  || { printf 'AH-R01 provisioning error: V1 Redis or Agent Hub identity changed\n' >&2; exit 3; }

image_id="$(docker inspect -f '{{.Image}}' "$target_id")"
docker_root="$(docker info --format '{{.DockerRootDir}}')"
free_kib="$(df -Pk "$docker_root" | awk 'NR == 2 {print $4}')"
free_bytes="$((free_kib * 1024))"
verified_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
python3 - "$receipt_dir/provision-receipt.json" <<PY
import json
from pathlib import Path
import sys

payload = {
    "schema_version": "1.0",
    "status": "PASS",
    "change_id": "AH-R01-M1",
    "verified_at": "$verified_at",
    "git_commit": "$EXPECTED_COMMIT",
    "target_image_id": "$image_id",
    "target_container_id": "$target_id",
    "target_network": "$TARGET_NETWORK",
    "target_volume": "$TARGET_VOLUME",
    "target_empty": True,
    "target_host_port_published": False,
    "target_authentication_required": True,
    "target_aof": "PASS",
    "docker_storage_free_bytes": int("$free_bytes"),
    "agent_hub_container_unchanged": True,
    "agent_hub_redis_url_changed": False,
    "v1_redis_container_unchanged": True,
    "production_data_exported": False,
    "production_data_restored": False,
    "cutover_performed": False,
    "ah03_authorized": False,
}
Path(sys.argv[1]).write_text(
    json.dumps(payload, indent=2) + "\n", encoding="utf-8"
)
PY
chmod 600 "$receipt_dir"/*.json "$receipt_dir"/*.sha256

trap - EXIT
printf 'AH-R01 M1 provisioning PASS: receipt=%s target_empty=true agent_hub_unchanged=true v1_redis_unchanged=true cutover=false\n' \
  "$receipt_dir/provision-receipt.json"
