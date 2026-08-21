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

## Phase 8.2 direct source reads and owner observation gate

Version `0.12.2` adds provider-specific, aggregate-only reads for experiment evidence:

- GA4 reads `sessionManualCampaignName` using the Campaign tracking
  `utm_campaign`, maps `sessionManualAdContent` exactly to planned `VAR-*` IDs,
  and stores only sessions/key events by variant;
- Meta Ads reads Insights at ad level only after
  `attribution_refs.meta_ads_campaign_id` and every variant
  `asset_ref=meta_ad:<numeric_ad_id>` are explicit. Unmapped ads are ignored;
- tracking validation reports `ready`, `partial` or `not_configured` and a failed
  contract never creates an observation;
- a successful query with no mapped rows reports `no_data` and does not create
  synthetic zero observations;
- every stored source snapshot starts `pending_owner`. Evaluation is blocked until
  an owner accepts its source, date window, mapping and aggregate quality. Rejection
  remains audited and cannot be evaluated;
- direct reads, decisions and evaluations persist through the existing Experiment OS
  Redis subnamespace. Payloads contain no raw customer PII or credentials.

The Command Center now exposes direct GA4/Meta read controls, snapshot quality state,
owner accept/reject controls, and enables evaluation only when an accepted observation
exists. These controls do not allocate traffic or call a write executor.

### Phase 8.2 acceptance contract

For the Vịnh Tiên acceptance experiment, the safe production outcome is either a real
mapped aggregate observation pending owner acceptance, or an explicit `partial`/
`no_data` response while the Campaign has no live variant mapping/data. The system must
not fabricate an observation merely to complete acceptance.

### Production acceptance — 2026-08-21

CI-green code commit `9e4c511` was deployed from the existing linked worktree
`/opt/npd-ai-video-factory-phase8`. Preflight discovered the existing
`n8n-marketing` Compose project, `n8n-marketing-caddy-1`, both shared networks and the
Agent Hub-only production Compose without creating replacement infrastructure.

The deployment created:

- Redis namespace backup
  `/var/backups/npd-agent-hub/agent-hub-20260821T141325Z.json` with 422 keys;
- rollback image `npd-agent-hub:rollback-20260821T141325Z`;
- deployment receipt
  `/var/lib/npd-ai/agent-hub-deployments/deploy-20260821T141325Z.json`.

Local and HTTPS smoke passed. Production reported version `0.12.2`, mode
`plan_preview_direct_read_owner_gate`, and CRM/Meta Ads/GA4/Social all configured.
Acceptance against `EXP-VGP-202609-001` returned:

- GA4 tracking `ready`, but the 14-day aggregate query returned `no_data` for the
  planned `VAR-CONTROL`/`VAR-HOOKA` UTM content values;
- Meta tracking `partial` because the Campaign has no numeric
  `meta_ads_campaign_id` and neither variant has `meta_ad:<numeric_ad_id>` mapping;
- zero observations before and after the read, zero owner-accepted snapshots and no
  evaluation;
- experiment execution/external writes disabled and `/execute` still HTTP 404.

Only the Agent Hub restarted. n8n, Caddy and the existing video Redis retained their
earlier start times. No traffic, Ads, CRM/CMS, n8n or customer-contact mutation was
performed. Public login health was verified; interactive authenticated visual QA stopped
at the Google account chooser without selecting or transmitting an account identity.

## Phase 8.3 tracking activation workflow

Version `0.12.3` closes the operational gap between a planned experiment and a truthful
source mapping without enabling production execution:

- tracking validation generates a deterministic relative landing-page URL for each
  planned variant with canonical `campaign_id`, `utm_campaign` and
  `utm_content=VAR-*` parameters;
- the Command Center displays GA4/Meta readiness, the exact UTM preview and the reason a
  source is partial;
- only an owner may submit a numeric Meta campaign ID plus one distinct numeric ad ID
  for every planned variant;
- the coordinated mapping updates only Campaign/Experiment records in the Agent Hub
  Redis namespace, records Campaign and Experiment audit events, invalidates the old
  preview and leaves Ads untouched;
- mapping is rejected if any variant is missing/extra, IDs are duplicated/non-numeric,
  Campaign/Experiment is outside draft/planned/previewed state, or an observation already
  exists. After evidence exists, mapping is immutable and a new experiment is required;
- source reads and the owner observation-quality gate remain unchanged. A tracking
  mapping does not start traffic, publish a URL or create an observation.

### Production discovery gate

A read-only Meta discovery query inspected 130 campaigns across the configured Ads
accounts and found no campaign matching Vịnh Tiên. Therefore no production mapping was
applied and no ID was inferred from a similar campaign name. Phase 8.3 must remain
`partial` for Meta until the real campaign and its two ads exist and their IDs are
verified in Ads Manager/API.

### Phase 8.3 production acceptance — 2026-08-21

CI-green code commit `9fecd6a` was deployed from the guarded worktree
`/opt/npd-ai-video-factory-phase8`. Preflight verified the existing
`n8n-marketing` project, `n8n-marketing-caddy-1`, shared video/n8n networks, Redis
storage and Google/static-token RBAC before replacing only the Agent Hub container.

The deployment created:

- Redis namespace backup
  `/var/backups/npd-agent-hub/agent-hub-20260821T143441Z.json` with 444 keys;
- rollback image `npd-agent-hub:rollback-20260821T143441Z`;
- deployment receipt
  `/var/lib/npd-ai/agent-hub-deployments/deploy-20260821T143441Z.json`.

Local smoke passed immediately. The first HTTPS health probe briefly returned HTTP 503
while the recreated upstream was entering the healthy state; direct localhost,
Caddy-to-upstream and public health then all returned HTTP 200, and the complete public
viewer/operator/owner plus CRM/marketing smoke passed on retry.

Production reported version `0.12.3`, mode
`plan_preview_direct_read_owner_gate`, and CRM/Meta Ads/GA4/Social all configured.
Acceptance against `EXP-VGP-202609-001` confirmed:

- GA4 tracking `ready`, with deterministic URLs for `VAR-CONTROL` and `VAR-HOOKA`
  carrying `campaign_id=CMP-VGP-VINHTIEN-202609-01`,
  `utm_campaign=cmp-vgp-vinhtien-202609-01` and the matching `utm_content`;
- a 14-day GA4 read returned `no_data`, created no synthetic observation and performed
  no external write;
- Meta tracking remained `partial`; a direct read stopped before querying/storing an
  observation because no verified Meta campaign/ad mapping exists;
- an operator mapping request was denied with HTTP 403; an owner request with incomplete
  variant coverage was denied with HTTP 409; variant asset references and readiness
  remained unchanged;
- observation and evaluation counts remained zero, production/experiment execution and
  external writes remained disabled, and `/execute` returned HTTP 404;
- authenticated visual QA with `nguyenvanvangct@gmail.com` confirmed the owner UI,
  readiness counters, UTM previews, direct-read controls, owner mapping control and a
  disabled evaluation action while no accepted observation exists.

Only the Agent Hub restarted at `2026-08-21T14:35:02Z`. n8n, Caddy and the existing
video Redis retained their earlier start times (`2026-08-14T01:55:28Z`,
`2026-08-08T07:21:11Z` and `2026-08-14T06:46:07Z`). No Meta ID was fabricated or
applied, and no traffic, Ads, CRM/CMS, n8n or customer-contact mutation occurred.

### Historical Meta evidence activation — 2026-08-21

The owner allowed the acceptance experiment to use an existing Vịnh Ngọc/Vin campaign,
or otherwise the most recent real campaign with reported leads, because production Ads
names do not consistently contain project names. A 90-day, read-only Meta query found no
campaign name matching `Vịnh Ngọc` or `Vịnh Tiên`. The most recent lead campaign had only
one ad and could not satisfy the two-variant contract.

The next-most-recent eligible campaign was therefore selected from account
`Bat Dong San 1`:

- Meta campaign `120247585611660280`, `Lead-v1-page bds vin-24/7-1`, objective
  `OUTCOME_LEADS`, paused at acceptance time;
- 90-day campaign aggregate: 18 Meta-reported leads, 49,722 impressions,
  1,080 clicks and 5,234,425 VND spend;
- `VAR-CONTROL` mapped to ad `120247586290300280`: 33,021 impressions,
  14 reported leads and read-only CPL 245,560.29 VND;
- `VAR-HOOKA` mapped as a comparison label to ad `120247585611680280`:
  14,903 impressions, 3 reported leads and read-only CPL 502,943.33 VND.

Both ads have distinct Meta creative IDs but the visible title/body metadata is the
same. The mapping therefore does not claim that the second ad is a newly designed hook,
and the historical data cannot establish creative causality. It is an evidence-pipeline
acceptance comparison only.

The coordinated owner mapping returned HTTP 200, changed Meta tracking from `partial` to
`ready`, invalidated the old preview and returned the experiment to `planned`. A direct
Meta read for `2026-05-24` through `2026-08-21` stored observation
`eobs_5f994a164de04fcba4f2` as `verified_read_only` and `pending_owner`. The payload has
no raw PII and external writes remain disabled. No quality decision or evaluation has
been applied; the owner must review the historical-comparison caveat before accepting
the snapshot.

## Intentional limits and next increment

There is still no traffic allocation, live experiment start, winner application, budget
reallocation, CMS change or autonomous optimization loop. Meta extraction requires
explicit live campaign/ad IDs; GA4 requires the canonical UTM contract to have reached
live sessions. A winner candidate remains an advisory result even after owner quality
acceptance. Live execution belongs to a separate later phase and approval design.
