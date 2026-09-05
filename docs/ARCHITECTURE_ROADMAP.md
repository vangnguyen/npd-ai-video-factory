# NPD AI architecture roadmap

This document is the canonical phase naming. It corrects documentation drift without
renaming existing code, Redis keys, APIs, tags or historical pull requests.

## Implemented foundation

- Phase 1–5 — Agent Hub and production foundation.
- Phase 6A — read-only marketing intelligence.
- Phase 6B — Campaign Operating System, planning/draft/preview by default.
- Phase 7 — Attribution and Revenue OS.
- Phase 8A — Experiment and Optimization OS, preview/approval bounded.
- Phase 8B — reliability track:
  - 8.4 Campaign Identity and Data Quality;
  - 8.5 Intake Exceptions;
  - 8.6 Delivery Observability;
  - 8.7 Provider Health;
  - 8.8 Heartbeat and Scheduler;
  - 8.9 Alert Routing Preview.

Release state is distinct from implementation state. The 2026-08-26 stable runtime is
Agent Hub `0.13.0` at commit
`400899ba82501beeea469f4a33dc169a9a09bb8e`, tagged
`agent-hub-v0.13.0`. Phase 8.5–8.9 and their reliability prerequisites are merged;
the fixed 48-hour Phase 8.8 gate and the later 24-hour 0.13.0 post-deploy window passed.
This is historical release evidence, not a claim that the current live runtime has
been inspected. Later `main` includes Phase 9 source through PR #61 at
`82fd18a3e524b13b479bb73d66c962620c6e8d9b`; these changes are not documentation-only.
Phase 9 production-shadow activation and business acceptance are separate from source
merge. Alert routing in the accepted release is a deterministic preview, while
external delivery remains disabled.

## Phase 9 — Customer Journey and Sales Intelligence

- Customer Journey Engine;
- explainable Lead Scoring Engine;
- recommendation-only Next Best Action;
- sales SLA and funnel evidence;
- no automatic customer contact.

The original entry prerequisites are the stabilization handoff, green CI and resolution
or explicit separate disposition of the WordPress/Imunify360 pricing-sync issue #28.
Issue #28 is now closed as completed in GitHub; do not report its historical description
as an open blocker. Historical draft PR dispositions are not implicitly approved.
Phase 9A remains read-only.

Phase 9A/9B core services and version-bound NBA v2 review telemetry are on `main` through
PR #61. The next product milestone is an evidence-backed internal marketing/sales pilot,
not Phase 10 execution. See [Phase 9 marketing pilot](PHASE_9_MARKETING_PILOT.md) for the
opt-in Commander workflow, input contract, UAT and remaining live-data/UI work. Source
checks, fixture results, deployment state and business acceptance must stay distinct.

## Phase 10 — Controlled Channel Execution

- owner-gated Meta Ads execution;
- Google Ads production API;
- dedicated Email Marketing provider;
- dedicated Zalo/ZBS provider;
- WordPress landing-page production publisher.

Each capability needs least-privilege credentials, dry-run/preview, approval records,
idempotency, rollback and a channel-specific acceptance gate. No capability is implied by
its place on the roadmap.

## Phase 11 — Creative and CRO Optimization

- controlled creative experiments;
- landing-page CRO;
- owner-gated rollout and rollback;
- no autonomous production loop by default.

## Phase 12 — Executive Revenue Control Tower

- portfolio revenue cockpit;
- Daily Executive Brief;
- AI/API cost governance;
- portfolio-level decision support with evidence and confidence.

## Permanent safety boundaries

Unless a later owner-approved phase explicitly replaces an individual boundary, external
notifications, Ads mutation, CRM mass write, customer messaging, bulk Email/ZBS, CMS
production publish, autonomous experiments and the n8n write executor remain disabled.
The existing n8n, Caddy and Redis are reused; parallel infrastructure is not created.
