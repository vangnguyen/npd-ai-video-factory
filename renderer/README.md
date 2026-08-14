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

The service:

1. validates request paths stay below `STORAGE_ROOT`;
2. reads the validated video manifest;
3. exposes local media to Remotion through the internal `/media` route;
4. bundles the Remotion entrypoint once per process;
5. selects `real-estate-short-v1` with manifest input props;
6. renders H.264 + AAC to the requested output path.

The template supports timeline scenes, local video/image media, narration/music, subtitles, brand logo, headline overlays, and a final CTA card.

## Development checks

```bash
npm install
npm run typecheck
npm run bundle:check
```

Remotion packages are intentionally pinned to the same exact version.
