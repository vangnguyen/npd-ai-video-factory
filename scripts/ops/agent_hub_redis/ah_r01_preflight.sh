#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
BASE_COMPOSE="${PHASE5_COMPOSE_FILE:-$ROOT_DIR/deploy/phase5/docker-compose.agent-hub.prod.yml}"
OVERLAY_COMPOSE="${AH_R01_OVERLAY_COMPOSE:-$ROOT_DIR/deploy/ah-r01/docker-compose.redis-independent.yml}"
V1_COMPOSE="${V1_COMPOSE_FILE:-$ROOT_DIR/docker-compose.yml}"
EXPECTED_COMMIT="${AH_R01_EXPECTED_COMMIT:-}"
EXPECTED_IMAGE_ID="${AH_R01_EXPECTED_REDIS_IMAGE_ID:-}"
PASSWORD_FILE="${AH_R01_REDIS_PASSWORD_HOST_FILE:-}"
REDIS_IMAGE="${AGENT_REDIS_IMAGE:-redis:7-alpine}"
TARGET_NETWORK="${AH_R01_REDIS_NETWORK_NAME:-npd-agent-hub-data}"
TARGET_VOLUME="${AH_R01_REDIS_VOLUME_NAME:-npd-agent-hub-redis-data}"
MIN_FREE_BYTES="${AH_R01_MIN_FREE_BYTES:-5368709120}"

fail() { printf 'AH-R01 preflight error: %s\n' "$*" >&2; exit 2; }

[[ "$TARGET_NETWORK" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{2,127}$ ]] \
  || fail "target network name is invalid"
[[ "$TARGET_VOLUME" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{2,127}$ ]] \
  || fail "target volume name is invalid"
[[ "$MIN_FREE_BYTES" =~ ^[1-9][0-9]{8,}$ ]] \
  || fail "AH_R01_MIN_FREE_BYTES must be a positive byte threshold"

[[ "$EXPECTED_COMMIT" =~ ^[0-9a-f]{40}$ ]] \
  || fail "AH_R01_EXPECTED_COMMIT must be a 40-character SHA"
[[ "$(git -C "$ROOT_DIR" rev-parse HEAD)" == "$EXPECTED_COMMIT" ]] \
  || fail "repository commit does not match the approved SHA"
git -C "$ROOT_DIR" diff --quiet || fail "tracked working tree has unstaged changes"
git -C "$ROOT_DIR" diff --cached --quiet || fail "tracked working tree has staged changes"

[[ "$PASSWORD_FILE" == /* && -f "$PASSWORD_FILE" ]] \
  || fail "Redis password must be an absolute regular file"
resolved_password_file="$(realpath "$PASSWORD_FILE")"
case "$resolved_password_file" in
  "$ROOT_DIR"|"$ROOT_DIR"/*) fail "Redis password file must be outside the repository" ;;
esac
if mode="$(stat -c '%a' "$resolved_password_file" 2>/dev/null)"; then
  (( 8#$mode & 0077 )) && fail "Redis password permissions must be 0600 or stricter"
fi
python3 - "$resolved_password_file" <<'PY'
from pathlib import Path
import re
import sys

value = Path(sys.argv[1]).read_text(encoding="utf-8").rstrip("\r\n")
if re.fullmatch(r"[A-Za-z0-9_-]{43,128}", value) is None:
    raise SystemExit("Redis password must contain 43-128 base64url characters")
PY

[[ "$EXPECTED_IMAGE_ID" =~ ^sha256:[0-9a-f]{64}$ ]] \
  || fail "AH_R01_EXPECTED_REDIS_IMAGE_ID must be an approved sha256 image ID"
actual_image_id="$(docker image inspect "$REDIS_IMAGE" --format '{{.Id}}' 2>/dev/null)" \
  || fail "approved Redis image is not present locally"
[[ "$actual_image_id" == "$EXPECTED_IMAGE_ID" ]] \
  || fail "local Redis image does not match the approved image ID"
docker_root="$(docker info --format '{{.DockerRootDir}}')"
free_kib="$(df -Pk "$docker_root" | awk 'NR == 2 {print $4}')"
[[ "$free_kib" =~ ^[0-9]+$ ]] || fail "could not determine Docker storage free space"
free_bytes="$((free_kib * 1024))"
(( free_bytes >= MIN_FREE_BYTES )) || fail "Docker storage free space is below the approved threshold"

AH_R01_REDIS_PASSWORD_HOST_FILE="$resolved_password_file" \
  docker compose -f "$BASE_COMPOSE" -f "$OVERLAY_COMPOSE" config --quiet

v1_redis_id="$(docker compose -f "$V1_COMPOSE" ps -q redis)"
agent_hub_id="$(docker compose -f "$BASE_COMPOSE" ps -q agent-hub)"
[[ -n "$v1_redis_id" && -n "$agent_hub_id" ]] \
  || fail "running V1 Redis and production Agent Hub are required"
[[ "$(docker inspect -f '{{.State.Running}}' "$v1_redis_id")" == "true" ]] \
  || fail "V1 Redis is not running"
[[ "$(docker inspect -f '{{.State.Running}}' "$agent_hub_id")" == "true" ]] \
  || fail "Agent Hub is not running"
current_url="$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$agent_hub_id" \
  | sed -n 's/^AGENT_REDIS_URL=//p' | tail -n 1)"
[[ "$current_url" == "redis://redis:6379/1" ]] \
  || fail "Agent Hub is not on the accepted V1 Redis DB1 source endpoint"

existing_target="$(AH_R01_REDIS_PASSWORD_HOST_FILE="$resolved_password_file" \
  docker compose -f "$BASE_COMPOSE" -f "$OVERLAY_COMPOSE" ps -aq agent-redis)"
[[ -z "$existing_target" ]] || fail "Agent Hub-owned Redis container already exists"
docker volume inspect "$TARGET_VOLUME" >/dev/null 2>&1 \
  && fail "Agent Hub-owned Redis volume already exists"
docker network inspect "$TARGET_NETWORK" >/dev/null 2>&1 \
  && fail "Agent Hub-owned Redis network already exists"

printf 'AH-R01 preflight PASS: commit=%s redis_image_id=%s free_bytes=%s min_free_bytes=%s current_source=v1-db1 target_absent=true agent_hub_unchanged_required=true v1_redis_unchanged_required=true\n' \
  "$EXPECTED_COMMIT" "$actual_image_id" "$free_bytes" "$MIN_FREE_BYTES"
