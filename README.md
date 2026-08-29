# NPD AI Video Factory

NPD AI Video Factory is a data-driven video production system for Vietnamese real-estate content.

## Sprint 1 goal

Deliver one end-to-end 45-second vertical video through this path:

`n8n -> FastAPI -> script/storyboard -> TTS -> local footage -> video manifest -> Remotion -> final.mp4`

Sprint 1 deliberately excludes scene intelligence, ComfyUI, and automatic social publishing.

## Sprint 1 status

Tasks 1-13 are implemented and the Docker Compose vertical slice is verified:

- FastAPI health, readiness, create-job, status, and safe artifact endpoints
- Redis-backed job records, idempotency, queue, monotonic stage/progress transitions, and artifact registration
- provider interfaces for structured content generation and Vietnamese TTS
- deterministic development content provider
- deterministic local asset resolver with minimum-asset validation
- video-manifest builder and Draft 2020-12 JSON Schema validation
- `real-estate-short-v1` Remotion renderer at 1080x1920, 30 fps, H.264 + AAC
- resumable Redis worker with artifact reuse, stable cross-service error codes, and FFprobe QC
- inactive n8n smoke-test workflow with bounded polling and terminal error/timeout output
- Python, renderer, contract, and Docker Compose E2E checks in GitHub Actions

The verified Sprint 1 proof is recorded in [Sprint 1 acceptance evidence](docs/sprint-1-acceptance-evidence.md).

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
Phase 7 snapshot, accepts provenance-bound variant observations from read-only sources,
and produces advisory `winner_candidate`/`continue`/`stop_and_review` recommendations.
There is no live execution endpoint and no traffic, budget, CMS or CRM mutation.

Phase 8.4 adds an owner-verified Campaign identity registry and a pseudonymous,
read-only touchpoint-ingestion quality gate. It reports mapping coverage, freshness,
unknown identities and conflicts; it never infers projects from Ads names or enables
external writes.

Phase 8.5 adds a durable Lead Intake attribution exception queue. Unknown/conflicting
events remain privacy-safe and outside the immutable ledger until verified evidence
resolves exactly one Campaign; operator replay is internal shadow-only and idempotent.

Phase 8.6 wraps read-only attribution delivery with tamper-evident HMAC receipts,
bounded producer retry/dead-letter evidence and per-source freshness SLOs. It observes
delivery health but never schedules retries or enables source-system writes.

Phase 8.7 adds bounded read-only provider probes and deduplicated internal alert
routing. Health/alert state persists in a dedicated Agent Hub Redis subnamespace;
acknowledgement is an internal audit action only. No Zalo/email/PWA notification,
provider retry, source mutation or production write is enabled.

Phase 8.8 separates n8n Lead Intake liveness from lead volume with signed, PII-free
heartbeat receipts. A Redis-lease scheduler evaluates cached state internally; it does
not poll providers, send notifications, retry delivery or enable production writes.

## Handoff package

- [Technical handoff](docs/technical-handoff.md)
- [Codex implementation prompt](docs/CODEX_SPRINT_1_PROMPT.md)
- [13-task implementation plan](docs/implementation-plan.md)
- [API contract and error model](docs/api-contract.md)
- [Acceptance tests](docs/acceptance-tests.md)
- [Phase 6B Campaign Operating System](docs/PHASE_6B_CAMPAIGN_OPERATING_SYSTEM.md)
- [Phase 7 Attribution & Revenue OS](docs/PHASE_7_ATTRIBUTION_REVENUE_OS.md)
- [Phase 8 Experiment & Optimization OS](docs/PHASE_8_EXPERIMENT_OPTIMIZATION_OS.md)
- [Phase 8.4 Campaign Identity & Attribution Data Quality](docs/PHASE_8_4_CAMPAIGN_IDENTITY_DATA_QUALITY.md)
- [Phase 8.5 Lead Intake Attribution Operations](docs/PHASE_8_5_LEAD_INTAKE_ATTRIBUTION_OPERATIONS.md)
- [Phase 8.6 Ingestion Delivery Observability](docs/PHASE_8_6_INGESTION_DELIVERY_OBSERVABILITY.md)
- [Phase 8.7 Provider Health & Internal Alert Routing](docs/PHASE_8_7_PROVIDER_HEALTH_ALERT_ROUTING.md)
- [Phase 8.8 Lead Intake Heartbeat & Scheduled Health](docs/PHASE_8_8_HEARTBEAT_SCHEDULED_HEALTH.md)
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

## Local verification

Copy `.env.example` to `.env`, provide at least five local image/video assets in the configured project folder, then run:

```bash
docker compose up -d --build
./scripts/e2e-smoke.sh
```

Generated media stays under `storage/jobs/` and is intentionally excluded from Git.
