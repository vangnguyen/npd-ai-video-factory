# Phase 8.7 — Provider Health & Internal Alert Routing

## Outcome

Phase 8.7 turns the accepted Phase 8.6 freshness evidence into an operational,
read-only health surface. It runs bounded aggregate probes for configured CRM,
Meta Ads, GA4 and Social adapters, combines those results with signed-delivery SLO
state, and routes deduplicated alerts only to Command Center and the Agent Hub audit
trail.

This phase does not create a notification service. Zalo, email, PWA, Slack and other
external destinations are intentionally unsupported. It does not schedule provider
retries, mutate source systems or enable the n8n Agent executor.

## Base branch and PR strategy

PR #17 remains draft/unmerged. Phase 8.7 therefore uses a stacked branch:

```text
agent/phase-8-5-lead-intake-attribution
  -> agent/phase-8-6-ingestion-observability (PR #17)
    -> agent/phase-8-7-provider-health-alerting (new draft PR)
```

No earlier PR is merged automatically. If the owner later merges the parent PRs,
Phase 8.7 can be rebased onto `main` as an independent review decision.

## Architecture

```text
configured read-only adapters                 signed delivery store
CRM / Meta Ads / GA4 / Social                 n8n Lead Intake freshness
              \                                  /
               +-- bounded provider probe -------+
                              |
                    ProviderHealthSnapshot
                              |
              deterministic condition + dedupe key
                              |
                    ProviderHealthAlert
                       /              \
             Command Center       Agent Hub audit
```

Only provider state, timestamps, SLO age and pseudonymous receipt references are
persisted. Provider payloads, credentials and raw contact data are not stored in the
health namespace.

## Health states

| State | Meaning | Internal alert |
|---|---|---|
| `healthy` | Bounded read probe succeeded or signed delivery is within SLO | none |
| `degraded` | Configuration is incomplete | warning |
| `stale` | Required signed delivery exceeded SLO | critical |
| `no_data` | Configured/required source has no accepted evidence | warning |
| `not_configured` | Credential/adapter is intentionally absent | none |
| `failed` | Bounded read-only probe failed | critical |

`not_configured` is visible but does not page. This prevents false incidents for
provider contracts that are intentionally absent.

## Alert lifecycle

```text
condition appears -> open -> acknowledged
condition clears  -> resolved
resolved + recurrence -> open (occurrence_count + 1)
```

The deterministic dedupe key is `provider_health:{provider}:{condition}`. Repeated
refreshes update the last-seen time rather than creating alert storms. Acknowledge is
an operator-level internal audit action; it does not claim remediation. Resolution is
automatic only when the observed condition clears.

## API and RBAC

| Route | Role | Effect |
|---|---|---|
| `GET /api/v1/provider-health/status` | viewer | Read latest snapshot and active alerts |
| `POST /api/v1/provider-health/refresh` | operator | Run bounded read-only probes and sync internal alerts |
| `GET /api/v1/provider-health/alerts` | viewer | Filter persisted alert history |
| `POST /api/v1/provider-health/alerts/{id}/acknowledge` | operator | Record an internal acknowledgement |

The acknowledge contract includes an expected status so stale UI actions fail with
HTTP 409 rather than overwriting a newer alert state.

## Persistence

The existing store abstraction is extended with:

```text
{AGENT_REDIS_NAMESPACE}:provider-health:snapshot:*
{AGENT_REDIS_NAMESPACE}:provider-health:snapshots
{AGENT_REDIS_NAMESPACE}:provider-health:alert:*
{AGENT_REDIS_NAMESPACE}:provider-health:alerts
```

This remains separate from `npd:video-jobs:*` and survives Agent Hub restarts.
fakeredis tests cover snapshot/alert recovery and namespace separation.

## Tool policy

- `provider.health.read`: read;
- `provider.health.refresh`: read;
- `provider.alert.acknowledge`: planning-only internal draft;
- all Ads launch/budget, CRM write, content publishing and customer-contact tools stay
  disabled and approval-gated.

## Acceptance

Phase 8.7 acceptance requires:

1. configured read-only providers report `healthy` when bounded probes succeed;
2. Phase 8.6 `n8n_lead_intake` evidence reports `fresh`;
3. stale/no-data/failed conditions create one deduplicated alert;
4. repeated refresh does not create duplicate alerts;
5. operator acknowledge writes only Agent Hub state/audit;
6. a cleared condition auto-resolves and a later recurrence reopens the same alert;
7. Redis recovery retains snapshots and alerts after restart;
8. external notifications and production writes remain disabled;
9. existing Phase 1–8.6 regression remains green.

## Rollout gates

1. Keep Phase 8.7 stacked on draft PR #17; do not merge automatically.
2. Pass Agent Hub CI, Phase 5 Deployment Bundle CI and Sprint 1 Docker E2E.
3. Back up the Agent Hub env file, Redis namespace and rollback image.
4. Deploy only Agent Hub in the existing production stack.
5. Run authenticated localhost/public status and refresh smoke.
6. Verify no Caddy, n8n, CRM, Redis or video service restart.
7. Do not enable external alert targets.

## Intentional limits and next step

Phase 8.7 is manual/on-demand provider probing and internal alert handling. It does not
run a scheduler, deliver notifications, retry failed providers, open tickets, change
credentials or remediate incidents. A later phase may add owner-approved scheduling
and notification-provider contracts, but only after alert-volume and false-positive
evidence is reviewed. External delivery must remain disabled by default and require a
separate approval/security design.
