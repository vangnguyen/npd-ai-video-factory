#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${AGENT_HUB_PUBLIC_URL:-http://127.0.0.1:${AGENT_HUB_PORT:-8010}}"
ENV_FILE="${AGENT_HUB_ENV_FILE:-/etc/npd-ai/agent-hub.env}"

fail() {
  printf 'smoke error: %s\n' "$*" >&2
  exit 2
}

command -v curl >/dev/null 2>&1 || fail "curl is required"
command -v python3 >/dev/null 2>&1 || fail "python3 is required"
[[ -f "$ENV_FILE" ]] || fail "env file not found: $ENV_FILE"

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

for name in AGENT_VIEWER_TOKEN AGENT_OPERATOR_TOKEN AGENT_OWNER_TOKEN; do
  [[ -n "${!name:-}" ]] || fail "$name is missing"
done

BASE_URL="${BASE_URL%/}"
workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

http_code() {
  local method="$1"
  local url="$2"
  local token="${3:-}"
  local data="${4:-}"
  local output="$5"
  local args=(-sS -o "$output" -w '%{http_code}' -X "$method")
  if [[ -n "$token" ]]; then
    args+=(-H "Authorization: Bearer $token")
  fi
  if [[ -n "$data" ]]; then
    args+=(-H 'Content-Type: application/json' --data "$data")
  fi
  curl "${args[@]}" "$url"
}

code="$(http_code GET "$BASE_URL/health" '' '' "$workdir/health.json")"
[[ "$code" == "200" ]] || fail "/health returned HTTP $code"

code="$(http_code GET "$BASE_URL/readyz" '' '' "$workdir/ready.json")"
[[ "$code" == "200" ]] || fail "/readyz returned HTTP $code"

code="$(http_code GET "$BASE_URL/api/v1/command-center" '' '' "$workdir/unauth.json")"
[[ "$code" == "401" ]] || fail "unauthenticated Command Center must return 401, got $code"

code="$(http_code GET "$BASE_URL/api/v1/command-center" "$AGENT_VIEWER_TOKEN" '' "$workdir/viewer.json")"
[[ "$code" == "200" ]] || fail "viewer Command Center returned HTTP $code"

code="$(http_code GET "$BASE_URL/api/v1/whoami" "$AGENT_OWNER_TOKEN" '' "$workdir/whoami.json")"
[[ "$code" == "200" ]] || fail "owner whoami returned HTTP $code"
owner_role="$(python3 - "$workdir/whoami.json" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding='utf-8')).get('role', ''))
PY
)"
[[ "$owner_role" == "owner" ]] || fail "owner token resolved to unexpected role: $owner_role"

create_body='{"objective":"Phase 5 deployment RBAC smoke","preferred_agents":["social_media"]}'
code="$(http_code POST "$BASE_URL/api/v1/agent-tasks" "$AGENT_OPERATOR_TOKEN" "$create_body" "$workdir/task.json")"
[[ "$code" == "200" ]] || fail "operator task creation returned HTTP $code"

read -r task_id action_id < <(python3 - "$workdir/task.json" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding='utf-8'))
task_id = payload['task_id']
action_id = ''
for report in payload.get('reports', []):
    for action in report.get('actions', []):
        if action.get('tool') == 'social.publish':
            action_id = action['action_id']
            break
    if action_id:
        break
if not action_id:
    raise SystemExit('social.publish action not found')
print(task_id, action_id)
PY
)

code="$(http_code POST "$BASE_URL/api/v1/agent-tasks/$task_id/actions/$action_id/decision" "$AGENT_OPERATOR_TOKEN" '{"approved":false,"note":"phase5 smoke"}' "$workdir/operator-decision.json")"
[[ "$code" == "403" ]] || fail "operator must not approve/reject owner action; got HTTP $code"

code="$(http_code POST "$BASE_URL/api/v1/agent-tasks/$task_id/actions/$action_id/decision" "$AGENT_OWNER_TOKEN" '{"approved":false,"note":"phase5 smoke reject - no external side effect"}' "$workdir/owner-decision.json")"
[[ "$code" == "200" ]] || fail "owner reject returned HTTP $code"

code="$(http_code GET "$BASE_URL/api/v1/integrations/espocrm/schema/Lead" "$AGENT_VIEWER_TOKEN" '' "$workdir/espo-schema.json")"
[[ "$code" == "200" ]] || fail "EspoCRM Lead schema discovery returned HTTP $code"

code="$(http_code GET "$BASE_URL/api/v1/integrations/espocrm/mapping/Lead" "$AGENT_VIEWER_TOKEN" '' "$workdir/espo-mapping.json")"
[[ "$code" == "200" ]] || fail "EspoCRM Lead mapping returned HTTP $code"

field_count="$(python3 - "$workdir/espo-schema.json" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding='utf-8'))
print(payload.get('field_count', 0))
PY
)"
[[ "$field_count" =~ ^[0-9]+$ ]] && (( field_count > 0 )) || fail "EspoCRM Lead schema returned no fields"

printf 'smoke ok: url=%s auth=viewer/operator/owner espocrm_lead_fields=%s task=%s\n' "$BASE_URL" "$field_count" "$task_id"
