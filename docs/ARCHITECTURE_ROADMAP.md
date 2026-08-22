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

Release state is distinct from implementation state. On the 2026-08-22 stabilization
baseline, `main` ends at 8.4/Agent Hub 0.12.4, 8.5–8.8 are stacked draft PRs, production is
running the reviewed 8.8/0.12.9 commit inside its 48-hour acceptance window, and 8.9 is
preview-only and not deployed. The sequential merge gate is #16, #17, #18, then #19 only
after the 8.8 window passes. PR #20 remains last.

## Phase 9 — Customer Journey and Sales Intelligence

- Customer Journey Engine;
- explainable Lead Scoring Engine;
- recommendation-only Next Best Action;
- sales SLA and funnel evidence;
- no automatic customer contact.

Phase 9 begins only after the stabilization stack is merged to `main`, production is
equivalent to a reviewed `main` commit, and full CI is green.

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

