#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="${PHASE5_COMPOSE_FILE:-$ROOT_DIR/deploy/phase5/docker-compose.agent-hub.prod.yml}"
ENV_FILE="${AGENT_HUB_ENV_FILE:-/etc/npd-ai/agent-hub.env}"
VIDEO_NETWORK="${NPD_DOCKER_NETWORK:-npd-ai-video-factory_default}"
N8N_NETWORK="${N8N_DOCKER_NETWORK:-n8n-marketing_n8n_net}"
N8N_COMPOSE_FILE="${N8N_COMPOSE_FILE:-/opt/n8n/docker-compose.yml}"
N8N_COMPOSE_PROJECT="${N8N_COMPOSE_PROJECT:-n8n-marketing}"
CADDY_CONTAINER="${N8N_CADDY_CONTAINER:-}"
CADDYFILE="${N8N_CADDYFILE:-/opt/n8n/Caddyfile}"

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
require_command curl
require_command python3

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
[[ "${AGENT_BROWSER_AUTH_MODE:-}" == "google_oidc" ]] || fail "AGENT_BROWSER_AUTH_MODE must be google_oidc in production"
[[ "${AGENT_STORE_BACKEND:-}" == "redis" ]] || fail "AGENT_STORE_BACKEND must be redis in production"

require_value AGENT_VIEWER_TOKEN
require_value AGENT_OPERATOR_TOKEN
require_value AGENT_OWNER_TOKEN
require_value AGENT_PUBLIC_BASE_URL
require_value AGENT_GOOGLE_CLIENT_ID
require_value AGENT_GOOGLE_CLIENT_SECRET
require_value AGENT_SESSION_SIGNING_KEY
require_value AGENT_OWNER_EMAILS
require_value ESPOCRM_URL
require_value ESPOCRM_API_KEY

for token_name in AGENT_VIEWER_TOKEN AGENT_OPERATOR_TOKEN AGENT_OWNER_TOKEN; do
  token="${!token_name}"
  [[ ${#token} -ge 32 ]] || fail "$token_name must be at least 32 characters"
done

[[ "$AGENT_VIEWER_TOKEN" != "$AGENT_OPERATOR_TOKEN" ]] || fail "viewer/operator tokens must differ"
[[ "$AGENT_VIEWER_TOKEN" != "$AGENT_OWNER_TOKEN" ]] || fail "viewer/owner tokens must differ"
[[ "$AGENT_OPERATOR_TOKEN" != "$AGENT_OWNER_TOKEN" ]] || fail "operator/owner tokens must differ"

[[ ${#AGENT_SESSION_SIGNING_KEY} -ge 32 ]] || fail "AGENT_SESSION_SIGNING_KEY must be at least 32 characters"
[[ "$AGENT_PUBLIC_BASE_URL" =~ ^https://[^/]+$ ]] \
  || fail "AGENT_PUBLIC_BASE_URL must be an HTTPS origin without a path or trailing slash"
[[ "$AGENT_OWNER_EMAILS" == *"@"* ]] || fail "AGENT_OWNER_EMAILS must contain at least one email"

case "$ESPOCRM_URL" in
  http://*|https://*) ;;
  *) fail "ESPOCRM_URL must start with http:// or https://" ;;
esac

docker network inspect "$VIDEO_NETWORK" >/dev/null 2>&1 || fail "existing video-factory Docker network not found: $VIDEO_NETWORK"
video_network_containers="$(docker network inspect "$VIDEO_NETWORK" --format '{{range .Containers}}{{println .Name}}{{end}}')"
printf '%s\n' "$video_network_containers" | grep -Eiq '(^|[-_])redis([-_]|$)' || fail "no Redis container found on $VIDEO_NETWORK"
printf '%s\n' "$video_network_containers" | grep -Eiq '(^|[-_])api([-_]|$)' || fail "no video API container found on $VIDEO_NETWORK"

if [[ "${PHASE5_REQUIRE_CADDY:-1}" == "1" ]]; then
  [[ -f "$N8N_COMPOSE_FILE" ]] || fail "n8n production Compose file not found: $N8N_COMPOSE_FILE"
  [[ -f "$CADDYFILE" ]] || fail "host Caddyfile not found: $CADDYFILE"
  n8n_compose_services="$(
    docker compose -p "$N8N_COMPOSE_PROJECT" -f "$N8N_COMPOSE_FILE" config --services
  )"
  grep -Fxq 'caddy' <<<"$n8n_compose_services" \
    || fail "caddy service not found in $N8N_COMPOSE_FILE"
  caddy_container_id="$(docker compose -p "$N8N_COMPOSE_PROJECT" -f "$N8N_COMPOSE_FILE" ps -q caddy)"
  [[ -n "$caddy_container_id" ]] || fail "running Caddy container was not discovered from project $N8N_COMPOSE_PROJECT"
  if [[ -z "$CADDY_CONTAINER" ]]; then
    CADDY_CONTAINER="$(docker inspect -f '{{.Name}}' "$caddy_container_id")"
    CADDY_CONTAINER="${CADDY_CONTAINER#/}"
  fi
  docker network inspect "$N8N_NETWORK" >/dev/null 2>&1 || fail "n8n Docker network not found: $N8N_NETWORK"
  docker inspect "$CADDY_CONTAINER" >/dev/null 2>&1 || fail "Caddy container not found: $CADDY_CONTAINER"
  [[ "$(docker inspect -f '{{.Id}}' "$CADDY_CONTAINER")" == "$caddy_container_id" ]] \
    || fail "$CADDY_CONTAINER is not the caddy service in Compose project $N8N_COMPOSE_PROJECT"
  [[ "$(docker inspect -f '{{.State.Running}}' "$CADDY_CONTAINER")" == "true" ]] \
    || fail "Caddy container is not running: $CADDY_CONTAINER"
  caddy_network_containers="$(docker network inspect "$N8N_NETWORK" --format '{{range .Containers}}{{println .Name}}{{end}}')"
  printf '%s\n' "$caddy_network_containers" | grep -Fxq "$CADDY_CONTAINER" \
    || fail "$CADDY_CONTAINER is not attached to $N8N_NETWORK"
  mounted_caddyfile="$(docker inspect "$CADDY_CONTAINER" --format '{{range .Mounts}}{{if eq .Destination "/etc/caddy/Caddyfile"}}{{println .Source}}{{end}}{{end}}')"
  [[ "$mounted_caddyfile" == "$CADDYFILE" ]] \
    || fail "$CADDY_CONTAINER does not mount $CADDYFILE at /etc/caddy/Caddyfile"
  docker exec "$CADDY_CONTAINER" caddy validate --config /etc/caddy/Caddyfile >/dev/null
fi

if git -C "$ROOT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git -C "$ROOT_DIR" diff --quiet || fail "working tree has unstaged changes"
  git -C "$ROOT_DIR" diff --cached --quiet || fail "working tree has staged but uncommitted changes"
fi

export AGENT_HUB_ENV_FILE="$ENV_FILE"
export NPD_DOCKER_NETWORK="$VIDEO_NETWORK"
export N8N_DOCKER_NETWORK="$N8N_NETWORK"
docker compose -f "$COMPOSE_FILE" config --quiet

printf 'preflight ok: compose=%s video_network=%s n8n_network=%s caddy=%s auth=static_token+google_oidc store=redis\n' \
  "$COMPOSE_FILE" "$VIDEO_NETWORK" "$N8N_NETWORK" "$CADDY_CONTAINER"
