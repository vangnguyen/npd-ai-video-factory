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

Phase 6B was merged through PR #11 into `main` at `aa1e21e`. Phase 7 was merged
through PR #12 at `1cc65a3` and tagged `agent-hub-v0.11.0`. Production acceptance
hardening is recorded on draft PR #13 (`agent/phase-7-campaign-id-baseline`) and
remains independently reviewable/unmerged.

Production deployment is always gated by repository CI, guarded backup/deploy/smoke,
read-only source evidence and owner quality acceptance; a merge alone is insufficient.

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

The initial accepted production projection had nine fields and no raw PII. EspoCRM
reported zero Opportunity records and no canonical Campaign OS custom field, so no
reconciliation snapshot was created and owner quality acceptance/revenue reporting
remained blocked. Phase 7 must not create a synthetic CRM Opportunity to bypass this
gate.

### Canonical Campaign ID onboarding — 2026-08-21

EspoCRM Opportunity now has the custom audited field `cCampaignId`, labelled
`Campaign ID`. It is a nullable 64-character varchar with validation pattern
`^CMP-[A-Z0-9][A-Z0-9-]{1,47}-[0-9]{6}-[0-9]{2}$`. The field is visible in the
Opportunity detail/edit layout and list layout. It is distinct from EspoCRM's native
`campaignId` link and is the only field used to carry the canonical Campaign OS ID.

Before the schema change, production created and verified these rollback assets:

- full EspoCRM database dump and custom metadata archive under
  `/var/backups/npd-agent-hub/espocrm-opportunity-campaign-field-20260821T090329Z`;
- pre-change Opportunity detail and list layouts in the same directory;
- the pre-change Agent Hub environment file in the same directory.

The production Agent Hub is configured with
`ESPOCRM_OPPORTUNITY_CAMPAIGN_FIELD=cCampaignId` and was recreated from git SHA
`1cc65a30a8f2e50df10ddeaa9e23d1feb2ea0d69`. The guarded deployment created Redis
namespace backup
`/var/backups/npd-agent-hub/agent-hub-20260821T090747Z.json`, rollback image
`npd-agent-hub:rollback-20260821T090747Z`, and deployment receipt
`/var/lib/npd-ai/agent-hub-deployments/deploy-20260821T090747Z.json`.

Local and public source smoke tests both returned HTTP 200 for operator and HTTP 403
for viewer. The accepted projection now has ten fields, including `cCampaignId`, with
`contains_raw_pii=false` and `external_writes_enabled=false`. The Agent Hub role still
has Opportunity `read=all` and `create/edit/delete/stream=no`. Caddy and the existing
n8n/Redis topology were not changed, and the n8n write executor remains disabled.

A follow-up security audit rotated the Agent Hub browser session signing key. No key
value is stored in the repository or this document. The previous environment was
backed up under
`/var/backups/npd-agent-hub/session-key-rotation-20260821T100309Z`; guarded deployment
receipt `deploy-20260821T100309Z.json` confirms a healthy restart. Existing browser
sessions may need to authenticate again after this rotation.

### Explicit acceptance Opportunity — 2026-08-21

After explicit owner authorization, production created the planning-only Campaign
`CMP-VGP-VINHTIEN-202609-01` from the standard Vịnh Tiên brief. It remains `planned`;
none of its Ads, email, ZBS or landing-page plans were executed.

EspoCRM then created one clearly labelled acceptance record:

- Opportunity ID `6a881aa4bb9606e32`;
- name `[ACCEPTANCE] Vinh Tien thang 9 - Campaign OS`;
- stage `Prospecting`, close date `2026-09-30`;
- canonical field `cCampaignId=CMP-VGP-VINHTIEN-202609-01`;
- amount `0`, so it does not represent real pipeline or revenue.

At initial creation EspoCRM permitted only `USD`, so the record started at `0 USD`.
A follow-up audit confirmed that `VND` had subsequently been enabled and set as the
CRM default. After another full database and Agent Hub namespace backup, the acceptance
record was aligned to `0 VND`; no positive pipeline or revenue value was introduced.
The USD event is retained only as historical audit evidence and is excluded from
current business calculations.
The alignment evidence and rollback assets are stored under
`/var/backups/npd-agent-hub/opportunity-vnd-alignment-20260821T100411Z`.

Before the authorized writes, Agent Hub Redis and the full EspoCRM database were
backed up under
`/var/backups/npd-agent-hub/opportunity-acceptance-20260821T092725Z`. The database
archive passed its integrity test, and rollback remains manual to avoid overwriting
newer CRM records.

Local and public source reads then reported `available`, one reported/one read
Opportunity, the correct Campaign ID, currency `VND`, no raw PII and no external
writes. The original USD snapshot is retained in audit history but is not accepted
by the current runtime contract. Reconciliation
`rec_5c00f1d5d75540759da4` matched the Opportunity to the Campaign at 100 percent but
remained `blocked_by_data_quality`: there was no real closed-won Opportunity with
covered revenue. No owner quality acceptance was recorded at that point, and the
acceptance record was not converted to fake won revenue to bypass the gate.

### Existing-customer source classification

Campaign OS permits a zero-budget source Campaign when the owner explicitly classifies
revenue as non-paid demand such as an existing customer, referral or organic source.
This prevents the attribution ledger from inventing media spend merely to satisfy the
Campaign contract. A source Campaign remains draft/planning-only, has no channel plans
or execution permission, and its `crm_source_refs` records the owner-confirmed source
type without customer PII. The resulting revenue remains a shadow calculation and must
not be reported as Ads ROAS.

### Final production quality acceptance — 2026-08-21

The owner classified a real `13,000,000,000 VND` Closed Won Opportunity as originating
from an existing customer. Campaign OS was extended to allow a truthful zero-budget
non-paid source rather than inventing nominal media spend. Production created source
Campaign `CMP-VSGP-KHACHHANGCU-202608-01` in `draft`, with no channel plans or execution
permission, then attached that canonical ID to only the confirmed Opportunity.

Before the mapping change, the complete Agent Hub namespace, full EspoCRM database,
original Opportunity mapping and manual rollback SQL were stored under
`/var/backups/npd-agent-hub/existing-customer-attribution-20260821T121012Z`. The Agent
Hub deployment of commit `408c35d` also created Redis backup
`/var/backups/npd-agent-hub/agent-hub-20260821T120746Z.json`, rollback image
`npd-agent-hub:rollback-20260821T120746Z` and deployment receipt
`/var/lib/npd-ai/agent-hub-deployments/deploy-20260821T120746Z.json`.

Reconciliation `rec_1218e8a9db744c3a9720` then passed the owner gate:

- `2/2` Opportunities mapped with no conflicts;
- `1/1` Closed Won Opportunity had positive revenue and `closed_at`;
- match and won-revenue coverage rates were both 100 percent;
- owner quality state became `quality_accepted`;
- last-touch shadow pipeline was `25,700,008,957 VND`;
- last-touch shadow closed revenue was `13,000,000,000 VND`;
- public status remained `read_only_shadow` with production writes disabled.

The existing-customer Campaign is explicitly not Ads-attributed and is ineligible for
ROAS. CAC/ROAS remain unavailable until reconciled paid-media spend exists for the same
Campaign, currency and period.

### Currency policy

The operating currency is **VND only**. Campaign budgets, Meta Ads spend and
EspoCRM Opportunity amounts must be VND before entering Campaign OS or the
Attribution & Revenue OS. Explicit non-VND values fail closed; the system never
converts them and never relabels USD as VND. Missing currency values use the VND
default. Historical non-VND audit records remain immutable evidence but are not
eligible for reconciliation, KPI aggregation, CAC or ROAS.

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
