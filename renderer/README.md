# Remotion renderer

Sprint 1 renderer service for `real-estate-short-v1`.

## Contract

`POST /render`

```json
{
  "job_id": "vid_...",
  "manifest_path": "/workspace/storage/jobs/vid_.../video-manifest.json",
  "output_path": "/workspace/storage/jobs/vid_.../final.mp4"
}
```

`output_path` is optional and defaults to `final.mp4` beside the manifest.

Success:

```json
{
  "status": "success",
  "output_path": "/workspace/storage/jobs/vid_.../final.mp4",
  "duration": 45,
  "width": 1080,
  "height": 1920,
  "fps": 30,
  "codec": "h264"
}
```

Failures return `status`, `error_code`, a safe message, retryability, and structured details without a raw stack trace.

The service:

1. validates request paths stay below `STORAGE_ROOT`;
2. reads the validated video manifest;
3. exposes local media to Remotion through the internal `/media` route;
4. bundles the Remotion entrypoint once per process;
5. selects `real-estate-short-v1` with manifest input props;
6. renders H.264 + AAC to the requested output path.

The template supports timeline scenes, local video/image media, narration/music, mobile-safe subtitles, Vietnamese Noto Sans glyph coverage, brand logo, headline/body/emphasis overlays, and a final CTA card. Renderer progress events map 0-100% render completion into overall job progress 70-95.

## Development checks

```bash
npm ci
npm test
npm run typecheck
npm run bundle:check
```

Remotion packages are intentionally pinned to the same exact version.
