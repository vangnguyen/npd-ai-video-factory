#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="${PHASE5_COMPOSE_FILE:-$ROOT_DIR/deploy/phase5/docker-compose.agent-hub.prod.yml}"
ENV_FILE="${AGENT_HUB_ENV_FILE:-/etc/npd-ai/agent-hub.env}"
IMAGE=""
BACKUP=""

usage() {
  cat >&2 <<'EOF'
Usage: bash scripts/phase5/rollback.sh --image <rollback-image-tag> [--backup <agent-hub-backup.json>]

The image rollback is always explicit. Redis namespace restore is optional and destructive;
it is only performed when --backup is provided.
EOF
  exit 2
}

while (($#)); do
  case "$1" in
    --image) IMAGE="${2:-}"; shift 2 ;;
    --backup) BACKUP="${2:-}"; shift 2 ;;
    *) usage ;;
  esac
done

[[ -n "$IMAGE" ]] || usage
[[ -f "$ENV_FILE" ]] || { printf 'rollback error: env file not found: %s\n' "$ENV_FILE" >&2; exit 2; }
docker image inspect "$IMAGE" >/dev/null 2>&1 || { printf 'rollback error: image not found: %s\n' "$IMAGE" >&2; exit 2; }

export AGENT_HUB_ENV_FILE="$ENV_FILE"
export AGENT_HUB_IMAGE="$IMAGE"

if [[ -n "$BACKUP" ]]; then
  [[ -f "$BACKUP" ]] || { printf 'rollback error: backup not found: %s\n' "$BACKUP" >&2; exit 2; }
  docker compose -f "$COMPOSE_FILE" stop agent-hub >/dev/null 2>&1 || true
  cat "$BACKUP" | docker compose -f "$COMPOSE_FILE" run --rm --no-deps -T agent-hub \
    python -m npd_agent_hub.maintenance restore \
      --input - --replace --confirm RESTORE_AGENT_HUB
fi

docker compose -f "$COMPOSE_FILE" up -d --no-deps --no-build --force-recreate agent-hub

container_id="$(docker compose -f "$COMPOSE_FILE" ps -q agent-hub)"
for _ in $(seq 1 24); do
  status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id")"
  if [[ "$status" == "healthy" ]]; then
    printf 'rollback ok: image=%s container=%s\n' "$IMAGE" "$container_id"
    exit 0
  fi
  if [[ "$status" == "unhealthy" || "$status" == "exited" || "$status" == "dead" ]]; then
    docker compose -f "$COMPOSE_FILE" logs --tail=100 agent-hub >&2 || true
    printf 'rollback error: Agent Hub reached status %s\n' "$status" >&2
    exit 3
  fi
  sleep 5
done

docker compose -f "$COMPOSE_FILE" logs --tail=100 agent-hub >&2 || true
printf 'rollback error: Agent Hub did not become healthy in time\n' >&2
exit 3
