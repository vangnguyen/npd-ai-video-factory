# Technical Handoff: Sprint 1 Vertical Slice

## Objective

Build one production-shaped vertical slice that accepts a Vietnamese real-estate video request and produces a reviewable 1080x1920 MP4 without manual editing.

## In scope

- n8n orchestration only; n8n must not render video.
- FastAPI create/status/artifact endpoints.
- Redis-backed job state and queue.
- Pluggable text-generation and Vietnamese TTS adapters.
- Deterministic local-footage resolver using files supplied by the operator.
- A versioned video manifest validated before rendering.
- Remotion renderer with one template: `real-estate-short-v1`.
- Job artifacts and structured failure details.
- A 45-second Vinhomes Green Paradise smoke test.

## Explicitly out of scope

- Vision or automatic scene intelligence.
- ComfyUI, text-to-video, or image-to-video generation.
- Stock-footage provider integrations.
- Dashboard/review application.
- Automatic publishing to TikTok, Facebook, or YouTube.
- Analytics feedback loops.

## Runtime architecture

```text
n8n
  -> POST /api/v1/video-jobs
FastAPI
  -> validate request
  -> persist job snapshot
  -> enqueue job in Redis
Worker
  -> generate script and storyboard
  -> synthesize narration
  -> resolve local assets deterministically
  -> build and validate video manifest
  -> call Remotion renderer
Renderer
  -> render real-estate-short-v1
  -> write final.mp4
Worker
  -> record artifact and complete status
n8n
  -> poll GET /api/v1/video-jobs/{job_id}
```

## Required pipeline stages

| Stage | Progress range | Required output |
|---|---:|---|
| `queued` | 0 | Immutable input snapshot |
| `scripting` | 5-20 | Script JSON |
| `storyboarding` | 20-35 | Timed scene plan |
| `generating_voice` | 35-50 | Narration audio and measured duration |
| `resolving_assets` | 50-65 | Local file selections with time ranges |
| `generating_subtitles` | 65-72 | Timed subtitle cues |
| `building_manifest` | 72-78 | Schema-valid manifest |
| `rendering` | 78-95 | MP4 artifact |
| `quality_check` | 95-99 | Mechanical QC report |
| `awaiting_review` | 100 | Artifact URL ready for human review |

Terminal error state: `failed`. Sprint 1 stops at `awaiting_review`; approval and publishing are later phases.

## Artifact layout

```text
storage/jobs/{job_id}/
  request.json
  script.json
  storyboard.json
  narration.mp3
  subtitles.json
  manifest.json
  qc-report.json
  final.mp4
  job.json
```

Each stage writes atomically: write a temporary file, validate it, then rename it to the canonical artifact name.

## Reliability rules

1. Job creation is idempotent when `Idempotency-Key` is supplied.
2. A worker may resume from the last validated artifact after restart.
3. Every failed job records `failed_stage`, a stable error code, a safe message, and retryability.
4. Paths in API responses are URLs or job-relative artifact names, never host filesystem paths.
5. Secrets exist only in `.env`; examples and logs must never contain tokens.
6. Local media inputs must be allowlisted beneath `ASSET_STORAGE_ROOT`.
7. Manifest duration must equal the sum of scene durations within a 100 ms tolerance.
8. Renderer inputs are immutable for a render attempt.

## Template timeline

- 0-3 seconds: hook.
- 3-8 seconds: project identity.
- 8-20 seconds: key information.
- 20-32 seconds: visual evidence/product.
- 32-40 seconds: sales or investment angle.
- 40-45 seconds: CTA and brand lockup.

Required components: hook text, project title, feature cards, subtitles, NPD logo, CTA, progress bar, and scene transition.

## Decisions for Codex

- Python 3.12 and FastAPI for the API/worker.
- Redis as the only Sprint 1 external state dependency.
- TypeScript and Remotion for rendering.
- JSON Schema is the cross-language contract source of truth.
- Provider interfaces must support deterministic fakes for tests.
- No database, vector store, or cloud object storage in Sprint 1.
