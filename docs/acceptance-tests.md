# Sprint 1 Acceptance Tests

## Contract tests

- [x] The sample request is accepted and unknown properties are rejected.
- [x] A generated manifest validates against `video-manifest.schema.json`.
- [x] Scene order is monotonic and total duration is within 100 ms of metadata duration.
- [x] Only `video` and `image` local visual types are accepted in Sprint 1.

## API tests

- [x] Create returns HTTP 202 and a unique `vid_` job ID.
- [x] Repeating the same `Idempotency-Key` returns the original job at the state-store layer.
- [x] Status transitions never move backward.
- [x] Missing jobs and path-traversal artifact requests fail safely.
- [x] Artifact serving is limited to artifacts recorded on the job.

These API/contract tests are executed by `.github/workflows/api-ci.yml`.

## Worker tests

- [x] Deterministic providers produce repeatable pipeline artifacts end-to-end.
- [x] A worker interruption at render resumes from validated content/TTS/manifest artifacts.
- [x] Transient renderer network errors are retried with a bounded policy.
- [x] Non-retryable provider, asset, manifest, renderer, and QC errors use stable codes and terminate in `failed`.

## Renderer tests

- [x] Composition is 1080x1920 at 30 fps.
- [x] Output uses H.264 video and AAC audio.
- [x] Output video stream is 45.000 seconds; MP4 container is 45.056 seconds.
- [x] Subtitles remain inside mobile-safe margins with three-line clamping and Vietnamese Noto Sans glyph coverage.
- [x] Logo and CTA appear during the expected timeline ranges.

## End-to-end test

1. [x] Place five copyright-safe local image fixtures under the configured project asset folder.
2. [x] Start the Compose stack.
3. [x] Import the inactive n8n smoke workflow with the n8n CLI and validate bounded terminal branches.
4. [x] Submit the committed Vinhomes Green Paradise request.
5. [x] Observe bounded polling until `awaiting_review`.
6. [x] Verify the final MP4 exists, is playable, and passes FFprobe metadata assertions.
7. [x] Record the job ID, manifest validation result, video metadata, and test results in the acceptance evidence.
