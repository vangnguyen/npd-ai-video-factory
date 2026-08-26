# API Contract

Base path: `/api/v1`

## Create job

`POST /video-jobs`

Headers:

- `Content-Type: application/json`
- `Idempotency-Key: <client-generated-key>` is recommended.

Request body is demonstrated in `examples/vinhomes-green-paradise.request.json`.

Successful response: `202 Accepted`

```json
{
  "job_id": "vid_01JXYZ",
  "status": "queued",
  "stage": "queued",
  "progress": 0,
  "status_url": "/api/v1/video-jobs/vid_01JXYZ"
}
```

## Get job

`GET /video-jobs/{job_id}`

```json
{
  "job_id": "vid_01JXYZ",
  "status": "running",
  "stage": "rendering",
  "progress": 84,
  "created_at": "2026-08-14T00:00:00Z",
  "updated_at": "2026-08-14T00:01:05Z",
  "artifacts": [],
  "error": null
}
```

When ready for review:

```json
{
  "job_id": "vid_01JXYZ",
  "status": "awaiting_review",
  "stage": "awaiting_review",
  "progress": 100,
  "artifacts": [
    {
      "kind": "video",
      "name": "final.mp4",
      "url": "/api/v1/video-jobs/vid_01JXYZ/artifacts/final.mp4"
    }
  ],
  "error": null
}
```

## Get artifact

`GET /video-jobs/{job_id}/artifacts/{artifact_name}`

An artifact is served only when all of these are true:

1. the job exists;
2. the artifact name is registered in that job's Redis record;
3. the resolved file is a direct child of the configured job directory;
4. the file exists.

Path traversal and arbitrary host filesystem access are rejected as `404 ARTIFACT_NOT_FOUND` without exposing host paths.

## Health

- `GET /healthz`: process liveness.
- `GET /readyz`: Redis and required local storage readiness.

## Error model

```json
{
  "error": {
    "code": "MANIFEST_VALIDATION_FAILED",
    "message": "Video manifest validation failed.",
    "failed_stage": "building_manifest",
    "retryable": false,
    "details": []
  }
}
```

Stable Sprint 1 codes:

- `REQUEST_INVALID`
- `CONTENT_PROVIDER_FAILED`
- `TTS_PROVIDER_FAILED`
- `ASSET_RESOLUTION_FAILED`
- `MANIFEST_VALIDATION_FAILED`
- `RENDERER_UNAVAILABLE`
- `RENDER_FAILED`
- `QC_FAILED`
- `ARTIFACT_NOT_FOUND`
- `INTERNAL_ERROR`

Validation errors use HTTP 422; missing jobs/artifacts use 404; dependency unavailability uses 503; unexpected failures use 500. Job-stage failures remain queryable through the job status resource.

Registered artifact kinds are `request`, `script`, `storyboard`, `audio`, `subtitle`, `assets`, `manifest`, `video`, and `qc`. The older `metadata` value remains accepted for backward compatibility.
