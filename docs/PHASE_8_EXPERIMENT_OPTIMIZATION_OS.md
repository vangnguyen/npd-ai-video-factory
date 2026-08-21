# Phase 8 — Experiment & Optimization OS

## Goal and safety boundary

Phase 8 turns owner-accepted Phase 7 attribution evidence into controlled experiment
plans. It records hypotheses, variants, primary metrics, guardrails, stop conditions,
preview packages and provenance-bound read-only observations. The current mode is
`plan_preview_observe`.

Phase 8 does not allocate live traffic, change Ads budgets, publish landing pages,
contact customers, write CRM records or start n8n production executors. Approving an
experiment approves only its plan. There is intentionally no execute API.

## Branch strategy

Phase 8 is implemented on `agent/phase-8-experiment-optimization-os` as a stacked
branch based on the head of draft PR #13 (`agent/phase-7-campaign-id-baseline`). PR #13
remains independently reviewable and unmerged. If PR #13 later merges, Phase 8 must be
rebased onto the resulting `main` before its own merge review.

## Architecture

```text
owner-accepted Attribution reconciliation
                 |
                 v
Campaign coverage validation
                 |
                 v
Experiment plan -- hypothesis / variants / KPI
                 |
                 v
guardrails + stop conditions + deterministic preview
                 |
                 v
read-only observations -- provenance / freshness / sample size
                 |
                 v
advisory recommendation -- winner candidate / continue / stop and review
                 |
                 v
owner review (no execution)
```

`ExperimentService` uses the existing `HubStore` abstraction. An experiment can be
created only when its Campaign exists, its reconciliation state is `quality_accepted`,
and that accepted snapshot covers the Campaign. This prevents optimization plans from
being built on rejected, stale or unrelated revenue evidence.

## Domain model

Each experiment contains:

- an explicit ID such as `EXP-VGP-202609-001`;
- canonical `campaign_id` and accepted `attribution_reconciliation_id`;
- experiment type: creative, audience, landing page, offer or messaging;
- falsifiable hypothesis;
- primary metric, source, direction, baseline and target lift;
- two or more uniquely identified variants whose allocation proposal totals 100%;
- guardrail thresholds and `stop_and_review` actions;
- non-automatic stop conditions;
- evaluation window and owner;
- audit timestamps, approval decision and the latest preview;
- up to 100 normalized observations with source system, snapshot ID, window,
  collection timestamp, source quality, sample size and conversion counts;
- latest evaluation with freshness, sample sufficiency, two-proportion p-value,
  target-lift comparison and guardrail breaches;
- immutable safety flags showing execution and external writes are disabled.

Secrets are forbidden in Experiment objects and audit metadata. Observation payloads
also reject raw PII, external-write flags, unknown/duplicate variants and impossible
time windows. A `verified_read_only` snapshot must cover every planned variant; a
`partial` snapshot can be retained for diagnosis but cannot produce a winner candidate.

## Lifecycle

```text
planned -> previewed -> awaiting_approval -> approved
                    \-> rejected
```

Draft-safe fields can be updated only while an experiment is `planned` or `previewed`;
an update invalidates its previous preview. Preview is an internal calculation and does
not require approval. Approval is owner-only and still does not unlock execution.
Completed/cancelled execution lifecycle is reserved for a later separately approved
runtime design.

## API and RBAC

| Operation | Endpoint | Minimum role |
|---|---|---|
| OS status | `GET /api/v1/experiments/status` | viewer |
| Create plan | `POST /api/v1/experiments` | operator |
| List/filter | `GET /api/v1/experiments` | viewer |
| Read one | `GET /api/v1/experiments/{id}` | viewer |
| Update draft-safe fields | `PATCH /api/v1/experiments/{id}` | operator |
| Generate preview | `POST /api/v1/experiments/{id}/preview` | operator |
| Request owner review | `POST /api/v1/experiments/{id}/approvals/request` | operator |
| Approve/reject plan | `POST /api/v1/experiments/{id}/approvals/decision` | owner |
| Audit history | `GET /api/v1/experiments/{id}/audit` | viewer |
| Attach normalized read-only observation | `POST /api/v1/experiments/{id}/observations` | operator |
| List observations | `GET /api/v1/experiments/{id}/observations` | viewer |
| Generate advisory evaluation | `POST /api/v1/experiments/{id}/evaluations` | operator |

There is no `/execute` endpoint.

## Read-only evaluation policy

The first planned variant is the control. For conversion observations the service
calculates each variant's conversion rate and a two-sided two-proportion z-test against
the best challenger. Default checks require every variant to have at least 100 samples,
source collection no more than 72 hours old, `verified_read_only` evidence, target lift,
the selected confidence threshold and no guardrail breach.

Passing all checks yields `winner_candidate`, not an automatic winner. Missing samples
yields `insufficient_data`; partial or stale evidence yields `manual_review`; a breached
guardrail or significantly worse challenger yields `stop_and_review`; otherwise the
advisory result is `continue`. Every evaluation is audited and leaves experiment status,
traffic, spend and external systems unchanged.

## Persistence

Memory and Redis stores implement the same contract. Redis uses a dedicated
subnamespace in the existing Agent Hub DB:

```text
{AGENT_REDIS_NAMESPACE}:experiment-os:experiment:*
{AGENT_REDIS_NAMESPACE}:experiment-os:experiments
{AGENT_REDIS_NAMESPACE}:experiment-os:campaign:*:experiments
{AGENT_REDIS_NAMESPACE}:experiment-os:audit:*
```

Video jobs remain in DB 0 and `npd:video-jobs:*` is untouched. Recovery tests use
fakeredis and verify preview, observations, evaluation and audit state after service
restart. Observations and the latest evaluation are embedded in the Experiment document,
so existing Agent Hub namespace backup and rollback procedures cover them.

## Experiment Optimization Agent and tool policy

The new specialist coordinates with Marketing Leader, Revenue Attribution,
Performance Ads and Web & Landing Page. It may create plans and previews only.

Central tool capabilities are:

- `experiment.plan.create`: planning-only;
- `experiment.preview.generate`: planning-only;
- `experiment.observation.read`: read-only;
- `experiment.recommendation.evaluate`: planning-only advisory analysis;
- `experiment.execution.start`: write, requires approval, disabled.

## Command Center workspace

The responsive workspace shows Experiment OS status, accepted-source requirement,
Campaign selection, hypothesis, baseline, target lift, plan cards, preview details,
observation counts and the latest advisory recommendation. Its evidence panel lists
source state, period and per-variant sample sizes without raw PII. Owner approval buttons
explicitly state that approval does not allocate traffic or change production.

## Initial acceptance example

For Vịnh Tiên, the workspace can propose a 50/50 creative-hook test:

- control: current creative;
- variant: benefit-led hook draft;
- primary metric: GA4 form conversion rate;
- baseline: 2.5 percent;
- target lift: 20 percent, preview target 3.0 percent;
- guardrail: qualified-lead CPL at or below 1,500,000 VND;
- evaluation window: 14 days;
- stop condition: two review windows breaching the guardrail;
- live traffic allocation: disabled.

## Tests and rollout gates

Tests cover accepted-attribution gating, Campaign coverage, model validation, preview
math, plan approval RBAC, no execute endpoint, observation RBAC, PII/write rejection,
sample sufficiency, partial-source behavior, two-proportion significance, guardrail
breaches, Memory/Redis recovery, audit order, agent routing, centralized tool policy and
responsive dashboard surfaces.

Before a production rollout:

- Agent Hub CI and business evals must pass;
- Deployment Bundle CI must pass when deployment assets are touched;
- Sprint 1 CI including Docker E2E must pass;
- guarded Agent Hub backup/deploy/smoke must pass;
- production should initially contain no automatically started experiment.

## Initial production acceptance — 2026-08-21

Commit `5ad7688` was deployed from the dedicated worktree
`/opt/npd-ai-video-factory-phase8`. Guarded deployment created Redis namespace backup
`/var/backups/npd-agent-hub/agent-hub-20260821T122553Z.json`, rollback image
`npd-agent-hub:rollback-20260821T122553Z` and receipt
`/var/lib/npd-ai/agent-hub-deployments/deploy-20260821T122553Z.json`. The normal Agent
Hub smoke passed; n8n, Caddy and Redis topology were unchanged.

Production then created and previewed acceptance plan `EXP-VGP-202609-001` for Campaign
`CMP-VGP-VINHTIEN-202609-01` using owner-accepted reconciliation
`rec_1218e8a9db744c3a9720`. The `2.5 percent` baseline is explicitly recorded as a
planning assumption that must be replaced by accepted GA4 evidence before any future
execution design. The preview calculated a `3.0 percent` target for a 20 percent lift,
two 50/50 proposed variants, a 14-day evaluation window, CPL guardrail and manual
stop-and-review condition.

Acceptance evidence confirmed:

- experiment status `previewed` in `plan_preview` mode;
- experiment and preview external writes disabled;
- production execution disabled;
- no `/execute` endpoint (`HTTP 404`);
- unauthenticated Command Center redirects to login (`HTTP 303`) and login is healthy
  (`HTTP 200`);
- no traffic, Ads, CMS, CRM, n8n or customer-contact action was executed.

## Phase 8.1 read-only observation increment

Version `0.12.1` adds the normalized observation contract, Redis persistence, source
provenance and freshness gates, sample sufficiency, two-proportion significance,
guardrail evaluation and advisory recommendations. Configured GA4 and Meta Ads aggregate
readers are reported as `partial` for variant analysis until their tracking dimensions
can produce a verified per-variant snapshot. Verified imports remain read-only and must
carry an opaque snapshot reference; they may not contain credentials or customer PII.

### Production acceptance — 2026-08-21

CI-green commit `0b44eef` was deployed from the existing detached worktree
`/opt/npd-ai-video-factory-phase8`. The deployment guard was corrected to discover the
real Compose `caddy` service without a `pipefail`/early-`grep` false negative and to
recognize linked Git worktrees whose `.git` entry is a file. Preflight then passed against
project `n8n-marketing`, container `n8n-marketing-caddy-1` and the existing networks.

The Agent Hub-only deployment created:

- Redis namespace backup
  `/var/backups/npd-agent-hub/agent-hub-20260821T134609Z.json` with 400 keys;
- rollback image `npd-agent-hub:rollback-20260821T134609Z`;
- deployment receipt
  `/var/lib/npd-ai/agent-hub-deployments/deploy-20260821T134609Z.json`.

Local and HTTPS smoke both passed with Google login, viewer/operator/owner RBAC, 61
EspoCRM Lead fields and completed CRM/marketing read-only answers. Acceptance reported
version `0.12.1`, mode `plan_preview_observe`, all four marketing integrations configured,
and variant evidence states `ga4=partial`, `meta_ads=partial`,
`verified_import=read_only`. The existing acceptance experiment remains `previewed` with
zero observations and zero evaluations; requesting evaluation without evidence returns
HTTP 409, while `/execute` remains absent with HTTP 404.

Only the Agent Hub container restarted. n8n, Caddy and the existing video Redis retained
their earlier start times, confirming that the production topology was not recreated.
No synthetic observation, traffic allocation, budget mutation, CRM/CMS write, n8n write
or customer-contact action was performed.

## Intentional limits and next increment

There is still no traffic allocation, live experiment start, winner application, budget
reallocation, CMS change or autonomous optimization loop. The service does not pretend
that current aggregate GA4/Meta reports contain variant-level evidence. The next safe
increment is provider-specific read-only extraction keyed by canonical `campaign_id` and
`utm_content`/variant ID, with tracking validation and owner acceptance of the source
snapshot. Live execution belongs to a separate later phase and approval design.
