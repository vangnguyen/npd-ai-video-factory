# Phase 6B — Campaign Operating System

## Goal and safety boundary

Phase 6B adds one Campaign control plane above the existing Agent Hub, EspoCRM,
n8n, WordPress/Sales Hub and marketing read adapters. Every planned Meta Ads,
Google Ads, Email, Zalo/ZBS, landing-page, CRM and Sales activity carries the same
Campaign identity, KPI package and tracking contract.

The release supports only:

```text
research -> plan -> draft -> preview
```

It does not launch Ads, mutate budgets, bulk-send Email/ZBS, publish a production
landing page, mass-write CRM or contact customers. Owner approval records a decision;
it does not enable a production executor. Existing n8n write execution remains
disabled/inactive for Campaign OS acceptance.

## Base-branch and rollout strategy

PR #9 is still draft/unmerged. Phase 6B is therefore implemented on
`agent/phase-6b-campaign-os`, stacked on `agent/multi-agent-management-hub` at the PR
#9 head. The Phase 6B PR must use that branch as its base and remain draft/unmerged.
After the owner accepts and merges PR #9, the Phase 6B branch can be rebased or its PR
base can be changed to `main`; neither operation is automatic.

No deployment bundle topology changes are required. A later rollout continues to use
the existing `n8n-marketing` stack, Caddy container and Redis service. Campaign data
uses an Agent Hub subnamespace and never uses the video-job Redis DB 0 namespace.

## Architecture

```text
Command Center / Campaign Workspace
              |
              v
Campaign REST API -- viewer/operator/owner RBAC
              |
              v
CampaignService -- lifecycle -- approval -- audit
       |              |                 |
       v              v                 v
specialist plans   tool registry    HubStore abstraction
       |                                |
       v                                v
provider contracts             Memory / Redis persistence
                                        |
                              npd:agent-hub:v1:campaign-os:*
```

`CampaignService` is a deterministic planning control plane. Specialist agents create
proposals but do not call live channel executors. Capability policy is centralized in
`tool_registry.py`, so the API and UI can show the same read/draft/write,
approval-required, target-system, execution-state and dry-run metadata.

## Domain model

The root `Campaign` contains:

- canonical `campaign_id`, name, project/project code, objective and audience;
- budget/currency, start/end dates and KPI/funnel targets;
- lifecycle status;
- Meta Ads, Google Ads, Email, Zalo/ZBS and Web/Landing channel plans;
- creative briefs and landing-page staging drafts;
- Email and Zalo/ZBS sequence references;
- EspoCRM/Sales Hub source references and attribution placeholders;
- tracking contract and Sales SLA/handoff;
- owner, actor/version audit metadata and timestamps;
- approval package for every production-impacting action.

Campaign IDs follow:

```text
CMP-{PROJECT_CODE}-{CAMPAIGN_TOKEN}-{YYYYMM}-{NN}
```

Example: `CMP-VGP-VINHTIEN-202609-01`. Campaign inputs and audit metadata recursively
reject secret-, token-, password-, API-key- and credential-bearing keys. Credential
values belong only in the existing protected deployment secret mechanism.

## Lifecycle

```text
draft -> planned -> awaiting_approval -> approved -> ready_to_execute
                                                     |
                                              active -> paused
                                                 |       |
                                                 +-> completed

draft/planned/awaiting_approval/approved/ready_to_execute/active/paused
  -> cancelled (where valid)
```

Invalid transitions are rejected. Draft-safe fields can only be changed while
`draft` or `planned`. An operator may request approval; only an owner may approve or
reject. Side-effect states require owner authorization. In Phase 6B, transition to
`active` is rejected even for an owner because production execution is disabled.
Every create, plan refresh, update, approval and transition is appended to audit.

## Tracking contract

Every Campaign carries fields designed for downstream propagation:

| Field | Contract |
|---|---|
| `campaign_id` | Canonical internal Campaign key |
| `utm_source` | Channel source template |
| `utm_medium` | Paid, email, ZBS, social or referral medium template |
| `utm_campaign` | Canonical campaign ID in normalized form |
| `utm_content` | Creative/version key |
| `source_campaign_id` | Native channel campaign ID |
| `source_adset_id` | Meta ad-set ID where applicable |
| `source_ad_group_id` | Google Ads ad-group ID where applicable |
| `source_ad_id` | Native ad/creative delivery ID |
| `landing_page` | Resolved landing-page URL |
| `first_touch` | Immutable first-touch payload/reference |
| `last_touch` | Most recent qualified touch payload/reference |
| `lead_id` | Existing EspoCRM Lead ID |
| `opportunity_id` | Existing EspoCRM Opportunity ID |

Propagation targets are landing forms, EspoCRM Lead/Opportunity, Sales Hub, GA4
events and channel reporting. Phase 6B validates and preserves the contract; it does
not calculate full revenue attribution.

## Specialist agents under Marketing Leader

### Performance Ads Agent

Creates Meta/Google Ads hierarchy, audience/keyword, budget allocation, tracking and
creative-test plans. Existing Meta read-only evidence may inform proposals. Google Ads
live data remains `not_configured`. No launch or live budget mutation is available.

### Email Marketing Agent

Creates consented segmentation, nurture/lifecycle/re-engagement sequences and
subject/content A/B drafts. It requires a dedicated provider contract and explicitly
does not use WordPress Gmail SMTP for bulk marketing. Live send is disabled.

### Zalo/ZBS Marketing Agent

Creates OA/ZBS audience, template/sequence, consent/frequency and CRM handoff plans.
It does not reuse the transactional Zalo GMF flow. Live/bulk send is disabled.

### Web & Landing Page Agent

Creates a campaign brief, CTA/form, SEO/CRO checklist, tracking map and WordPress/Sales
Hub staging metadata. It targets the existing CMS and produces preview first. It does
not publish production pages.

## Provider contracts and current states

| Capability | State | Phase 6B behavior |
|---|---|---|
| Meta Ads | `read_only` | Reuse existing aggregate insights for planning |
| GA4 | `read_only` via existing integration | Planning/measurement context only |
| Social | aggregate read-only via existing integration | Planning context only |
| EspoCRM | `read_only` | Lead/funnel context and downstream ID contract |
| Google Ads | `not_configured` | Interface, config contract and planning validation only |
| Email provider | `not_configured` | Dedicated provider contract; no send |
| Zalo/ZBS | `not_configured` | OA/ZBS provider contract; no send |
| WordPress/Sales Hub | `contract_only` | Staging target metadata; no production publish |
| n8n write executor | `disabled` | No acceptance-side execution |

Missing providers must remain visibly `not_configured` or `partial`; generated plans
must never be presented as live-source performance.

## REST API and RBAC

| Operation | Endpoint | Minimum role |
|---|---|---|
| Create explicit Campaign | `POST /api/v1/campaigns` | operator |
| Create from business brief | `POST /api/v1/campaigns/from-brief` | operator |
| List/get | `GET /api/v1/campaigns`, `GET /api/v1/campaigns/{id}` | viewer |
| Update draft-safe fields | `PATCH /api/v1/campaigns/{id}` | operator |
| Generate/refresh channel plans | `POST /api/v1/campaigns/{id}/channel-plans/refresh` | operator |
| Request approval | `POST /api/v1/campaigns/{id}/approvals/request` | operator |
| Approve/reject campaign/channel | `POST /api/v1/campaigns/{id}/approvals/{scope}/decision` | owner |
| Lifecycle transition | `POST /api/v1/campaigns/{id}/transitions` | operator; owner for side-effect states |
| Audit/history | `GET /api/v1/campaigns/{id}/audit` | viewer |
| Summary/status | `GET /api/v1/campaigns/{id}/summary` | viewer |
| Provider status | `GET /api/v1/integrations/campaign/status` | viewer |
| Tool policy | `GET /api/v1/tools/capabilities` | viewer |

## Persistence and recovery

Campaigns reuse `HubStore`. `MemoryHubStore` supports unit tests; `RedisHubStore`
stores data under:

```text
{AGENT_REDIS_NAMESPACE}:campaign-os:campaign:{campaign_id}
{AGENT_REDIS_NAMESPACE}:campaign-os:campaigns
{AGENT_REDIS_NAMESPACE}:campaign-os:audit:{campaign_id}
```

The production namespace remains `npd:agent-hub:v1`; therefore Campaign OS recovery
uses the same existing Redis service and Agent Hub DB, while remaining isolated from
`npd:video-jobs:*` in DB 0. Recovery is verified with fakeredis by constructing a new
service/store against the same Redis state.

## Campaign Workspace

The responsive Command Center adds:

- Campaign Overview and KPI/funnel;
- Channel Plans and provider states;
- Creatives and Landing Pages;
- Email and Zalo/ZBS drafts;
- Tracking contract;
- owner Approvals;
- a read-only Lead Funnel placeholder.

The current Approval queue remains ahead of recent tasks and tasks remain limited to
the latest five. The existing Command Center answer tables and 20-question business
library remain intact.

## Approval matrix

| Automatic planning operation | Requires owner approval before production effect |
|---|---|
| Research/read-only analysis | Ads launch or budget mutation |
| Draft generation | Email bulk-send |
| Preview generation | ZBS/OA bulk-send |
| Tracking validation | Landing-page production publish |
| Provider/config validation | CRM mass-write |
|  | Customer-contact action |

An approval decision does not itself execute an action. The production executor and
separate execution command remain unavailable to Campaign OS in Phase 6B.

## Vịnh Tiên acceptance package

Input:

```text
Tạo chiến dịch Vịnh Tiên tháng 9, ngân sách 100 triệu, mục tiêu 300 lead và 30 khách đi xem.
```

Expected deterministic output:

- `campaign_id`: `CMP-VGP-VINHTIEN-202609-01`;
- status `planned`, budget `100,000,000 VND`;
- KPI funnel: 300 leads, 30 site visits, 10% lead-to-visit;
- Meta plan: 50% proposed budget, prospecting + retargeting, read-only evidence;
- Google Ads plan: 25% proposed budget, Search/ad groups/keywords, `not_configured`;
- Web/Landing: 10% proposed budget, staging brief, CTA/form and tracking validation;
- two creative briefs and variant matrix;
- four-step Email sequence, provider `not_configured`, live send false;
- three-step Zalo/ZBS sequence, consent/frequency guards, live send false;
- EspoCRM Lead/Opportunity tracking refs and attribution placeholders;
- Sales SLA: first response 15 minutes, visit booking handoff within 24 hours;
- seven owner-approval requirements, all with execution disabled.

The acceptance creates no external side effect and does not claim any Google Ads,
Email provider or ZBS live data.

## Tests and CI gates

Campaign OS tests cover ID generation/validation, secret rejection, lifecycle,
draft-safe updates, RBAC, approval boundaries, Redis recovery, audit, four specialists,
provider absence, sample acceptance, no planning executor calls, API and UI. Agent Hub
CI runs the complete suite and the 20-question business-answer eval gate.

Before a rollout, the stacked PR also requires:

- Agent Hub CI;
- Phase 5 Deployment Bundle CI if the deployment bundle is touched;
- Sprint 1/API CI including Docker Compose E2E;
- a review confirming no production write capability became active.

## Intentional limits and Phase 7 handoff

Phase 6B intentionally excludes full revenue attribution, autonomous Ads scaling,
live Email/ZBS sends, direct CRM mass writes, autonomous landing-page publication,
Revenue Agent, CRO auto-optimization and the production Creative Testing loop.

The exact Phase 7 first step is to define and backfill an immutable touchpoint/event
ledger keyed by `campaign_id`, `lead_id` and `opportunity_id`, then reconcile source
campaign IDs with EspoCRM opportunities and closed revenue in read-only shadow mode.
Only after data-quality/reconciliation acceptance should Phase 7 calculate attributable
pipeline/revenue; it must not enable channel mutation or customer contact.
