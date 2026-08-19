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

## Local verification

Copy `.env.example` to `.env`, provide at least five local image/video assets in the configured project folder, then run:

```bash
docker compose up -d --build
./scripts/e2e-smoke.sh
```

Generated media stays under `storage/jobs/` and is intentionally excluded from Git.
