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

## Files added for Phase 5

- `deploy/phase5/docker-compose.agent-hub.prod.yml`
- `deploy/phase5/agent-hub.env.example`
- `deploy/phase5/Caddyfile.agent-hub.example`
- `scripts/phase5/preflight.sh`
- `scripts/phase5/deploy.sh`
- `scripts/phase5/smoke.sh`
- `scripts/phase5/backup.sh`
- `scripts/phase5/rollback.sh`
- `npd_agent_hub.maintenance` backup/restore CLI
- `.github/workflows/phase5-deploy-bundle-ci.yml`

## Required VPS state

The existing stack must already provide Docker containers named/identified as API and Redis on the Docker network used by the video factory. The default expected network is:

```text
npd-ai-video-factory_default
```

Override it with `NPD_DOCKER_NETWORK` if the existing Compose project uses another network name.

Required host commands:

```text
docker
docker compose
git
curl
python3
caddy
```

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
bash scripts/phase5/preflight.sh
```

Preflight fails closed when:

- required software is missing;
- env file is missing or has unsafe permissions;
- auth is not `static_token`;
- Redis persistence is not enabled;
- role tokens are short, duplicated, or still placeholders;
- EspoCRM URL/key is missing;
- existing API or Redis is not present on the expected Docker network;
- the Git checkout contains uncommitted changes;
- production Compose cannot render.

## Deployment and backup

Deploy with:

```bash
export AGENT_HUB_ENV_FILE=/etc/npd-ai/agent-hub.env
export NPD_DOCKER_NETWORK=npd-ai-video-factory_default
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

## What the smoke test verifies

The smoke test does not execute any external write action.

It verifies:

- `/health` and `/readyz`;
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

Use the existing VPS Caddy instance. Do not start another Caddy container.

Take the site block from:

```text
deploy/phase5/Caddyfile.agent-hub.example
```

Replace `agent-hub.example.invalid` with the already-approved hostname only. Merge the block into the existing Caddy configuration according to the current VPS layout.

Validate before reload:

```bash
sudo caddy fmt --overwrite /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Do not reload Caddy if validation fails.

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

## Observability

Container status:

```bash
docker compose -f deploy/phase5/docker-compose.agent-hub.prod.yml ps
```

Agent Hub logs:

```bash
docker compose -f deploy/phase5/docker-compose.agent-hub.prod.yml logs --tail=200 agent-hub
```

Caddy access log configured by the example site block:

```text
/var/log/caddy/npd-agent-hub-access.log
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

## Phase 5 acceptance criteria

Phase 5 is deployment-ready when all are true:

- Phase 5 Deployment Bundle CI is green;
- Agent Hub CI is green;
- existing API/worker/renderer regression is green;
- production preflight passes on the VPS;
- Agent Hub becomes healthy on loopback;
- local smoke passes;
- Caddy configuration validates and reloads;
- public HTTPS smoke passes;
- real EspoCRM Lead schema/mapping smoke passes;
- deployment receipt and rollback image exist after an upgrade;
- no production write workflow has been activated as part of this phase.
