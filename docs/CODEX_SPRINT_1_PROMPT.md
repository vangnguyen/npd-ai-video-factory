# Codex Prompt: Continue Sprint 1

Continue the NPD AI Video Factory Sprint 1 vertical slice in this repository.

Tasks 1-9 are already implemented on `codex/sprint-1-vertical-slice`. Do not redo them unless a failing test requires a targeted fix.

Read, in order:

1. `docs/technical-handoff.md`
2. `docs/api-contract.md`
3. `packages/contracts/video-manifest.schema.json`
4. `docs/implementation-plan.md`
5. `docs/acceptance-tests.md`

Start at **Task 10**.

## Task 10 — Remotion renderer

Implement `real-estate-short-v1` as a real Remotion composition:
- 1080x1920, 30 fps
- consume only the committed video manifest
- local MP4/image scene playback
- narration audio when `voice` exists
- subtitle overlays in mobile-safe margins
- NPD logo area and final CTA
- `/render` service endpoint with bounded, structured failures
- H.264 MP4 output to the requested shared-storage path

## Task 11 — resumable worker

Replace the worker placeholder with the pipeline:

`content -> TTS -> subtitles -> local assets -> manifest -> renderer -> QC -> awaiting_review`

Requirements:
- resume from validated artifacts after restart
- register artifacts in Redis job state
- keep progress monotonic
- map failures to stable contract error codes
- retry only transient provider/renderer errors

Then complete Tasks 12-13: n8n smoke flow and E2E proof.

Do not add ComfyUI, Vision AI, stock providers, auto-publishing, a dashboard, or analytics in Sprint 1.

Before finishing, run all CI/test commands and report any blocked external credential or missing licensed media fixture explicitly.
