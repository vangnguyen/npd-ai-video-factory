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

The workflow has only a Schedule Trigger and one internal Code node HTTP request. It does not read
lead data, contact customers, publish content, mutate Ads/CRM, or call an external alert
provider. Successful execution payload retention is disabled.

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

## Intentional limits

Phase 8.8 does not add external alert delivery, incident tickets, auto-remediation,
provider retries, synthetic leads, CRM/Ads/CMS writes or customer messaging. Provider
probes remain manual in Phase 8.7. A later phase may add owner-approved notification
provider contracts after alert-volume and false-positive evidence is reviewed.
