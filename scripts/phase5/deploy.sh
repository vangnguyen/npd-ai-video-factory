#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="${PHASE5_COMPOSE_FILE:-$ROOT_DIR/deploy/phase5/docker-compose.agent-hub.prod.yml}"
ENV_FILE="${AGENT_HUB_ENV_FILE:-/etc/npd-ai/agent-hub.env}"
BACKUP_DIR="${AGENT_HUB_BACKUP_DIR:-/var/backups/npd-agent-hub}"
RECEIPT_DIR="${AGENT_HUB_DEPLOY_RECEIPT_DIR:-/var/lib/npd-ai/agent-hub-deployments}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ACTIVE_IMAGE="${AGENT_HUB_IMAGE:-npd-agent-hub:phase5}"
ROLLBACK_IMAGE=""
BACKUP_PATH=""

export AGENT_HUB_ENV_FILE="$ENV_FILE"
export AGENT_HUB_IMAGE="$ACTIVE_IMAGE"
export PHASE5_TIMESTAMP="$TIMESTAMP"

bash "$ROOT_DIR/scripts/phase5/preflight.sh"

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

mkdir -p "$BACKUP_DIR" "$RECEIPT_DIR"

current_container="$(docker compose -f "$COMPOSE_FILE" ps -q agent-hub 2>/dev/null || true)"
if [[ -n "$current_container" ]]; then
  current_image_id="$(docker inspect -f '{{.Image}}' "$current_container")"
  ROLLBACK_IMAGE="npd-agent-hub:rollback-$TIMESTAMP"
  docker tag "$current_image_id" "$ROLLBACK_IMAGE"

  BACKUP_PATH="$BACKUP_DIR/agent-hub-$TIMESTAMP.json"
  bash "$ROOT_DIR/scripts/phase5/backup.sh" "$BACKUP_PATH"
fi

rollback_on_failure() {
  exit_code=$?
  if [[ $exit_code -eq 0 ]]; then
    return
  fi
  printf 'deploy failed with exit code %s\n' "$exit_code" >&2
  if [[ -n "$ROLLBACK_IMAGE" ]]; then
    printf 'attempting image rollback to %s (Redis restore is intentionally NOT automatic)\n' "$ROLLBACK_IMAGE" >&2
    AGENT_HUB_ENV_FILE="$ENV_FILE" bash "$ROOT_DIR/scripts/phase5/rollback.sh" --image "$ROLLBACK_IMAGE" || true
  else
    docker compose -f "$COMPOSE_FILE" rm -sf agent-hub >/dev/null 2>&1 || true
  fi
  exit "$exit_code"
}
trap rollback_on_failure EXIT

docker compose -f "$COMPOSE_FILE" build agent-hub
docker compose -f "$COMPOSE_FILE" up -d --no-deps --force-recreate agent-hub

container_id="$(docker compose -f "$COMPOSE_FILE" ps -q agent-hub)"
[[ -n "$container_id" ]] || { printf 'deploy error: Agent Hub container was not created\n' >&2; exit 3; }

for _ in $(seq 1 30); do
  status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id")"
  if [[ "$status" == "healthy" ]]; then
    break
  fi
  if [[ "$status" == "unhealthy" || "$status" == "exited" || "$status" == "dead" ]]; then
    docker compose -f "$COMPOSE_FILE" logs --tail=150 agent-hub >&2 || true
    printf 'deploy error: Agent Hub reached status %s\n' "$status" >&2
    exit 3
  fi
  sleep 5
done

status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id")"
[[ "$status" == "healthy" ]] || { docker compose -f "$COMPOSE_FILE" logs --tail=150 agent-hub >&2 || true; printf 'deploy error: Agent Hub health timeout (%s)\n' "$status" >&2; exit 3; }

AGENT_HUB_ENV_FILE="$ENV_FILE" \
AGENT_HUB_PUBLIC_URL="${AGENT_HUB_PUBLIC_URL:-http://127.0.0.1:${AGENT_HUB_PORT:-8010}}" \
  bash "$ROOT_DIR/scripts/phase5/smoke.sh"

new_image_id="$(docker inspect -f '{{.Image}}' "$container_id")"
git_sha="$(git -C "$ROOT_DIR" rev-parse HEAD 2>/dev/null || printf unknown)"
receipt="$RECEIPT_DIR/deploy-$TIMESTAMP.json"
python3 - "$receipt" "$TIMESTAMP" "$git_sha" "$new_image_id" "$ACTIVE_IMAGE" "$ROLLBACK_IMAGE" "$BACKUP_PATH" <<'PY'
import json, os, sys
path, timestamp, git_sha, image_id, image_tag, rollback_image, backup_path = sys.argv[1:]
payload = {
    "timestamp": timestamp,
    "git_sha": git_sha,
    "image_id": image_id,
    "image_tag": image_tag,
    "rollback_image": rollback_image or None,
    "backup_path": backup_path or None,
}
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
    f.write("\n")
os.chmod(path, 0o600)
PY

trap - EXIT
printf 'deploy ok: container=%s image=%s receipt=%s rollback_image=%s backup=%s\n' \
  "$container_id" "$new_image_id" "$receipt" "${ROLLBACK_IMAGE:-none}" "${BACKUP_PATH:-none}"
