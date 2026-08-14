# Codex Prompt: Implement Sprint 1

Implement the NPD AI Video Factory Sprint 1 vertical slice in this repository.

Read, in order:

1. `docs/technical-handoff.md`
2. `docs/api-contract.md`
3. `packages/contracts/video-manifest.schema.json`
4. `docs/implementation-plan.md`
5. `docs/acceptance-tests.md`

Work through the 13 tasks in order. Keep each task reviewable and test-backed. Preserve the API and manifest contracts unless a blocking inconsistency is documented in the pull request.

Definition of done:

- `docker compose up --build` starts API, Redis, worker, and renderer.
- The sample request creates a job and returns a stable job ID.
- The worker uses testable provider interfaces for script/storyboard and TTS.
- At least five local fixture clips are selected without Vision AI.
- The generated manifest validates against the committed JSON Schema.
- Remotion produces a 1080x1920 H.264 MP4 approximately 45 seconds long.
- The status endpoint exposes progress, stage, artifacts, and structured failures.
- The n8n workflow is importable, inactive by default, and completes the smoke test.
- Unit, contract, and end-to-end tests pass.

Do not add ComfyUI, Vision AI, stock providers, auto-publishing, a dashboard, or analytics in this sprint.
