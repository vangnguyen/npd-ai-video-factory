# NPD unified SaleHub–AgentHub work summary

## Document status

- Snapshot: `2026-08-29 00:49 Asia/Ho_Chi_Minh`.
- Repository: `vangnguyen/npd-ai-video-factory`.
- Documentation branch: `docs/stabilization-closeout-20260826`.
- Stable source revision: `400899ba82501beeea469f4a33dc169a9a09bb8e`.
- Agent Hub release: `0.13.0`.
- Production acceptance: **PASS** for the fixed 24-hour window from
  `2026-08-25T05:11:00Z` through `2026-08-26T05:11:00Z`.
- This change set is documentation-only. It records separately authorized production
  maintenance and reliability actions; it does not merge a feature PR, tag, deploy a new
  application version, reload Caddy or enable an execution capability.

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

The 2026-08-26 closeout also completed the owner-gated HMAC rotation drill, the one-shot
WordPress pricing synchronization accepted under the owner's existing WAF-rule decision,
three separate AgentHub god-file extraction PRs, the VND-only contract PR, and clean
replacement PRs for both divergent Video Factory branches. The SEO publisher received a
bounded structured-output retry and passed a real dry-run. The next eight natural
scheduled executions on 2026-08-27 and 2026-08-28 completed successfully and their
WordPress publication contract was independently verified.

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
| SaleHub position-image maintenance | Automatic unit-position image synchronization fix | Release `releases/20260826-position-image-autosync-v1` accepted on representative live inventory; timer and first-party image index verified |
| SaleHub pricing sync | One-shot VPS-to-WordPress policy synchronization | PASS; issue #28 closed after the owner accepted the current WAF exception scope |
| Reliability closeout | HMAC active-key rotation from v1 to v2 | Live; v1 retained as verify-only and both receipt generations verified |
| SEO publisher | Structured-output parse recovery | Live in `content-publisher`; direct `force=true,dry_run=true` acceptance plus eight natural scheduled executions on 2026-08-27 and 2026-08-28 passed |
| Video Factory legacy cleanup | Clean ports for PR #8 and then PR #6 | Draft PRs #34 and #35; legacy PRs closed without merge |
| Video Factory owner voice | V2 rejected; V3 regenerated without overwriting V2 | V3 technical QC passed; issue #5 remains open for explicit human listening acceptance |

The detailed phase contracts remain in [Campaign Operating System](./PHASE_6B_CAMPAIGN_OPERATING_SYSTEM.md),
[Attribution & Revenue OS](./PHASE_7_ATTRIBUTION_REVENUE_OS.md),
[Experiment & Optimization OS](./PHASE_8_EXPERIMENT_OPTIMIZATION_OS.md) and the
[Phase 8.9 routing document](./PHASE_8_9_ALERT_ROUTING_PREVIEW.md). The corrected
[architecture roadmap](./ARCHITECTURE_ROADMAP.md),
[Phase 9 proposal](./NEXT_PHASE_CUSTOMER_JOURNEY_SALES_INTELLIGENCE.md),
[branch-protection contract](./GITHUB_BRANCH_PROTECTION.md),
[incremental refactor plan](./AGENT_HUB_INCREMENTAL_REFACTOR_PLAN.md) and
[legacy Video Factory audit](./VIDEO_FACTORY_LEGACY_PR_AUDIT.md) were clean-ported from
the useful documentation in PR #22 without carrying its obsolete workflow changes.

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
| [#22](https://github.com/vangnguyen/npd-ai-video-factory/pull/22) | Historical stabilization/governance bundle | Superseded; useful docs clean-ported through #26, obsolete workflow diff not merged |
| [#27](https://github.com/vangnguyen/npd-ai-video-factory/pull/27) | Run protected-branch CI gates for every PR | Merged as `084ce84`; governance-only, no runtime change |
| [#26](https://github.com/vangnguyen/npd-ai-video-factory/pull/26) | Unified SaleHub–AgentHub summary and handoff | This documentation milestone; no runtime change |

Post-baseline work remains isolated in reviewable PRs and is not part of the current
AgentHub production image:

| Pull request | Scope | Current disposition |
|---:|---|---|
| [#30](https://github.com/vangnguyen/npd-ai-video-factory/pull/30) | Extract delivery/heartbeat routes from `main.py` | Draft; API-preserving; checks green |
| [#31](https://github.com/vangnguyen/npd-ai-video-factory/pull/31) | Extract the store protocol from `store.py` | Draft; stable re-export; checks green |
| [#32](https://github.com/vangnguyen/npd-ai-video-factory/pull/32) | Extract dashboard response/security shell | Draft; byte-contract parity; checks green |
| [#33](https://github.com/vangnguyen/npd-ai-video-factory/pull/33) | Enforce VND-only new business contracts | Draft; non-VND fails closed; checks green |
| [#34](https://github.com/vangnguyen/npd-ai-video-factory/pull/34) | Clean-port useful Sprint 1/media-QC work from legacy PR #8 | Draft; full CI and Docker E2E green |
| [#35](https://github.com/vangnguyen/npd-ai-video-factory/pull/35) | Clean-port production-pilot/TTS work from legacy PR #6 | Draft stacked on #34; applicable GitHub checks and local full Docker E2E green; human voice gate open |

None of #30–#35 has been merged or deployed by this closeout.

The production deployment receipt and live AgentHub runtime resolve to
`400899ba82501beeea469f4a33dc169a9a09bb8e`. The annotated tag
`agent-hub-v0.13.0` resolves to that exact accepted runtime commit. GitHub `main`
also contains the later CI-governance commit `084ce84`; it changes workflow triggers
only, so `main` remains runtime-equivalent to production and is the source of truth.

The stable release tag is `agent-hub-v0.13.0`; it must not be moved to a later docs or
governance commit because the tag identifies the deployed binary source exactly.

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

The organization-level currency decision is now **VND only** for new Campaign OS,
Opportunity and attribution contracts. PR #33 implements that decision by rejecting
explicit non-VND provider data rather than relabeling or applying an implicit exchange
rate. It is still draft and therefore is not represented as live in AgentHub 0.13.0;
historical USD records remain immutable audit evidence only.

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
reset the Agent Hub observation window.

Representative browser acceptance on 2026-08-26 confirmed all four current Vinhomes
Saigon Park inventory cards used first-party, versioned position images matching their
unit codes (`TL12-37`, `TL14-39`, `AS47-30`, `AS77-36`). The `TL12-37` detail modal
rendered the corresponding image at its natural size. The timer-backed index independently
confirmed `104` unit images across four projects, `warnings=0`, Drive
`authMode=oauth_readonly`, and a successful image/knowledge refresh. This accepts the
mechanism and the representative VSP business sample; it does not authorize fuzzy unit
matching where an exact current unit code is absent.

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
- The owner-gated HMAC drill moved active signing to `npd-attribution-v2`, retained
  `npd-attribution-v1` as verify-only, and verified old delivery/heartbeat receipts plus
  a new v2 heartbeat without exposing secret material.
- WordPress pricing synchronization ran exactly once from the VPS and passed the public
  contract check; issue #28 is closed. The owner explicitly accepted the existing WAF
  exception scope and chose not to pursue a narrower rule in this milestone.
- The SEO publisher's repeated structured-output failures were traced through n8n
  execution records. A fence-tolerant parser plus one bounded retry was deployed only to
  `content-publisher`; a real dry-run passed without a WordPress post side effect. The
  next eight natural scheduled calls returned HTTP 200 and produced eight independently
  verified published WordPress posts with featured media.
- Legacy PR #8 and PR #6 were replaced in order by clean draft PRs #34 and #35, then
  closed without merge. Issue #7 was closed as not planned because its generic content
  network conflicts with the accepted NPD real-estate roadmap.

## Backup and rollback evidence

- Deployment receipt:
  `/var/lib/npd-ai/agent-hub-deployments/deploy-20260825T050536Z.json`.
- Pre-deploy namespace backup:
  `/var/backups/npd-agent-hub/agent-hub-20260825T050536Z.json`.
- Rollback image: `npd-agent-hub:rollback-20260825T050536Z`.
- HMAC rotation namespace backup:
  `/var/backups/npd-agent-hub/hmac-rotation-20260826T100000Z/agent-hub-before-rotation.json`
  (`4002` AgentHub Redis keys at capture time).
- HMAC configuration backup:
  `/var/backups/npd-agent-hub/hmac-rotation-20260826T100000Z/config/agent-hub.env-20260826T095854Z`.
- HMAC drill deploy receipt:
  `/var/lib/npd-ai/agent-hub-deployments/deploy-20260826T095855Z.json`; rollback image
  `npd-agent-hub:rollback-20260826T095855Z`.
- SEO publisher backup:
  `/var/backups/npd-content-publisher/seo-json-retry-20260826T102459Z`; rollback image
  `n8n-marketing-content-publisher:rollback-20260826T102459Z`.
- Agent Hub rollback remains namespace-scoped; Redis restoration is never automatic.
- SaleHub uses atomic release directories under `/opt/salehub/releases` and the
  `/opt/salehub/current` symlink. Its rollback must be coordinated with the SaleHub
  owner and must not be triggered by Agent Hub monitoring.
- Caddy changes use the existing `/opt/n8n/Caddyfile` and
  `n8n-marketing-caddy-1`; configuration must be backed up and validated in that
  container before any owner-approved reload/recreation.

## Natural SEO schedule acceptance follow-up

The remaining scheduled-execution evidence gate is **PASS**. No workflow, container,
credential, publication setting or execution-retention setting was changed during this
read-only follow-up.

- n8n kept `BDS - 08 Biên tập và đăng bài SEO tự động` active with cron
  `0 8,10,12,14 * * *`; the n8n startup log recorded activation of workflow
  `c18ac267-3f70-49e0-8e0c-d216df31ae8c`.
- `content-publisher` received four natural `POST /run` calls on 2026-08-27 at
  `08:01`, `10:01`, `12:01` and `14:01` Asia/Ho_Chi_Minh, then the same four slots on
  2026-08-28. All eight returned HTTP 200.
- Persisted `/data/content-state.json` advanced to 54 runs, `last_error=null`; the eight
  new entries were `ok=true`, used two to eight cited sources, and recorded WordPress
  post IDs `28068`, `28070`, `28072`, `28074`, `28076`, `28078`, `28080` and `28082`.
- WordPress REST independently returned `status=publish` plus a non-zero
  `featured_media` for all eight IDs. The first 2026-08-27 page and the latest
  2026-08-28 page also returned public HTTPS 200 with valid TLS.
- n8n intentionally has `EXECUTIONS_DATA_SAVE_ON_SUCCESS=none`, so successful execution
  rows and IDs are not retained in `execution_entity`. The acceptance evidence is the
  registered schedule and activation log, timestamped downstream access log, durable
  publisher state and independently queried WordPress contract. The absence of a
  retained n8n success row is not represented as an execution failure.

This is evidence for the pre-existing authorized SEO publication workflow. It does not
enable an AgentHub write, external-notification or WordPress landing-page publication
capability and does not widen any accepted safety boundary.

## Technical debt and remaining work

Remaining closeout work count: **3 tracked review/owner/monitoring gates**.

1. Review and merge the isolated PRs in dependency-safe order. #30, #31 and #32 are
   independent refactors; #33 is the VND-only behavior change; #34 must precede stacked
   #35. Re-run the required protected-branch checks after any rebase/retarget.
2. Keep issue [#5](https://github.com/vangnguyen/npd-ai-video-factory/issues/5) open until
   the owner listens to and explicitly accepts the Vietnamese production-pilot voice.
   The owner rejected V2 on 2026-08-29 because “Ngọc” still sounded like “nọc”. A new,
   versioned V3 was generated with OpenAI `gpt-4o-mini-tts` voice `nova`, targeting a
   female Vietnamese voice around 25–30 with a soft, warm and professional delivery.
   To remove the nasal coarticulation in “Nhắn Ngọc”, the CTA was changed without changing
   intent to “Liên hệ với Ngọc Phương Đông để đặt lịch xem mô hình dự án.” Narration,
   headline and subtitle use the same text. The 30.059-second 1080x1920 H.264/AAC render
   passed black-frame, six-scene audio, loudness and manifest-sync checks; both
   `gpt-4o-transcribe` and `whisper-1` recognized “Ngọc Phương Đông” from the muxed MP4.
   Video SHA-256 is
   `9add7bf1b94b1d0a34eddb3a3acd6392d627c4342a3e67c14251f268094bddaf`.
   Automated media QC still cannot satisfy the human timbre/quality gate.
3. Treat the current pricing-sync WAF exception as an owner-accepted security decision.
   Do not claim it was narrowed; monitor the route and revisit only if the owner changes
   that decision or new evidence shows collateral exposure.

## Evidence versus inference

- Commit, image/version, routes, container restarts, scheduler counters, Redis metadata,
  receipt verification, provider state, CI runs and PR state are confirmed evidence.
- “The two applications operate as one platform” is the target operating model, not a
  claim that their repositories or runtimes have been physically merged.
- SaleHub position-image release promotion, timer execution and the representative 4/4
  VSP image sample are confirmed. Coverage for units whose current code has no exact
  source image remains a data-availability limitation, not an inferred match.
- The SEO production change, direct dry-run and eight natural scheduled publications are
  confirmed. Because n8n does not retain successful executions, the scheduled result is
  established by correlated trigger/access timestamps, durable publisher state and the
  live WordPress REST/public contract rather than inferred from service health.
- VND-only behavior is confirmed in PR #33 tests and CI, but remains draft/unmerged and
  is not claimed as production behavior.
- Phase 9 business value is a roadmap decision; no Phase 9 engine was implemented in
  this stabilization milestone.

## Exact next milestone

After the owner reviews the isolated closeout PRs and dispositions the remaining Video
Factory voice gate, the next business milestone is **Phase 9 — Customer Journey & Sales
Intelligence**, delivered in three
owner-reviewable increments:

1. read-only Customer Journey Projection;
2. deterministic, explainable Lead Scoring;
3. recommendation-only Next Best Action with reason, evidence, confidence and SLA.

No customer contact or channel execution should be enabled until this shared journey,
attribution and data-quality baseline has been accepted.
