# NPD AI Video Factory — Sprint 1 Technical Handoff

## Objective

Build the first end-to-end vertical slice:

`n8n -> FastAPI -> script/storyboard -> TTS -> local footage -> video manifest -> Remotion -> final.mp4`

The output target is a Vietnamese 45-second 9:16 real-estate video, rendered without manual editing and exposed as a job artifact for review.

## Current implementation status

Tasks 1-9 are implemented on `codex/sprint-1-vertical-slice` and covered by API CI:

- strict FastAPI request/status contracts
- Redis-backed job state, idempotency, queue, monotonic transitions, and artifact registration
- safe artifact download endpoint
- content provider and Vietnamese TTS interfaces
- deterministic development content provider
- deterministic local asset resolver
- manifest builder and Draft 2020-12 JSON Schema validation

Implementation should now start at Task 10 (Remotion), then Task 11 (resumable worker), Task 12 (n8n smoke flow), and Task 13 (E2E proof).

## Runtime topology

```text
n8n
  |
  | POST /api/v1/video-jobs
  v
FastAPI API
  |
  +--> Redis job state
  +--> npd:video-jobs:queue
              |
              v
         Worker service
              |
              +--> Content provider
              +--> Vietnamese TTS provider
              +--> Subtitle generation
              +--> Local asset resolver
              +--> Manifest builder / validator
              +--> Remotion renderer
              +--> ffprobe quality check
```

## Sprint 1 service boundaries

### API
- `GET /healthz`
- `GET /readyz`
- `POST /api/v1/video-jobs`
- `GET /api/v1/video-jobs/{job_id}`
- `GET /api/v1/video-jobs/{job_id}/artifacts/{artifact_name}`

### Redis
- job key: `npd:video-job:{job_id}`
- idempotency key: `npd:video-idempotency:{key}`
- queue: `npd:video-jobs:queue`

### Renderer
- `POST /render`
- reads the committed video manifest only
- writes `final.mp4` under the job directory

## Canonical state flow

```text
queued
  -> scripting
  -> storyboarding
  -> generating_voice
  -> generating_subtitles
  -> resolving_assets
  -> building_manifest
  -> rendering
  -> quality_check
  -> awaiting_review
```

Any stage may terminate in `failed`. Progress must never decrease.

## Artifact model

Every generated file must live below:

`storage/jobs/{job_id}/`

Expected artifacts:

```text
script.json
storyboard.json
narration.mp3 or narration.wav
subtitles.srt
video-manifest.json
final.mp4
video-metadata.json
```

An artifact must be registered in Redis before the API will serve it.

## Renderer target

Template: `real-estate-short-v1`

- 1080x1920
- 30 fps
- H.264 MP4
- local MP4/image scenes
- optional narration audio from `voice.audio_uri`
- subtitle overlays in mobile-safe margins
- brand logo area
- final CTA

Renderer progress 0-1 should map to overall job progress 70-95.

## Worker requirements

The worker must be resumable. Before running a stage, check for a validated artifact from that stage. On restart, continue from the latest valid stage rather than starting over.

Retries are allowed only for transient provider/renderer errors and must be bounded. Validation failures are not retryable.

## Security constraints

- no secrets in Git
- no user-controlled arbitrary filesystem paths
- all asset/project folders are constrained to the configured roots
- artifact serving is allowlisted by the job record
- public errors do not expose stack traces or host secrets

## Sprint 1 exclusions

Do not implement:
- Vision AI / scene intelligence
- ComfyUI
- stock media providers
- dashboard
- automatic TikTok/Facebook/YouTube publishing
- analytics

## Acceptance target

A committed 45-second Vinhomes Green Paradise request must produce a playable 1080x1920 H.264 MP4 and reach `awaiting_review` without manual video editing. The final PR must include test results and ffprobe metadata evidence.
