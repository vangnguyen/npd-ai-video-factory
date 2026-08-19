#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="${PHASE5_COMPOSE_FILE:-$ROOT_DIR/deploy/phase5/docker-compose.agent-hub.prod.yml}"
ENV_FILE="${AGENT_HUB_ENV_FILE:-/etc/npd-ai/agent-hub.env}"
NETWORK="${NPD_DOCKER_NETWORK:-npd-ai-video-factory_default}"

fail() {
  printf 'preflight error: %s\n' "$*" >&2
  exit 2
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

require_value() {
  local name="$1"
  local value="${!name:-}"
  [[ -n "$value" ]] || fail "$name is required"
  [[ "$value" != *REPLACE_WITH* ]] || fail "$name still contains the example placeholder"
}

require_command docker
require_command git

docker compose version >/dev/null 2>&1 || fail "docker compose plugin is unavailable"
[[ -f "$COMPOSE_FILE" ]] || fail "production compose file not found: $COMPOSE_FILE"
[[ -f "$ENV_FILE" ]] || fail "production env file not found: $ENV_FILE"

if stat -c '%a' "$ENV_FILE" >/dev/null 2>&1; then
  mode="$(stat -c '%a' "$ENV_FILE")"
  case "$mode" in
    600|640) ;;
    *) fail "$ENV_FILE permissions must be 600 or 640, found $mode" ;;
  esac
fi

# The env file is controlled by the VPS operator and must contain shell-compatible KEY=value lines.
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

[[ "${AGENT_AUTH_MODE:-}" == "static_token" ]] || fail "AGENT_AUTH_MODE must be static_token in production"
[[ "${AGENT_STORE_BACKEND:-}" == "redis" ]] || fail "AGENT_STORE_BACKEND must be redis in production"

require_value AGENT_VIEWER_TOKEN
require_value AGENT_OPERATOR_TOKEN
require_value AGENT_OWNER_TOKEN
require_value ESPOCRM_URL
require_value ESPOCRM_API_KEY

for token_name in AGENT_VIEWER_TOKEN AGENT_OPERATOR_TOKEN AGENT_OWNER_TOKEN; do
  token="${!token_name}"
  [[ ${#token} -ge 32 ]] || fail "$token_name must be at least 32 characters"
done

[[ "$AGENT_VIEWER_TOKEN" != "$AGENT_OPERATOR_TOKEN" ]] || fail "viewer/operator tokens must differ"
[[ "$AGENT_VIEWER_TOKEN" != "$AGENT_OWNER_TOKEN" ]] || fail "viewer/owner tokens must differ"
[[ "$AGENT_OPERATOR_TOKEN" != "$AGENT_OWNER_TOKEN" ]] || fail "operator/owner tokens must differ"

case "$ESPOCRM_URL" in
  http://*|https://*) ;;
  *) fail "ESPOCRM_URL must start with http:// or https://" ;;
esac

docker network inspect "$NETWORK" >/dev/null 2>&1 || fail "existing Docker network not found: $NETWORK"
network_containers="$(docker network inspect "$NETWORK" --format '{{range .Containers}}{{println .Name}}{{end}}')"
printf '%s\n' "$network_containers" | grep -Eiq '(^|[-_])redis([-_]|$)' || fail "no Redis container found on $NETWORK"
printf '%s\n' "$network_containers" | grep -Eiq '(^|[-_])api([-_]|$)' || fail "no video API container found on $NETWORK"

if [[ "${PHASE5_REQUIRE_CADDY:-1}" == "1" ]]; then
  require_command caddy
fi

if git -C "$ROOT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git -C "$ROOT_DIR" diff --quiet || fail "working tree has unstaged changes"
  git -C "$ROOT_DIR" diff --cached --quiet || fail "working tree has staged but uncommitted changes"
fi

export AGENT_HUB_ENV_FILE="$ENV_FILE"
export NPD_DOCKER_NETWORK="$NETWORK"
docker compose -f "$COMPOSE_FILE" config --quiet

printf 'preflight ok: compose=%s network=%s auth=static_token store=redis\n' "$COMPOSE_FILE" "$NETWORK"
