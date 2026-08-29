# Sprint 1 Implementation Plan

## Completed

1. Bootstrap the Python/TypeScript monorepo.
2. Codify request, status, and video-manifest contracts.
3. Create the FastAPI skeleton and health endpoints.
4. Implement Redis-backed job state and monotonic transitions.
5. Implement create/status/artifact endpoints.
6. Implement content-director provider interfaces.
7. Implement Vietnamese TTS provider interfaces.
8. Implement deterministic local-asset resolution.
9. Build and validate video manifests.

The API foundation is covered by GitHub Actions CI. The current CI installs `apps/api[dev]` and runs pytest on pushes to the Sprint 1 branch and pull requests to `main`.

## Completed vertical slice

10. [x] Implement the `real-estate-short-v1` Remotion renderer.
   - create a real composition at 1080x1920, 30 fps
   - consume the committed manifest contract only
   - render local video/image scenes
   - overlay logo, CTA, and subtitles
   - expose `/render` and return structured errors
   - emit progress that can be mapped to overall job progress 70-95

11. [x] Implement the resumable worker pipeline.
   - dequeue `npd:video-jobs:queue`
   - resume from the latest valid artifact/stage
   - run content -> TTS -> subtitles -> assets -> manifest -> render -> QC
   - persist each artifact and register it in Redis job state
   - map provider/renderer failures to stable error codes

12. [x] Complete the inactive n8n smoke-test workflow.
   - submit the sample request
   - bounded polling
   - stop at `awaiting_review` or `failed`
   - return the final artifact URL

13. [x] Prove the vertical slice with contract, unit, renderer, and E2E evidence.
   - GitHub Actions for Python and renderer tests
   - Docker Compose smoke test
   - final 45-second 1080x1920 H.264 MP4
   - record job ID, manifest validation result, ffprobe metadata, and test results in the Sprint 1 PR

Tasks 10-13 are complete. See `docs/sprint-1-acceptance-evidence.md` for the verified job and media metadata. Sprint 2 remains out of scope until this PR is reviewed and merged.

## Scope guard

Do not add Vision AI, ComfyUI, stock providers, dashboards, automatic publishing, or analytics during Sprint 1.

This historical Sprint 1 scope is complete. Later Agent Hub analytics and multi-agent
work are isolated in `services/agent_hub` and do not change the Sprint 1 runtime contract.
