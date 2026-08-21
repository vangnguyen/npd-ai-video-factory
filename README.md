# NPD AI Video Factory

NPD AI Video Factory is a data-driven video production system for Vietnamese real-estate content.

## Sprint 1 goal

Deliver one end-to-end 45-second vertical video through this path:

`n8n -> FastAPI -> script/storyboard -> TTS -> local footage -> video manifest -> Remotion -> final.mp4`

Sprint 1 deliberately excludes scene intelligence, ComfyUI, and automatic social publishing.

## Current implementation checkpoint

Sprint 1 Tasks 1-13 are implemented and covered by Docker Compose E2E:

- FastAPI health, readiness, create-job, status, and safe artifact endpoints
- Redis-backed job records, idempotency, queue, monotonic stage/progress transitions, and artifact registration
- provider interfaces for structured content generation and Vietnamese TTS
- deterministic development content provider
- deterministic local asset resolver with minimum-asset validation
- video-manifest builder and Draft 2020-12 JSON Schema validation
- API, worker, renderer, QC and Docker Compose E2E tests executed by GitHub Actions

The separate Agent Hub workstream has completed the accepted production baseline
`agent-hub-v0.9.0`, including Phase 5.1 deterministic business-answer evals and
Phase 6 read-only CRM, Meta Ads, GA4 and Social integrations with dedicated
least-privilege credentials.

Phase 6B adds an attribution-ready Campaign Operating System, merged through PR #11
into `main`: unified campaign IDs, lifecycle/RBAC/approval boundaries, channel
planning, specialist agents and a responsive Campaign Workspace. It is deliberately
limited to research, plan, draft and preview; production writes remain disabled.

Phase 7 builds on that draft with an immutable touchpoint ledger, read-only
Opportunity/revenue reconciliation, an owner-controlled data-quality gate and
first-touch/last-touch/linear shadow reports. It does not calculate or expose revenue
until the reconciliation snapshot is accepted, and it enables no external writes.

Phase 8 adds a controlled Experiment & Optimization OS. It requires an owner-accepted
Phase 7 snapshot and produces hypothesis/variant/KPI/guardrail/stop-condition plans and
previews only. There is no live execution endpoint and no traffic, budget, CMS or CRM
mutation.

## Handoff package

- [Technical handoff](docs/technical-handoff.md)
- [Codex implementation prompt](docs/CODEX_SPRINT_1_PROMPT.md)
- [13-task implementation plan](docs/implementation-plan.md)
- [API contract and error model](docs/api-contract.md)
- [Acceptance tests](docs/acceptance-tests.md)
- [Phase 6B Campaign Operating System](docs/PHASE_6B_CAMPAIGN_OPERATING_SYSTEM.md)
- [Phase 7 Attribution & Revenue OS](docs/PHASE_7_ATTRIBUTION_REVENUE_OS.md)
- [Phase 8 Experiment & Optimization OS](docs/PHASE_8_EXPERIMENT_OPTIMIZATION_OS.md)
- [Video manifest JSON Schema](packages/contracts/video-manifest.schema.json)
- [n8n smoke-test workflow](workflows/n8n/sprint-1-smoke-test.json)
- [45-second sample request](examples/vinhomes-green-paradise.request.json)

## Intended local layout

```text
apps/api/                    FastAPI HTTP service
services/worker/             Redis-backed pipeline worker
renderer/                    Remotion renderer and template
packages/contracts/          Cross-service JSON contracts
workflows/n8n/               Inactive importable workflows
storage/assets/              Local Sprint 1 footage
storage/jobs/                Generated job artifacts
```

The Docker Compose file is the runtime contract for the implementation.
