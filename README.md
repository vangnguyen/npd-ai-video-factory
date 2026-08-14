# NPD AI Video Factory

NPD AI Video Factory is a data-driven video production system for Vietnamese real-estate content.

## Sprint 1 goal

Deliver one end-to-end 45-second vertical video through this path:

`n8n -> FastAPI -> script/storyboard -> TTS -> local footage -> video manifest -> Remotion -> final.mp4`

Sprint 1 deliberately excludes scene intelligence, ComfyUI, and automatic social publishing.

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

The Docker Compose file is a contract for the implementation. It becomes runnable as the API, worker, and renderer tasks are completed.
