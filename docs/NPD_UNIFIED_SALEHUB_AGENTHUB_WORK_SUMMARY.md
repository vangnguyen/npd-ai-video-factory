# NPD unified SaleHub–AgentHub work summary

## Document status

- Snapshot: `2026-08-26 13:06 Asia/Ho_Chi_Minh`.
- Repository: `vangnguyen/npd-ai-video-factory`.
- Documentation branch: `docs/unified-salehub-agenthub-handoff`.
- Stable source revision: `400899ba82501beeea469f4a33dc169a9a09bb8e`.
- Agent Hub release: `0.13.0`.
- Production acceptance: **PASS** for the fixed 24-hour window from
  `2026-08-25T05:11:00Z` through `2026-08-26T05:11:00Z`.
- This change set is documentation-only. It does not merge, tag, deploy, rotate a key,
  reload Caddy or enable an execution capability.

## Executive summary

Ngọc Phương Đông now has two bounded applications that operate as one business
platform:

- **SaleHub** is the frontline sales workspace for inventory, prices, sales policy,
  Lead/Opportunity interaction and the authorized transaction workflow.
- **AgentHub** is the orchestration, marketing-intelligence, campaign, attribution,
  reliability, approval, audit and recommendation layer.

EspoCRM remains the customer and Opportunity source of truth. WordPress and SaleHub
remain the sales experience. AgentHub integrates with those systems and does not create
a parallel CRM, CMS, n8n, Caddy or Redis service.

The stabilization objective has been met: GitHub `main`, the production deployment
receipt and the live Agent Hub container all identify the same commit, Agent Hub 0.13.0
completed its 24-hour observation window without an unexplained outage, and all
marketing/customer write boundaries remain fail-closed. Concurrent SaleHub maintenance
was correlated separately and did not invalidate the Agent Hub acceptance window.

## Evidence vocabulary

| Label | Meaning |
|---|---|
| Confirmed | Read from GitHub, the production receipt, container metadata, persisted state or a live route during this review. |
| Authorized concurrent change | A SaleHub/Caddy change explicitly confirmed by the owner and evaluated separately from Agent Hub. |
| Owner gate | A decision or business/visual acceptance that has not been inferred from an HTTP health check. |

All operational statements below use confirmed evidence unless explicitly marked as an
owner gate or an intentional limitation.

## Delivery timeline

| Track | Outcome | Current state |
|---|---|---|
| Phases 1–5 | Video Factory foundation, Agent Hub, Command Center, RBAC, Redis persistence, audit and guarded production deployment | Live foundation |
| Phase 6A | Read-only marketing intelligence for EspoCRM, Meta Ads, GA4 and Social | Live, read-only |
| Phase 6B | Campaign Operating System, tracking contract and planning specialists | Live for research/plan/draft/preview; no channel execution |
| Phase 7 | Attribution & Revenue OS and Opportunity/value read models | Live read/analysis layer; write remains gated |
| Phase 8A | Experiment & Optimization OS | Preview and recommendation only |
| Phase 8B — 8.4 | Campaign identity and attribution data quality | Live |
| Phase 8B — 8.5 | Lead Intake attribution exception operations | Live |
| Phase 8B — 8.6 | Ingestion delivery observability | Live |
| Phase 8B — 8.7 | Provider health and internal alerts | Live |
| Phase 8B — 8.8 | Heartbeat and scheduled health evaluation | Live and accepted |
| Phase 8B — 8.9 | Deterministic alert-routing preview | Live in Agent Hub 0.13.0; external delivery remains disabled |
| SaleHub VSP policy | V07 giãn xây and V01 HĐCN thô/hoàn thiện policy release | Promoted on 2026-08-25; post-change shared-route smoke passed |
| SaleHub position-image maintenance | Automatic unit-position image synchronization fix | Release `releases/20260826-position-image-autosync-v1` observed live; visual/business acceptance remains an owner gate |

The detailed phase contracts remain in [Campaign Operating System](./PHASE_6B_CAMPAIGN_OPERATING_SYSTEM.md),
[Attribution & Revenue OS](./PHASE_7_ATTRIBUTION_REVENUE_OS.md),
[Experiment & Optimization OS](./PHASE_8_EXPERIMENT_OPTIMIZATION_OS.md) and the
[Phase 8.9 routing document](./PHASE_8_9_ALERT_ROUTING_PREVIEW.md).

## GitHub and release evidence

### Stabilization merge sequence

| Pull request | Scope | Disposition |
|---:|---|---|
| [#16](https://github.com/vangnguyen/npd-ai-video-factory/pull/16) | Phase 8.5 | Merged to `main` |
| [#17](https://github.com/vangnguyen/npd-ai-video-factory/pull/17) | Phase 8.6 | Merged after #16 |
| [#18](https://github.com/vangnguyen/npd-ai-video-factory/pull/18) | Phase 8.7 | Merged after #17 |
| [#19](https://github.com/vangnguyen/npd-ai-video-factory/pull/19) | Phase 8.8 | Merged after #18 |
| [#21](https://github.com/vangnguyen/npd-ai-video-factory/pull/21) | Historical HMAC verification keyring | Merged before Phase 8.9 |
| [#23](https://github.com/vangnguyen/npd-ai-video-factory/pull/23) | First provider-health router extraction | Merged as an API-preserving refactor |
| [#25](https://github.com/vangnguyen/npd-ai-video-factory/pull/25) | Full CI triggers after PR retarget/ready events | Merged before the final Phase 8.9 gate |
| [#20](https://github.com/vangnguyen/npd-ai-video-factory/pull/20) | Phase 8.9 routing preview | Merged as `400899b` and deployed as Agent Hub 0.13.0 |

Current `origin/main`, the production deployment receipt and the live runtime resolve to
`400899ba82501beeea469f4a33dc169a9a09bb8e`. This restores GitHub `main` as the
production source of truth.

The latest stable tag predates 0.13.0. No new tag was created by this documentation
milestone; tagging the accepted baseline is a separate owner action.

### CI on the exact production/main revision

| Required workflow | GitHub run | Result |
|---|---:|---|
| Agent Hub CI | [32810533290](https://github.com/vangnguyen/npd-ai-video-factory/actions/runs/32810533290) | Success |
| Phase 5 Deployment Bundle CI | [32810548375](https://github.com/vangnguyen/npd-ai-video-factory/actions/runs/32810548375) | Success |
| Sprint 1 CI, including API, worker, renderer and Docker Compose E2E | [32810550622](https://github.com/vangnguyen/npd-ai-video-factory/actions/runs/32810550622) | Success |

Branch protection on `main` requires a pull request, up-to-date required checks and
resolved conversations; force-push and branch deletion are disabled.

## Final Agent Hub 0.13.0 acceptance

### Decision

**PASS.** No unexplained Agent Hub outage, restart, scheduler/lease anomaly, provider
loss, Redis/HMAC failure or safety-boundary violation was found in the complete fixed
window.

### Window evidence

| Check | Result |
|---|---|
| Expected/observed scheduled heartbeats | `288 / 288` |
| First/last persisted heartbeat | `2026-08-25T05:15:02.047586Z` / `2026-08-26T05:10:02.048514Z` |
| Maximum heartbeat gap | `300.156976 seconds` |
| Gaps greater than 330 seconds | `0` |
| Sequence continuity | Strictly increasing; 288 unique sequence values |
| Scheduler | `succeeded`; run count progressed; lease skips `0`; last error empty |
| Incidents overlapping the window | `0` open, acknowledged, resolved or critical incidents |
| Agent Hub container | Healthy; restart count `0`; no fatal/traceback/uncaught exception |
| Read-only providers | CRM, Meta Ads, GA4, Social and n8n Lead Intake all healthy (`5/5`) |
| n8n heartbeat workflow | Active; 288 executions, 288 successes, 0 non-success |
| Redis | DB 1 namespace present; key count did not decrease abnormally |
| Receipts | Latest delivery and heartbeat receipts verified successfully |
| Public routes | Agent Hub ready, auth gate, n8n, CRM and SaleHub routes passed HTTPS/TLS smoke |
| Production writes | Disabled |
| External notifications | Disabled |

Lead activity freshness was evaluated separately from producer health. A quiet lead
stream was not misreported as a heartbeat outage, and no synthetic customer record was
created for this acceptance.

### Authorized SaleHub changes excluded from Agent Hub incidents

1. VSP staging Caddyfile work and the Caddy recreation at
   `2026-08-25T05:08:45Z`, followed by the SaleHub VSP policy promotion at
   `2026-08-25T06:33:50Z`.
2. The owner-confirmed SaleHub position-image auto-sync repair, including the Caddy
   recreation at `2026-08-26T04:34:23Z`, subsequent Caddyfile updates and the observed
   SaleHub release `releases/20260826-position-image-autosync-v1`.

For both maintenance periods, Caddy configuration validation passed and the shared
Agent Hub, n8n, CRM and SaleHub routes remained healthy. These planned changes did not
reset the Agent Hub observation window. The position-image feature itself still needs
owner visual/business acceptance; route health is not evidence that every unit image is
correct.

The final read-only recheck at `2026-08-26T06:06:47Z` confirmed the same SaleHub
release, a valid Caddy configuration, Agent Hub healthy with zero restarts, OpenAPI
`0.13.0`, the expected login redirect and HTTP 200/TLS-valid responses for Agent Hub
readiness, n8n health, CRM and SaleHub.

## What is live, preview-only and disabled

| Capability | State | Boundary |
|---|---|---|
| Command Center, Google login and viewer/operator/owner RBAC | Live | Owner-only approvals remain enforced |
| Campaign, attribution, provider health, heartbeat, audit and operational summaries | Live | Reads and deterministic analysis |
| CRM, Meta Ads, GA4, Social and n8n Lead Intake adapters | Live | Read-only |
| Phase 8.9 email/PWA/Zalo/ticket routing | Preview-only | `would_send=false`; providers are not configured |
| Experiment decisions | Preview-only | Recommendation/owner review; no autonomous execution |
| Ads launch or budget mutation | Disabled | Owner-gated future phase |
| CRM mass write and automatic customer contact | Disabled | No Agent Hub permission grant |
| Bulk Email or Zalo/ZBS send | Disabled | No provider execution credentials |
| WordPress production landing-page publish | Disabled | Preview/staging contract only |
| n8n Agent executor webhook | Disabled/blank | No production write orchestration |
| External notifications and retry/remediation executor | Disabled | Internal Command Center/audit only |

The existing internal Video Factory job-creation capability is separate from marketing
or customer-system writes and was not expanded by this stabilization.

## Issues resolved

- Production-ahead-of-`main` drift was removed through the ordered #16–#19 merges and
  exact `main`/receipt/runtime equivalence.
- Full CI now runs when a stacked PR is retargeted or marked ready for `main`.
- Phase 8.9 suppression semantics now make acknowledged, resolved and cooldown alerts
  report `escalation_would_apply=false`.
- Historical HMAC receipts can be verified through a verify-only keyring while new
  receipts use only the active signing key.
- Provider-health routing was extracted from the FastAPI god file without changing the
  public contract.
- Phase 8.8 retention and heartbeat execution persistence were stabilized before the
  observation window.
- SaleHub VSP policy and position-image changes were separated from Agent Hub incident
  evidence by timestamp, component and owner authorization.

## Backup and rollback evidence

- Deployment receipt:
  `/var/lib/npd-ai/agent-hub-deployments/deploy-20260825T050536Z.json`.
- Pre-deploy namespace backup:
  `/var/backups/npd-agent-hub/agent-hub-20260825T050536Z.json`.
- Rollback image: `npd-agent-hub:rollback-20260825T050536Z`.
- Agent Hub rollback remains namespace-scoped; Redis restoration is never automatic.
- SaleHub uses atomic release directories under `/opt/salehub/releases` and the
  `/opt/salehub/current` symlink. Its rollback must be coordinated with the SaleHub
  owner and must not be triggered by Agent Hub monitoring.
- Caddy changes use the existing `/opt/n8n/Caddyfile` and
  `n8n-marketing-caddy-1`; configuration must be backed up and validated in that
  container before any owner-approved reload/recreation.

## Technical debt and remaining work

Remaining work count at this handoff: **7 tracked items**.

1. PR [#22](https://github.com/vangnguyen/npd-ai-video-factory/pull/22) remains a
   draft historical governance/roadmap bundle. Useful material should be reconciled
   cleanly; its stale status snapshot should not be merged unchanged.
2. Legacy Video Factory PRs [#6](https://github.com/vangnguyen/npd-ai-video-factory/pull/6)
   and [#8](https://github.com/vangnguyen/npd-ai-video-factory/pull/8) remain draft and
   divergent. Clean-port #8 media QC before #6 production TTS; human Vietnamese voice
   listening remains a hard acceptance gate.
3. Continue incremental extraction from `main.py`, `store.py` and dashboard code in
   small API-parity PRs. Do not perform a rewrite or change Redis key formats.
4. Exercise the documented HMAC rotation procedure under an owner-approved maintenance
   window. The accepted production deployment was not rotated by this milestone.
5. Visually validate the SaleHub automatic position-image update on representative
   inventory records before calling that business fix accepted.
6. Preserve the known currency limitation: do not aggregate USD/VND executive revenue
   totals without a defined exchange-rate policy.
7. Re-check the historical SEO automation warning through execution evidence; an active
   workflow alone is not proof of health.

## Evidence versus inference

- Commit, image/version, routes, container restarts, scheduler counters, Redis metadata,
  receipt verification, provider state, CI runs and PR state are confirmed evidence.
- “The two applications operate as one platform” is the target operating model, not a
  claim that their repositories or runtimes have been physically merged.
- SaleHub position-image release promotion and shared-route health are confirmed; image
  correctness across inventory remains an owner acceptance gate.
- Phase 9 business value is a roadmap decision; no Phase 9 engine was implemented in
  this stabilization milestone.

## Exact next milestone

After the owner reviews this handoff, the next business milestone is **Phase 9 —
Customer Journey & Sales Intelligence**, delivered in three owner-reviewable increments:

1. read-only Customer Journey Projection;
2. deterministic, explainable Lead Scoring;
3. recommendation-only Next Best Action with reason, evidence, confidence and SLA.

No customer contact or channel execution should be enabled until this shared journey,
attribution and data-quality baseline has been accepted.
