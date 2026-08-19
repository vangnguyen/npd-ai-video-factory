# Phase 4 — Owner Command Center, RBAC, EspoCRM Mapping

## Scope

Phase 4 turns the Phase 3 Command Center backend into an owner-facing control surface and adds an authentication boundary before any production exposure.

Delivered:

- static bearer-token authentication for self-hosted deployment;
- three roles: `viewer`, `operator`, `owner`;
- owner Command Center page at `/command-center`;
- API role enforcement;
- security response headers;
- `/readyz` authentication configuration validation;
- EspoCRM schema-to-business-field mapping recommendations;
- tests for RBAC and mapping behavior.

## RBAC policy

| Capability | Viewer | Operator | Owner |
|---|---:|---:|---:|
| Read Command Center | yes | yes | yes |
| Read task/audit/execution history | yes | yes | yes |
| Read EspoCRM schema/mapping | yes | yes | yes |
| Create Agent Task | no | yes | yes |
| Execute eligible action | no | yes | yes |
| Approve/reject external write action | no | no | yes |

The existing action-level approval policy remains authoritative. Giving a user `operator` does not let that user approve `social.publish`, `ads.budget.update`, `sales.contact.send`, or `crm.records.update`.

## Authentication configuration

Production/self-hosted deployment should use:

```text
AGENT_AUTH_MODE=static_token
AGENT_VIEWER_TOKEN=<random-viewer-token>
AGENT_OPERATOR_TOKEN=<random-operator-token>
AGENT_OWNER_TOKEN=<random-owner-token>
```

Generate each token independently, for example:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Do not commit generated tokens. Keep them only in deployment secrets/environment configuration.

`AGENT_AUTH_MODE=disabled` exists only for local development and automated tests. In this mode the request is treated as owner-level and Agent Hub must not be exposed to an untrusted network.

When `static_token` is enabled, `/readyz` returns 503 if:

- the owner token is missing;
- two configured role tokens are identical;
- an unsupported auth mode is supplied.

Bearer tokens are compared using constant-time comparison and are not written to Redis or the Agent Hub audit log.

## Owner Command Center

Open:

```text
http://<agent-hub-host>:8010/command-center
```

The page itself contains no task/customer data. Enter a role token in the UI; the token is kept in browser `sessionStorage` and sent in the `Authorization: Bearer` header for API requests.

The current UI supports:

- current role/storage status;
- recent task metrics;
- task creation for operator/owner;
- task table and selected agents;
- approval queue;
- owner approve/reject controls;
- recent audit events.

The dashboard uses same-origin API requests and does not use authentication cookies.

## Protected endpoints

Viewer or higher:

```text
GET /api/v1/whoami
GET /api/v1/agents
GET /api/v1/command-center
GET /api/v1/agent-tasks/{task_id}
GET /api/v1/agent-tasks/{task_id}/executions
GET /api/v1/agent-tasks/{task_id}/audit
GET /api/v1/integrations/espocrm/schema/{entity_type}
GET /api/v1/integrations/espocrm/mapping/{entity_type}
```

Operator or higher:

```text
POST /api/v1/agent-tasks
POST /api/v1/agent-tasks/{task_id}/actions/{action_id}/execute
```

Owner only:

```text
POST /api/v1/agent-tasks/{task_id}/actions/{action_id}/decision
```

Public operational endpoints:

```text
GET /health
GET /readyz
GET /command-center
```

`/command-center` is only the static shell; data endpoints remain protected.

## EspoCRM mapping recommendations

Phase 3 can discover the actual EspoCRM entity field schema. Phase 4 adds:

```text
GET /api/v1/integrations/espocrm/mapping/Lead
```

The mapping helper compares discovered fields against conservative aliases for:

- lead name;
- email;
- phone;
- source;
- assigned user;
- status;
- project interest;
- budget;
- intent;
- last contact;
- modified timestamp.

It reports exact/case-insensitive matches and leaves unknown purposes as `missing`. It intentionally does not fuzzy-map unrelated custom fields, because a false field mapping can corrupt downstream sales logic.

Actual NPD field names cannot be finalized in source control without deployment access to the real read-only EspoCRM metadata endpoint. Once `ESPOCRM_URL` and `ESPOCRM_API_KEY` are supplied on the VPS, call the schema and mapping endpoints, review the results, and then pin the accepted mapping in a later production configuration slice.

## Security headers

Agent Hub adds:

- `X-Content-Type-Options: nosniff`;
- `X-Frame-Options: DENY`;
- `Referrer-Policy: no-referrer`;
- `Cache-Control: no-store` on API responses;
- a restrictive Content Security Policy on the Command Center HTML.

## Deliberate limits

Phase 4 does not:

- enable production n8n write actions;
- put EspoCRM write credentials in Agent Hub;
- add public Internet exposure or TLS termination;
- replace static-token RBAC with SSO/OIDC;
- guess unknown NPD custom-field mappings;
- merge PR #9 automatically.

For production Internet exposure, put Agent Hub behind a TLS reverse proxy/VPN and consider OIDC/SSO as the next authentication upgrade.
