# Phase 5 — Agent Hub Production Deployment

## Goal

Deploy the Phase 4 Agent Hub to the existing NPD VPS without disrupting the current video factory, Redis/video jobs, EspoCRM, or the existing n8n instance.

Phase 5 invariants:

- do not start a second n8n container;
- do not replace the existing Caddy instance;
- do not change the already-approved domain/hostname as part of deployment;
- Agent Hub binds only to `127.0.0.1:8010` on the VPS;
- public HTTPS terminates at the existing Caddy service;
- Agent Hub uses Redis DB 1 / namespace `npd:agent-hub:v1`; video jobs remain on Redis DB 0;
- EspoCRM credential is a read-only API user;
- write workflows remain inactive/dry-run until separately approved.

## Verified production topology

The following values were verified by a read-only VPS audit on 2026-08-20 and are the Phase 5 defaults:

| Purpose | Production value |
|---|---|
| VPS / SSH | `root@157.10.201.169` with the fixed verified host key |
| Video Factory checkout | `/opt/npd-ai-video-factory` |
| Video API / Redis network | `npd-ai-video-factory_default` |
| Video API / Redis aliases | `api`, `redis` |
| n8n Compose file | `/opt/n8n/docker-compose.yml` |
| n8n Compose project | `n8n-marketing` |
| n8n / Caddy network | `n8n-marketing_n8n_net` |
| Caddy container | `n8n-marketing-caddy-1` |
| Host Caddyfile | `/opt/n8n/Caddyfile` |
| Caddy container config | `/etc/caddy/Caddyfile` (read-only bind mount) |

Agent Hub joins both existing networks. It reaches the video API and Redis through `api`/`redis`, while the existing Caddy container reaches Agent Hub through the `npd-agent-hub` alias. The loopback port remains available only on the host for local smoke. A Caddy container must not proxy `127.0.0.1:8010`, because that address is the Caddy container's own loopback.

## Files added for Phase 5

- `deploy/phase5/docker-compose.agent-hub.prod.yml`
- `deploy/phase5/agent-hub.env.example`
- `deploy/phase5/Caddyfile.agent-hub.example`
- `scripts/phase5/preflight.sh`
- `scripts/phase5/deploy.sh`
- `scripts/phase5/smoke.sh`
- `scripts/phase5/backup.sh`
- `scripts/phase5/rollback.sh`
- `scripts/phase5/caddy-cutover.sh`
- `scripts/phase5/remote-deploy.ps1`
- `npd_agent_hub.maintenance` backup/restore CLI
- `.github/workflows/phase5-deploy-bundle-ci.yml`

## Required VPS state

The existing video stack must provide API and Redis on:

```text
npd-ai-video-factory_default
```

The existing Caddy service must remain in project `n8n-marketing` on:

```text
n8n-marketing_n8n_net
```

Override these only after a fresh read-only audit with `NPD_DOCKER_NETWORK` and `N8N_DOCKER_NETWORK`.

Required host commands:

```text
docker
docker compose
git
curl
python3
```

The host does not need a Caddy binary. Validation, formatting, reload and rollback use `docker exec n8n-marketing-caddy-1 caddy ...` against the existing container.

Do not deploy Agent Hub if the existing API/Redis services are unhealthy.

## Production secrets

Create the production env file outside the repository:

```bash
sudo mkdir -p /etc/npd-ai
sudo cp deploy/phase5/agent-hub.env.example /etc/npd-ai/agent-hub.env
sudo chmod 600 /etc/npd-ai/agent-hub.env
```

Generate three independent tokens. Example:

```bash
openssl rand -hex 32
openssl rand -hex 32
openssl rand -hex 32
```

Assign them separately to:

```text
AGENT_VIEWER_TOKEN
AGENT_OPERATOR_TOKEN
AGENT_OWNER_TOKEN
```

Do not reuse tokens between roles and do not commit them.

Browser access uses a dedicated Google Web OAuth client while bearer tokens remain available
for smoke tests and automation. Configure the client with:

```text
Authorized JavaScript origin: https://mkt.ngocphuongdong.com
Authorized redirect URI: https://mkt.ngocphuongdong.com/auth/google/callback
```

Then set the following outside the repository. `AGENT_OWNER_EMAILS` is an exact,
case-normalized allowlist; a successful Google login does not grant access unless the email is
listed:

```text
AGENT_BROWSER_AUTH_MODE=google_oidc
AGENT_PUBLIC_BASE_URL=https://mkt.ngocphuongdong.com
AGENT_GOOGLE_CLIENT_ID=...
AGENT_GOOGLE_CLIENT_SECRET=...
AGENT_SESSION_SIGNING_KEY=<independent-random-value-at-least-32-characters>
AGENT_SESSION_TTL_SECONDS=28800
AGENT_OWNER_EMAILS=nguyenvanvangct@gmail.com
AGENT_OPERATOR_EMAILS=
AGENT_VIEWER_EMAILS=
```

The browser receives only a signed `HttpOnly`, `Secure`, `SameSite=Lax` session cookie. The
OAuth code, client secret and bearer tokens are never stored in browser storage. Cookie-authenticated
write requests must carry the exact configured same-origin `Origin` header.

Configure the existing EspoCRM host and a read-only API-user key:

```text
ESPOCRM_URL=...
ESPOCRM_API_KEY=...
```

Phase 5 preflight intentionally requires EspoCRM configuration because the acceptance smoke test verifies the real `Lead` schema and mapping endpoint.

Keep this empty unless the production n8n write executor has been reviewed and intentionally enabled:

```text
N8N_AGENT_EXECUTOR_WEBHOOK_URL=
```

## Preflight

From a clean checkout of the target commit:

```bash
export AGENT_HUB_ENV_FILE=/etc/npd-ai/agent-hub.env
export NPD_DOCKER_NETWORK=npd-ai-video-factory_default
export N8N_DOCKER_NETWORK=n8n-marketing_n8n_net
export N8N_COMPOSE_FILE=/opt/n8n/docker-compose.yml
export N8N_COMPOSE_PROJECT=n8n-marketing
export N8N_CADDY_CONTAINER=n8n-marketing-caddy-1
export N8N_CADDYFILE=/opt/n8n/Caddyfile
bash scripts/phase5/preflight.sh
```

Preflight fails closed when:

- required software is missing;
- env file is missing or has unsafe permissions;
- API auth is not `static_token` or browser auth is not `google_oidc`;
- Redis persistence is not enabled;
- role tokens are short, duplicated, or still placeholders;
- Google OAuth, public HTTPS origin, session signing key or owner email allowlist is missing;
- EspoCRM URL/key is missing;
- existing API or Redis is not present on the expected Docker network;
- the production `n8n-marketing` Compose file, network or Caddy container does not match the verified topology;
- `/opt/n8n/Caddyfile` is not the file mounted at `/etc/caddy/Caddyfile`;
- current Caddy configuration fails validation inside `n8n-marketing-caddy-1`;
- the Git checkout contains uncommitted changes;
- production Compose cannot render.

## Deployment and backup

Deploy with:

```bash
export AGENT_HUB_ENV_FILE=/etc/npd-ai/agent-hub.env
export NPD_DOCKER_NETWORK=npd-ai-video-factory_default
export N8N_DOCKER_NETWORK=n8n-marketing_n8n_net
bash scripts/phase5/deploy.sh
```

If an Agent Hub deployment already exists, the script first:

1. tags its current image as `npd-agent-hub:rollback-<timestamp>`;
2. exports only the Agent Hub Redis namespace to `/var/backups/npd-agent-hub/`;
3. builds the new image;
4. recreates only the Agent Hub container;
5. waits for Docker health to become healthy;
6. runs the Phase 5 smoke test;
7. writes a deployment receipt to `/var/lib/npd-ai/agent-hub-deployments/`.

No Redis restore occurs automatically on deployment failure. An image rollback is attempted, but state restore is always an explicit operator decision.

Deployment only recreates `agent-hub`. It does not run `docker compose up` against `/opt/n8n/docker-compose.yml` and does not recreate n8n, Caddy, Redis, API, worker or renderer.

## Guarded SSH helper

From the handoff workspace on Windows, use the verified key and fixed known-hosts file. The helper always sets `StrictHostKeyChecking=yes` and `BatchMode=yes`; it never falls back to the global `known_hosts` file.

Read-only audit:

```powershell
pwsh -File scripts/phase5/remote-deploy.ps1 `
  -Action Audit `
  -SshKeyPath work/n8n-vps/codex_n8n_vps_ed25519 `
  -KnownHostsPath work/n8n-vps/known_hosts_test
```

Preflight requires the exact reviewed 40-character commit but does not change production:

```powershell
pwsh -File scripts/phase5/remote-deploy.ps1 `
  -Action Preflight `
  -ExpectedCommit <reviewed-pr-9-head> `
  -SshKeyPath work/n8n-vps/codex_n8n_vps_ed25519 `
  -KnownHostsPath work/n8n-vps/known_hosts_test
```

Every deploy, Caddy, smoke or rollback action additionally requires the literal `-Confirm PHASE5_REMOTE_CHANGE`. The helper refuses to continue when the remote commit differs, tracked changes exist, required parameters contain unsafe characters, or strict host verification fails. It intentionally does not fetch, switch or pull the VPS checkout; synchronization to the reviewed commit is a separate operator step so runtime directories are not overwritten.

## What the smoke test verifies

The smoke test does not execute any external write action.

It verifies:

- `/health` and `/readyz`;
- unauthenticated browser access redirects to `/login`;
- `/login` exposes Google login and the OAuth start redirects only to Google;
- unauthenticated API access is rejected;
- viewer can read Command Center;
- owner token resolves as `owner`;
- operator can create a test task;
- operator cannot approve/reject an owner-only action;
- owner can reject the test `social.publish` action;
- EspoCRM `Lead` schema discovery works against the configured real CRM;
- EspoCRM conservative field mapping works;
- discovered Lead schema contains at least one field.

The test owner action is **rejected**, never executed, so it cannot publish content, spend ads, message customers, or write CRM data.

## Caddy / HTTPS cutover

Agent Hub is intentionally not exposed directly. Its Compose port is loopback-only:

```text
127.0.0.1:8010 -> container:8010
```

Use the existing `n8n-marketing-caddy-1` container. Do not start another Caddy container and do not use `systemctl`.

Take the site block from:

```text
deploy/phase5/Caddyfile.agent-hub.example
```

The site block proxies to `npd-agent-hub:8010` on `n8n-marketing_n8n_net`. Replace `agent-hub.example.invalid` with the already-approved hostname only.

Guarded apply:

```bash
export AGENT_HUB_HOSTNAME=<already-approved-hostname>
bash scripts/phase5/caddy-cutover.sh --apply --confirm APPLY_CADDY
```

The script:

1. rejects a placeholder, duplicate hostname or duplicate managed block;
2. backs up `/opt/n8n/Caddyfile` as `/opt/n8n/Caddyfile.before-agent-hub-<timestamp>`;
3. copies the candidate into `n8n-marketing-caddy-1`;
4. runs `caddy fmt` and `caddy validate` inside that container;
5. writes the validated candidate back to `/opt/n8n/Caddyfile` **in place** so the read-only bind mount keeps the same inode;
6. validates `/etc/caddy/Caddyfile` and runs `caddy reload` inside the existing container;
7. restores the backup in place and reloads it if apply fails.

Manual read-only validation is:

```bash
docker exec n8n-marketing-caddy-1 \
  caddy validate --config /etc/caddy/Caddyfile
```

After HTTPS is live, run smoke again against the public hostname:

```bash
export AGENT_HUB_ENV_FILE=/etc/npd-ai/agent-hub.env
export AGENT_HUB_PUBLIC_URL=https://<already-approved-hostname>
bash scripts/phase5/smoke.sh
```

Caddy is responsible for certificate issuance/renewal. Agent Hub itself does not terminate TLS.

## Firewall / exposure

Expected exposure:

- `80/443`: existing Caddy only;
- `8010`: loopback only, not public;
- Redis: not public;
- Video API/renderer: retain their existing exposure policy; Phase 5 does not open additional ports;
- n8n: retain the existing deployment; Phase 5 does not create a second n8n.

## Backup

Manual Agent Hub state backup:

```bash
export AGENT_HUB_ENV_FILE=/etc/npd-ai/agent-hub.env
bash scripts/phase5/backup.sh
```

The backup contains only keys under the configured Agent Hub namespace. It does not export Redis DB 0 video-job state.

Backup files are written with mode `0600` because task context and audit data are internal operational data.

## Rollback

Every upgrade receipt records the rollback image tag and backup path.

Image-only rollback:

```bash
bash scripts/phase5/rollback.sh --image npd-agent-hub:rollback-<timestamp>
```

This is the default rollback because it preserves all current Agent Hub state.

Only if state itself must be reverted, explicitly provide a backup:

```bash
bash scripts/phase5/rollback.sh \
  --image npd-agent-hub:rollback-<timestamp> \
  --backup /var/backups/npd-agent-hub/agent-hub-<timestamp>.json
```

The restore CLI requires the literal confirmation `RESTORE_AGENT_HUB` internally and refuses namespace mismatches. It deletes/replaces only the Agent Hub namespace, never unrelated Redis keys.

Caddy rollback uses the exact backup emitted by `caddy-cutover.sh`:

```bash
bash scripts/phase5/caddy-cutover.sh \
  --rollback /opt/n8n/Caddyfile.before-agent-hub-<timestamp> \
  --confirm ROLLBACK_CADDY
```

The rollback candidate is validated inside `n8n-marketing-caddy-1` before the live host file is changed. A second safety backup of the pre-rollback Caddyfile is created. The Agent Hub image rollback now runs the complete loopback smoke before reporting success. Redis state restore remains optional and explicit.

## Observability

Container status:

```bash
docker compose -f deploy/phase5/docker-compose.agent-hub.prod.yml ps
```

Agent Hub logs:

```bash
docker compose -f deploy/phase5/docker-compose.agent-hub.prod.yml logs --tail=200 agent-hub
```

Caddy access logs use container stdout and the existing Docker logging policy:

```bash
docker logs --tail=200 n8n-marketing-caddy-1
```

Application operational history remains available through the authenticated Command Center audit endpoints and Redis persistence.

## Live EspoCRM mapping handoff

After production smoke succeeds, review:

```text
GET /api/v1/integrations/espocrm/schema/Lead
GET /api/v1/integrations/espocrm/mapping/Lead
```

using a viewer/owner bearer token.

Conservative mapping deliberately leaves unknown custom fields as `missing`. Do not enable CRM write automation merely because a field name looks similar. Real NPD custom-field mapping should be reviewed and recorded before any write workflow is activated.

## Current live status (accepted 2026-08-20)

- The primary `/opt/npd-ai-video-factory` production-pilot checkout remains unchanged at `a92785dc1721ec4e991bf12655629d809e13c241`; its untracked `.runtime/` and `production-pilot-artifacts/` directories were preserved.
- The reviewed Phase 5 commit was checked out separately at `/opt/npd-ai-video-factory-phase5` so deployment did not switch or overwrite the production-pilot worktree.
- `/etc/npd-ai/agent-hub.env` exists with mode 600 and independent viewer/operator/owner tokens. The n8n executor webhook remains empty.
- EspoCRM API user `agent-hub-readonly` has a dedicated `Agent Hub Read Only` role. `Lead` read is allowed; create, edit, delete and stream are denied. `App/user`, `Metadata` and a real Lead read all returned HTTP 200.
- Agent Hub is the only service in Compose project `npd-agent-hub-prod`, is healthy, joins `npd-ai-video-factory_default` and `n8n-marketing_n8n_net`, and exposes only `127.0.0.1:8010` on the host.
- Local smoke passed viewer/operator/owner RBAC and real EspoCRM schema/mapping discovery with 60 Lead fields. The smoke action was rejected and caused no external execution.
- `mkt.ngocphuongdong.com` resolves to `157.10.201.169`. DNS propagation was accepted only after three consecutive 30-query samples returned the VPS address with no stale Cloudflare answers.
- Caddy was backed up, validated and reloaded inside `n8n-marketing-caddy-1`. The live proxy target is `npd-agent-hub:8010`, and HTTPS `/readyz` returns HTTP 200 with a valid public certificate.
- Public HTTPS smoke passed the complete RBAC and real EspoCRM schema/mapping suite.
- Image rollback was exercised with `npd-agent-hub:accepted-1aa06dd` and passed loopback smoke. Caddy rollback was exercised from `/opt/n8n/Caddyfile.before-agent-hub-20260820T034702Z`, then the public route was re-applied and public smoke passed again.
- Google browser login was activated with a dedicated Web OAuth client limited to `openid email profile`. The exact allowlist maps `nguyenvanvangct@gmail.com` to `owner`; the Google Auth project remains in Testing with that account already registered as a test user.
- Agent Hub `0.6.0` was deployed from commit `d17a65d` after preflight. Public `/command-center` redirected to `/login`, Google callback created the secure session, and the live page displayed `nguyenvanvangct@gmail.com · owner` with Redis-backed data.
- The login upgrade passed public bearer-token RBAC and real EspoCRM smoke with 60 Lead fields. Its rollback image is `npd-agent-hub:rollback-20260820T043019Z`, namespace backup is `/var/backups/npd-agent-hub/agent-hub-20260820T043019Z.json`, and deployment receipt is `/var/lib/npd-ai/agent-hub-deployments/deploy-20260820T043019Z.json`.

Recorded recovery artifacts:

- EspoCRM RBAC backup: `/var/backups/npd-agent-hub/espocrm-rbac-20260820T031230Z.sql.gz`;
- Agent Hub namespace backup: `/var/backups/npd-agent-hub/agent-hub-20260820T031438Z.json`;
- first Caddy pre-cutover backup: `/opt/n8n/Caddyfile.before-agent-hub-20260820T034702Z`;
- Caddy pre-rollback safety backup: `/opt/n8n/Caddyfile.before-agent-hub-rollback-20260820T035732Z`;
- final Caddy pre-reapply backup: `/opt/n8n/Caddyfile.before-agent-hub-20260820T035733Z`.
- pre-login OAuth environment backup: `/var/backups/npd-agent-hub/agent-hub.env.before-google-login-20260820T042858Z`.

No social publish, Ads mutation, customer message, CRM write or Redis restore was executed. This acceptance makes the deployment live, but it does not authorize merging PR #9 or enabling the inactive production-write workflow.

### Business-answer upgrade accepted (Agent Hub 0.7.0, 2026-08-20)

The guarded Agent Hub-only rollout from commit `6be623705a0e53c51be74a667e89114c86534b74` added read-only CRM auto-analysis and an evidence-backed answer panel. Task creation and explicit re-analysis may execute only `crm.leads.read` and `crm.audit.read`; all write actions remain approval-gated and the n8n executor remains inactive/unconfigured. The Lead adapter requests only the business fields needed for triage and removes raw email/phone values before persistence.

Acceptance evidence:

- Agent Hub CI run `32333949233`, Phase 5 Deployment Bundle CI run `32333949253`, and all jobs in Sprint 1 CI run `32333949231` passed, including Docker Compose E2E.
- Guarded preflight passed against `/opt/npd-ai-video-factory-phase5`; the primary `/opt/npd-ai-video-factory` checkout remained unchanged at `a92785dc1721ec4e991bf12655629d809e13c241`.
- Deployment created rollback image `npd-agent-hub:rollback-20260820T050522Z`, namespace backup `/var/backups/npd-agent-hub/agent-hub-20260820T050522Z.json`, and receipt `/var/lib/npd-ai/agent-hub-deployments/deploy-20260820T050522Z.json` before/after the Agent Hub-only replacement as appropriate.
- The resulting single Agent Hub container is healthy, reports version `0.7.0`, remains on `npd-ai-video-factory_default` plus `n8n-marketing_n8n_net`, and Caddy still validates inside `n8n-marketing-caddy-1` without a Caddy configuration change.
- Loopback and public `https://mkt.ngocphuongdong.com` smoke both passed RBAC, Google login route, 60-field EspoCRM discovery, business-answer generation and raw-contact-field persistence checks. Both returned `crm_answer=completed`; smoke write proposals were explicitly rejected and not executed.
- The original user test task `agt_1c55c3f081894ecc` was re-analyzed through the owner browser session. The UI returned 3 checked leads, 3 needing care at the 7-day threshold, 0 high priority, 0 unassigned and 1 missing contact; the old `undefined` Pending display no longer appears.
- The Google owner session still showed `nguyenvanvangct@gmail.com · owner`. The answer panel displayed per-lead reason, business fields and next-best-action while preserving the explicit caveat that activity timestamps are a proxy for last contact.

No Caddy cutover, second n8n/Caddy/Redis service, social publish, Ads mutation, customer message, CRM write or Redis restore occurred in this upgrade. PR #9 remains draft/unmerged.

## Phase 5 acceptance criteria

Repository deployment-bundle readiness requires:

- Phase 5 Deployment Bundle CI is green;
- Agent Hub CI is green;
- existing API/worker/renderer/Sprint 1 regression is green.

Production-live acceptance additionally requires:

- production preflight passes on the VPS;
- Agent Hub becomes healthy on loopback;
- local smoke passes;
- Caddy configuration validates and reloads;
- public HTTPS smoke passes;
- allowlisted Google owner login completes through the production callback and `/api/v1/whoami` returns the exact email with role `owner`;
- real EspoCRM Lead schema/mapping smoke passes;
- deployment receipt and rollback image exist after an upgrade;
- no production write workflow has been activated as part of this phase.
