# NPD AI Video Factory

NPD AI Video Factory is a data-driven video production system for Vietnamese real-estate content.

## Sprint 1 goal

Deliver one end-to-end 45-second vertical video through this path:

`n8n -> FastAPI -> script/storyboard -> TTS -> local footage -> video manifest -> Remotion -> final.mp4`

Sprint 1 deliberately excludes scene intelligence, ComfyUI, and automatic social publishing.

## Current implementation checkpoint

Tasks 1-9 are implemented on the Sprint 1 branch:

- FastAPI health, readiness, create-job, status, and safe artifact endpoints
- Redis-backed job records, idempotency, queue, monotonic stage/progress transitions, and artifact registration
- provider interfaces for structured content generation and Vietnamese TTS
- deterministic development content provider
- deterministic local asset resolver with minimum-asset validation
- video-manifest builder and Draft 2020-12 JSON Schema validation
- API tests executed by GitHub Actions

Next implementation targets are the Remotion renderer and resumable worker pipeline.

## Handoff package

- [Technical handoff](docs/technical-handoff.md)
- [Codex implementation prompt](docs/CODEX_SPRINT_1_PROMPT.md)
- [13-task implementation plan](docs/implementation-plan.md)
- [API contract and error model](docs/api-contract.md)
- [Acceptance tests](docs/acceptance-tests.md)
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
