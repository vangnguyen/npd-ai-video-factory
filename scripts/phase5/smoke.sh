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

if [[ "${AGENT_BROWSER_AUTH_MODE:-}" == "google_oidc" ]]; then
  code="$(curl -sS -D "$workdir/command-center.headers" -o "$workdir/command-center.html" -w '%{http_code}' "$BASE_URL/command-center")"
  [[ "$code" == "303" ]] || fail "unauthenticated browser must be redirected to login; got HTTP $code"
  grep -Eiq '^location:[[:space:]]*/login' "$workdir/command-center.headers" \
    || fail "Command Center redirect did not target /login"

  code="$(curl -sS -o "$workdir/login.html" -w '%{http_code}' "$BASE_URL/login")"
  [[ "$code" == "200" ]] || fail "/login returned HTTP $code"
  grep -Fq '/auth/google/login' "$workdir/login.html" \
    || fail "login page does not expose the Google login action"

  code="$(curl -sS -D "$workdir/google-login.headers" -o /dev/null -w '%{http_code}' "$BASE_URL/auth/google/login")"
  [[ "$code" == "302" ]] || fail "Google login start returned HTTP $code"
  grep -Eiq '^location:[[:space:]]*https://accounts\.google\.com/' "$workdir/google-login.headers" \
    || fail "Google login start did not redirect to Google"
fi

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

crm_body='{"objective":"Kiểm tra CRM và tìm các lead chưa được chăm sóc"}'
code="$(http_code POST "$BASE_URL/api/v1/agent-tasks" "$AGENT_OPERATOR_TOKEN" "$crm_body" "$workdir/crm-answer.json")"
[[ "$code" == "200" ]] || fail "CRM business-answer task returned HTTP $code"

read -r crm_task_id crm_answer_status < <(python3 - "$workdir/crm-answer.json" <<'PY'
import json, sys

payload = json.load(open(sys.argv[1], encoding='utf-8'))
answer = payload.get('answer') or {}
status = answer.get('status', '')
if status != 'completed':
    raise SystemExit(f'CRM answer is not completed: {status}')
if 'crm_manager' not in payload.get('selected_agents', []):
    raise SystemExit('CRM manager was not selected')
if 'marketing_leader' in payload.get('selected_agents', []):
    raise SystemExit('pure CRM follow-up question was incorrectly routed to marketing')
metrics = answer.get('metrics') or {}
for metric in ('Lead đã kiểm tra', 'Cần chăm sóc'):
    if metric not in metrics:
        raise SystemExit(f'CRM answer is missing metric: {metric}')
if not (
    'Ngưỡng quá hạn (ngày)' in metrics
    or (
        'SLA New/Assigned (phút)' in metrics
        and 'SLA In Process/Recycled (giờ)' in metrics
    )
):
    raise SystemExit('CRM answer is missing care threshold/SLA metrics')
if not answer.get('evidence'):
    raise SystemExit('CRM answer has no read-only evidence')
raw = json.dumps(payload, ensure_ascii=False)
if 'emailAddress' in raw or 'phoneNumber' in raw:
    raise SystemExit('CRM answer persisted raw contact fields')
print(payload['task_id'], status)
PY
)

code="$(http_code GET "$BASE_URL/api/v1/agent-tasks/$crm_task_id/executions" "$AGENT_VIEWER_TOKEN" '' "$workdir/crm-executions.json")"
[[ "$code" == "200" ]] || fail "CRM execution evidence returned HTTP $code"
python3 - "$workdir/crm-executions.json" <<'PY'
import json, sys

payload = json.load(open(sys.argv[1], encoding='utf-8'))
tools = {item.get('tool') for item in payload}
if not tools or not tools.issubset({'crm.leads.read', 'crm.audit.read'}):
    raise SystemExit(f'unexpected auto-executed tools: {sorted(tools)}')
raw = json.dumps(payload, ensure_ascii=False)
if 'emailAddress' in raw or 'phoneNumber' in raw:
    raise SystemExit('CRM execution evidence persisted raw contact fields')
PY

python3 - "$workdir/crm-answer.json" <<'PY' > "$workdir/crm-approval-ids.txt"
import json, sys

payload = json.load(open(sys.argv[1], encoding='utf-8'))
for action in payload.get('approvals_required', []):
    print(action['action_id'])
PY
while IFS= read -r crm_action_id; do
  [[ -n "$crm_action_id" ]] || continue
  code="$(http_code POST "$BASE_URL/api/v1/agent-tasks/$crm_task_id/actions/$crm_action_id/decision" "$AGENT_OWNER_TOKEN" '{"approved":false,"note":"phase5 CRM answer smoke reject - no external side effect"}' "$workdir/crm-reject-$crm_action_id.json")"
  [[ "$code" == "200" ]] || fail "owner CRM smoke reject returned HTTP $code"
done < "$workdir/crm-approval-ids.txt"

analytics_body='{"objective":"Báo cáo hiệu quả marketing theo nguồn trong 30 ngày"}'
code="$(http_code POST "$BASE_URL/api/v1/agent-tasks" "$AGENT_OPERATOR_TOKEN" "$analytics_body" "$workdir/analytics-answer.json")"
[[ "$code" == "200" ]] || fail "marketing analytics task returned HTTP $code"

read -r analytics_task_id analytics_answer_status < <(python3 - "$workdir/analytics-answer.json" <<'PY'
import json, sys

payload = json.load(open(sys.argv[1], encoding='utf-8'))
answer = payload.get('answer') or {}
status = answer.get('status', '')
if status != 'completed':
    raise SystemExit(f'analytics answer is not completed: {status}')
if payload.get('selected_agents') != ['marketing_leader']:
    raise SystemExit(f'unexpected analytics routing: {payload.get("selected_agents")}')
metrics = answer.get('metrics') or {}
for metric in ('Lead đã phân tích', 'Đã chuyển đổi', 'Tỷ lệ Converted (%)', 'Active quá 24 giờ'):
    if metric not in metrics:
        raise SystemExit(f'analytics answer is missing metric: {metric}')
if not any('analytics.read' in item for item in answer.get('evidence', [])):
    raise SystemExit('analytics answer has no read-only evidence')
raw = json.dumps(payload, ensure_ascii=False)
for forbidden in ('emailAddress', 'phoneNumber', 'assignedUserName'):
    if forbidden in raw:
        raise SystemExit(f'analytics answer persisted forbidden field: {forbidden}')
print(payload['task_id'], status)
PY
)

code="$(http_code GET "$BASE_URL/api/v1/agent-tasks/$analytics_task_id/executions" "$AGENT_VIEWER_TOKEN" '' "$workdir/analytics-executions.json")"
[[ "$code" == "200" ]] || fail "analytics execution evidence returned HTTP $code"
python3 - "$workdir/analytics-executions.json" <<'PY'
import json, sys

payload = json.load(open(sys.argv[1], encoding='utf-8'))
if {item.get('tool') for item in payload} != {'analytics.read'}:
    raise SystemExit('analytics auto-executed a tool outside analytics.read')
raw = json.dumps(payload, ensure_ascii=False)
for forbidden in ('emailAddress', 'phoneNumber', 'assignedUserName'):
    if forbidden in raw:
        raise SystemExit(f'analytics execution persisted forbidden field: {forbidden}')
PY

python3 - "$workdir/analytics-answer.json" <<'PY' > "$workdir/analytics-approval-ids.txt"
import json, sys

payload = json.load(open(sys.argv[1], encoding='utf-8'))
for action in payload.get('approvals_required', []):
    print(action['action_id'])
PY
while IFS= read -r analytics_action_id; do
  [[ -n "$analytics_action_id" ]] || continue
  code="$(http_code POST "$BASE_URL/api/v1/agent-tasks/$analytics_task_id/actions/$analytics_action_id/decision" "$AGENT_OWNER_TOKEN" '{"approved":false,"note":"phase5 analytics smoke reject - no external side effect"}' "$workdir/analytics-reject-$analytics_action_id.json")"
  [[ "$code" == "200" ]] || fail "owner analytics smoke reject returned HTTP $code"
done < "$workdir/analytics-approval-ids.txt"

field_count="$(python3 - "$workdir/espo-schema.json" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding='utf-8'))
print(payload.get('field_count', 0))
PY
)"
if ! [[ "$field_count" =~ ^[0-9]+$ ]] || (( field_count <= 0 )); then
  fail "EspoCRM Lead schema returned no fields"
fi

printf 'smoke ok: url=%s auth=viewer/operator/owner+google_oidc espocrm_lead_fields=%s task=%s crm_task=%s crm_answer=%s analytics_task=%s analytics_answer=%s\n' "$BASE_URL" "$field_count" "$task_id" "$crm_task_id" "$crm_answer_status" "$analytics_task_id" "$analytics_answer_status"
