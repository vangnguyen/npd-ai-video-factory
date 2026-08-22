# Phase 8.8 — Lead Intake Heartbeat & Scheduled Health Evaluation

## Outcome

Phase 8.8 separates pipeline liveness from lead volume. n8n emits a PII-free heartbeat
every five minutes even when no lead arrives. Agent Hub signs and persists the heartbeat,
uses it as the primary freshness evidence, and retains the latest real lead-delivery age
as a separate activity metric.

An Agent Hub scheduler re-evaluates cached provider state and heartbeat freshness every
five minutes. It does not call Meta, GA4, Social or CRM, retry delivery, send a message,
or mutate any source system. Alerts remain internal to Command Center and Agent Hub audit.

## Branch strategy

Phase 8.8 is stacked on draft PR #18:

```text
agent/phase-8-6-ingestion-observability (PR #17)
  -> agent/phase-8-7-provider-health-alerting (PR #18)
    -> agent/phase-8-8-heartbeat-scheduled-health (new draft PR)
```

No parent PR is merged automatically.

## Architecture

```text
n8n Schedule Trigger (5 minutes)
  -> internal HTTP POST, operator RBAC
  -> PII-free AttributionProducerHeartbeat
  -> immutable HMAC AttributionHeartbeatReceipt
  -> Agent Hub Redis heartbeat namespace

Agent Hub scheduler (5 minutes, Redis lease)
  -> cached provider observations only
  -> heartbeat freshness evaluation
  -> deduplicated internal alert lifecycle
  -> Command Center + Agent Hub audit only
```

The scheduler runs inside Agent Hub so a stopped n8n container cannot suppress stale
detection. A Redis lease prevents duplicate evaluation when more than one Agent Hub
process is present.

## Heartbeat contract

Required fields:

- `heartbeat_id`: unique pseudonymous identifier;
- `producer`: `n8n_lead_intake`;
- `emitted_at`: producer timestamp;
- `sequence`: strictly increasing producer sequence, using epoch milliseconds in n8n;
- `metadata`: bounded operational labels only;
- `external_writes_enabled`: always `false`.

The contract rejects raw/camelCase PII keys, secret-like values, enabled write flags,
heartbeats more than five minutes in the future, heartbeats older than 24 hours, reused
IDs with changed payloads, and non-increasing sequences. The receipt is signed with the
existing attribution receipt key; no signing key is exposed to n8n.

## Freshness semantics

| Evidence | Health calculation | Activity visibility |
|---|---|---|
| heartbeat exists | heartbeat receipt age | real delivery age remains visible separately |
| heartbeat absent | successful delivery age fallback | explicitly labeled `delivery_fallback` |
| neither exists | `no_data` | no fabricated activity |

This prevents a quiet lead period from being treated as an n8n outage after the first
accepted heartbeat. A stale heartbeat still opens the same deduplicated critical alert.

## API and RBAC

| Route | Role | Effect |
|---|---|---|
| `POST /api/v1/attribution/deliveries/heartbeats` | operator | Accept PII-free heartbeat and issue signed receipt |
| `GET /api/v1/attribution/deliveries/heartbeats` | viewer | Read bounded receipt history |
| `POST /api/v1/attribution/deliveries/heartbeats/verify` | viewer | Verify receipt signature |
| `GET /api/v1/provider-health/scheduler` | viewer | Read scheduler/lease status |
| `POST /api/v1/provider-health/evaluate` | operator | Run one cached-state-only evaluation |

Heartbeat ingestion triggers an immediate cached evaluation so an existing false stale
alert resolves without waiting for the next scheduler interval.

## Persistence

New keys remain inside the existing Agent Hub namespace:

```text
{AGENT_STORE_NAMESPACE}:attribution-os:heartbeat-receipt:*
{AGENT_STORE_NAMESPACE}:attribution-os:heartbeat-receipts
{AGENT_STORE_NAMESPACE}:provider-health:scheduler:status
{AGENT_STORE_NAMESPACE}:provider-health:scheduler:lease
```

No key is written to `npd:video-jobs:*` or Redis DB 0 video-job state.
Heartbeat receipt retention is capped at 5,000 records (roughly 17 days at five-minute
cadence) so the operational signal cannot grow the shared Agent Hub namespace without
bound. Attribution audit remains the lifecycle evidence surface.

## n8n workflow contract

`workflows/n8n/phase-8-8-lead-intake-heartbeat.json` is inactive in source control and
contains no credential value. It reuses `NPD_AGENT_HUB_ATTRIBUTION_URL` and
`NPD_AGENT_HUB_ATTRIBUTION_TOKEN`, the same environment contract already used by the
accepted lead-intake delivery workflow. Activate only after Agent Hub v0.12.8 is healthy
and the first manual execution returns a signed receipt.

The workflow has a Schedule Trigger, an internal Execute Workflow Trigger used only for
pre-activation CLI acceptance, and one internal Code node HTTP request. It has no webhook
or public trigger. It does not read lead data, contact customers, publish content, mutate
Ads/CRM, or call an external alert provider. Successful execution payload retention is
disabled.

## Configuration

```dotenv
AGENT_PROVIDER_HEALTH_SCHEDULER_ENABLED=false
AGENT_PROVIDER_HEALTH_SCHEDULER_INTERVAL_SECONDS=300
```

Source control defaults to disabled. Production enablement requires backup, CI, workflow
credential binding and manual heartbeat acceptance. The scheduler itself performs only
cached internal evaluation.

## Acceptance gates

1. HMAC heartbeat receipt verifies and is idempotent.
2. PII/write flags, replay, changed payload and non-increasing sequence are rejected.
3. A fresh heartbeat resolves delivery-fallback stale while preserving lead activity age.
4. A missing/stale heartbeat reopens one deduplicated internal alert.
5. Scheduler state and heartbeat receipts recover from Redis.
6. Redis lease prevents duplicate scheduler execution.
7. External provider probes, notifications and production writes remain disabled.
8. Inactive workflow template contains no secrets and no customer/source-system action.
9. Agent Hub, Phase 5 bundle and Sprint 1 Docker E2E regression pass.
10. Production cutover restarts only Agent Hub; n8n workflow activation is separately
    backed up and audited.

## Production operations runbook

### Validate and import

Run the repository gate before touching production. It statically rejects active source
workflows and likely inline credentials, then imports every workflow into an isolated,
ephemeral n8n 2.33.7 container:

```bash
bash scripts/ci/validate-n8n-workflows.sh
```

Before import, back up the `n8n-marketing` PostgreSQL database and record the currently
active workflow IDs. Import the JSON with `--activeState=false`; import must never make a
schedule live implicitly. The source file remains inactive.

Perform one manual execution before publication. On the production n8n host the manual
CLI acceptance may need a temporary, non-production task-runner broker port to avoid the
already-running container port:

```bash
N8N_RUNNERS_BROKER_PORT=5680 n8n execute \
  --id=fd262c48-24c0-4ee3-a20a-09f2a417de88
```

Acceptance requires a signed Agent Hub receipt and no PII. Publish the workflow from the
n8n UI only after that receipt verifies. Confirm that exactly one workflow with the
Phase 8.8 ID is published and that the existing Lead Intake workflow stays active and
unchanged. Publishing does not authorize any Ads, CRM, CMS or customer-contact action.

### Unpublish and rollback

If the receipt is missing, the cadence is wrong, or alerts become noisy:

1. unpublish `NPD Phase 8.8 - Lead Intake Heartbeat` in the n8n UI;
2. confirm no new scheduled receipt arrives after one interval plus clock tolerance;
3. keep the historical signed receipts and alert audit intact;
4. restore the previous Agent Hub image/config only if the Agent Hub change is the cause;
5. restore the n8n database only as an explicit last resort after a new backup—never as
   an automatic step.

No n8n, Caddy, Redis or database container restart is required for normal workflow
unpublish. Record each action and exact workflow ID in the deployment receipt.

### Diagnose n8n executions safely

n8n can retain soft-deleted rows whose `status` still reads `running`, particularly when
successful execution persistence is disabled. They are not active jobs. Audit only rows
whose `deletedAt` is null:

```sql
SELECT id, status, "workflowId", "startedAt", "stoppedAt", "deletedAt"
FROM execution_entity
WHERE "deletedAt" IS NULL
  AND status IN ('new', 'running', 'waiting')
ORDER BY "startedAt" DESC;
```

Do not delete or rewrite execution rows during diagnosis. Correlate any returned ID with
n8n logs and workflow state before deciding that an execution is stuck.

## Command Center operational signals

Command Center deliberately renders four different facts:

- latest PII-free heartbeat receipt;
- latest real lead activity age;
- latest cached-only scheduler completion;
- incident timeline from detection through resolution, including duration.

When heartbeat is fresh but lead activity is older than the SLO target, the UI says
`Pipeline đang sống · chưa có lead mới ...`. This is an informational operating verdict,
not a synthetic lead, an alert, or proof that marketing should be changed.

## 48-hour acceptance report

At a five-minute cadence, a complete 48-hour window has 576 expected intervals. Use the
read-only report helper; pass a token only through the environment and never in a command
argument or report file:

```bash
export NPD_AGENT_HUB_TOKEN="$AGENT_VIEWER_TOKEN"
python3 scripts/phase8/report-heartbeat-acceptance.py \
  --base-url http://127.0.0.1:8010 \
  --window-hours 48 \
  --output phase-8-8-acceptance-48h.json
unset NPD_AGENT_HUB_TOKEN
```

The helper reports observed coverage separately from the requested window, so an early
partial run cannot be mistaken for a completed 48-hour acceptance. The owner gate is:

| Signal | Acceptance evidence |
|---|---|
| heartbeat success | full window, receipt count/rate and signed latest receipt |
| max gap | no unexplained gap beyond one interval plus agreed clock/runtime tolerance |
| scheduler jitter | last completion and lag beyond configured interval |
| alert quality | open/resolved count; manually classify every incident/false positive |
| recovery | maximum detection-to-resolution duration |
| quiet lead period | pipeline liveness remains separate from lead activity |
| Redis growth | namespace bytes before/after and capped heartbeat retention |
| resource impact | Agent Hub/n8n restart count, CPU and memory before/after |
| safety | cached-only scheduler true; external probes/notifications/write all false |

Redis byte values are optional report inputs because the API intentionally does not expose
Redis internals. Capture namespace-only baseline/current values on the host, then provide
them with `--redis-baseline-bytes` and `--redis-current-bytes`. Do not scan or modify video
job keys or Redis DB 0.

## Next staged scope

Phase 8.9 may add severity routing, dedupe windows, cooldown, escalation policy and
notification preview/dry-run. External email, Zalo, PWA or ticket delivery remains disabled
until the 48-hour evidence is reviewed and the owner explicitly approves a provider and
least-privilege credential.

## Intentional limits

Phase 8.8 does not add external alert delivery, incident tickets, auto-remediation,
provider retries, synthetic leads, CRM/Ads/CMS writes or customer messaging. Provider
probes remain manual in Phase 8.7. A later phase may add owner-approved notification
provider contracts after alert-volume and false-positive evidence is reviewed.
