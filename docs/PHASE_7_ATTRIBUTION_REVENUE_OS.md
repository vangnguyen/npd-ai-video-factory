# Phase 7 — Attribution & Revenue OS

## Goal and boundary

Phase 7 turns the Campaign tracking contract into a verifiable attribution ledger.
It records immutable, pseudonymous touchpoints keyed by `campaign_id`, `lead_id`
and/or `opportunity_id`, reconciles read-only EspoCRM Opportunity snapshots, and
calculates pipeline/closed-revenue attribution only after an owner accepts the data
quality snapshot.

This phase runs in `read_only_shadow` mode. It never changes Ads, CRM, CMS, Email,
Zalo or customer-contact systems. It does not infer CAC or ROAS without reconciled
spend for the same Campaign, currency and period.

## Branch strategy

Phase 6B was merged through PR #11 into `main` at `aa1e21e`. Phase 7 is implemented
on `agent/phase-7-attribution-revenue-os`; PR #12 is based directly on `main` and
remains draft until it receives a separate owner review and rollout decision.

Phase 7 is not part of the production `agent-hub-v0.9.0` baseline and must not be
deployed merely because repository CI passes.

## Architecture

```text
Campaign OS tracking contract
          |
          v
immutable Touchpoint ledger <--- read-only source/backfill adapters
          |
          v
Opportunity/Revenue reconciliation snapshot
          |
          v
data-quality gate -- owner decision -- audit
          |
          v
first-touch / last-touch / linear shadow report
```

`AttributionService` is deterministic and uses the existing `HubStore` abstraction.
Touchpoint event IDs are idempotent: an exact retry is accepted as a duplicate, while
the same ID with changed content is rejected. Raw email, phone, address, names,
credentials and secrets are forbidden in attribution metadata.

## Domain contracts

### Immutable touchpoint

Required:

- `event_id`, `campaign_id`, event type and occurrence timestamp;
- source system and channel;
- `lead_id` or `opportunity_id`;
- optional source campaign/ad-set/ad-group/ad IDs;
- optional UTM and landing-page values;
- metadata that contains neither secrets nor raw PII.

Supported event types are `ad_click`, `landing_view`, `form_submit`, `lead_created`,
`opportunity_created`, `opportunity_stage_changed` and `sale_closed`.

### Opportunity observation

An observation is an immutable read snapshot with Opportunity/Lead references,
stage, `open|won|lost`, amount, currency, observed time and closed time. A won
Opportunity without positive revenue or `closed_at` is retained as data-quality
evidence but cannot pass owner acceptance. The reconciliation batch accepts only one
latest snapshot for each Opportunity.

### Reconciliation

Touchpoints are matched by `opportunity_id`, then `lead_id`, then an explicit valid
Campaign hint. Multiple ordered Campaign touches are valid and power multi-touch
models. A Campaign hint that contradicts the immutable event evidence is a conflict.

Every reconciliation stores its own observations, matches, quality metrics and a
SHA-256 fingerprint of the ledger used. It is therefore a reproducible historical
snapshot even when later touchpoints are added.

## Data-quality gate

An owner may accept a reconciliation only when all of these conditions hold:

- at least one Opportunity exists;
- every Opportunity maps to at least one Campaign;
- no Campaign hint conflicts with touchpoint evidence;
- at least one closed-won Opportunity exists;
- every closed-won Opportunity has positive reconciled revenue and `closed_at`.

Before acceptance, all attribution reports return
`blocked_until_owner_quality_acceptance` and contain no pipeline or revenue totals.
Rejection also leaves totals hidden. Acceptance only records an internal governance
decision; it produces no external side effect.

## Attribution models

After acceptance, Phase 7 can calculate:

- `first_touch`: 100% credit to the earliest Campaign touch;
- `last_touch`: 100% credit to the latest Campaign touch;
- `linear`: equal credit across unique ordered Campaign touches.

Pipeline includes open and won Opportunity value; closed revenue includes won value
only. Lost Opportunity value contributes neither. One reconciliation cannot calculate
across multiple currencies.

These are shadow calculations, not accounting entries. CAC/ROAS stay unavailable
until channel spend has the same accepted Campaign/period/currency reconciliation.

## Revenue Attribution Agent

The new specialist works with Marketing Leader, CRM Manager and Sales. It can prepare:

- immutable-ledger reviews;
- Campaign identity reconciliation previews;
- quality-gate findings;
- owner-accepted pipeline and revenue shadow reports.

All its tool capabilities are `planning_only`. It cannot write EspoCRM, change Ads,
send messages or execute an n8n write workflow.

## REST API and RBAC

| Operation | Endpoint | Minimum role |
|---|---|---|
| Attribution status | `GET /api/v1/attribution/status` | viewer |
| List/filter touchpoints | `GET /api/v1/attribution/touchpoints` | viewer |
| Backfill immutable touchpoints | `POST /api/v1/attribution/touchpoints/backfill` | operator |
| Create reconciliation snapshot | `POST /api/v1/attribution/reconciliations` | operator |
| Get reconciliation | `GET /api/v1/attribution/reconciliations/{id}` | viewer |
| Accept/reject quality snapshot | `POST /api/v1/attribution/reconciliations/{id}/acceptance` | owner |
| Read shadow report | `GET /api/v1/attribution/reconciliations/{id}/report` | viewer |
| Read audit history | `GET /api/v1/attribution/audit` | viewer |
| Read safe EspoCRM Opportunity snapshot | `GET /api/v1/attribution/sources/espocrm/opportunities` | operator |
| Reconcile latest EspoCRM Opportunity snapshot | `POST /api/v1/attribution/reconciliations/espocrm` | operator |

Backfill writes only to the internal immutable ledger. It does not write any source
system. Production onboarding of a source adapter needs a separate least-privilege
review and acceptance record.

The EspoCRM adapter requests only `id`, `stage`, `amount`, `amountCurrency`,
`closeDate`, `leadSource`, `campaignId`, `createdAt` and `modifiedAt`. It never requests
Opportunity name, contact, account, email, phone, notes or description. An optional
`ESPOCRM_OPPORTUNITY_CAMPAIGN_FIELD` may be configured only after a custom field that
carries the canonical `CMP-*` value exists; native EspoCRM `campaignId` remains a
source reference and is never treated as the Campaign OS ID.

## Persistence

Memory and Redis stores implement the same contract. Redis records Phase 7 under:

```text
{AGENT_REDIS_NAMESPACE}:attribution-os:touchpoint:*
{AGENT_REDIS_NAMESPACE}:attribution-os:campaign:*:touchpoints
{AGENT_REDIS_NAMESPACE}:attribution-os:opportunity:*:touchpoints
{AGENT_REDIS_NAMESPACE}:attribution-os:lead:*:touchpoints
{AGENT_REDIS_NAMESPACE}:attribution-os:reconciliation:*
{AGENT_REDIS_NAMESPACE}:attribution-os:audit
```

The production Agent Hub namespace remains in Redis DB 1. Video jobs stay in DB 0;
Phase 7 does not create another Redis service or touch `npd:video-jobs:*`.

## Command Center

The responsive Command Center adds an Attribution & Revenue OS status panel showing:

- `read_only_shadow` mode;
- immutable touchpoint count;
- reconciliation snapshot count;
- latest quality-gate state;
- production write state, which remains disabled.

The UI deliberately does not provide a shortcut to accept quality or import arbitrary
revenue. Owner acceptance uses the authenticated API after the reconciliation evidence
has been reviewed.

### Production read-projection audit — 2026-08-21

The existing `agent-hub-readonly` API role initially had no Opportunity scope. Its
single role was backed up to
`/var/backups/npd-agent-hub/espocrm-role-agent-hub-readonly-before-opportunity-20260821T083314Z.sql`,
then extended with `read=all` and `create/edit/delete/stream=no` for Opportunity.
Metadata and record GETs were verified; Lead access and all write restrictions remain
unchanged.

The accepted production projection has nine fields and no raw PII. EspoCRM currently
reports zero Opportunity records and no canonical Campaign OS custom field. Therefore
the production source state is `no_data`, no reconciliation snapshot is created, and
owner quality acceptance/revenue reporting remains blocked. Phase 7 must not create a
synthetic CRM Opportunity to bypass this gate.

## Acceptance example

The deterministic Vịnh Tiên sample records two Campaign touches for one won
Opportunity and one Campaign touch for an open Opportunity. Before quality acceptance,
the report hides revenue. After owner acceptance:

- total attributed pipeline is `20,000,000 VND`;
- total attributed closed revenue is `12,000,000 VND`;
- first-touch assigns the won revenue to the earliest Campaign;
- last-touch assigns it to the latest Campaign;
- linear splits it across both Campaigns;
- no source system is mutated.

## Tests and acceptance gates

Tests cover immutable/idempotent backfill, raw-PII rejection, Campaign validation,
quality blocking, owner-only acceptance, first/last/linear allocation, Redis recovery,
audit, Revenue Attribution Agent routing, centralized tool policy, API RBAC, responsive
UI surface and absence of external writes.

Required before any rollout:

- Agent Hub CI and the 20-question business eval gate;
- Phase 5 Deployment Bundle CI when relevant;
- Sprint 1 CI including Docker Compose E2E;
- review of the exact read-only EspoCRM Opportunity projection;
- dry backfill/reconciliation evidence with counts and no raw contact data;
- owner data-quality acceptance;
- separate VPS deployment approval.

## Intentional limits and Phase 8 handoff

Phase 7 does not implement autonomous budget scaling, Ads mutation, CRM writes,
customer messaging, bulk sends, production publishing, accounting-grade revenue,
automatic CRO changes or an autonomous creative-testing loop.

The Phase 8 first step is a controlled Experiment & Optimization OS that consumes
owner-accepted Phase 7 attribution snapshots to propose creative/audience/landing-page
experiments. It must begin in plan/preview mode with explicit experiment IDs,
hypotheses, guardrails and stop conditions. No optimizer may change spend or production
content until a separate approval and execution design is accepted.
