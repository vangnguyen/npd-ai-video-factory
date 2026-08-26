# Sprint 1 Acceptance Evidence

Verified on 2026-08-19 with the committed sample request and the Docker Compose runtime contract.

## End-to-end result

- Job ID: `vid_1787131593810_dec71475d7`
- Terminal status: `awaiting_review`
- Terminal stage/progress: `awaiting_review` / `100`
- Output: `storage/jobs/vid_1787131593810_dec71475d7/final.mp4`
- Registered artifacts: request, script, storyboard, narration, subtitles, resolved assets, manifest, final video, and QC report
- Manifest: validated against `packages/contracts/video-manifest.schema.json`

The test used five generated copyright-safe PNG fixtures. They prove local-image resolution and rendering without introducing third-party footage into the repository; production-quality source media remains an operator input.

## FFprobe result

| Property | Result |
| --- | --- |
| Container | MP4 (`mov,mp4,m4a,3gp,3g2,mj2`) |
| Video codec | H.264 |
| Resolution | 1080x1920 |
| Frame rate | 30/1 fps |
| Video duration | 45.000 seconds |
| Container/audio duration | 45.056 seconds |
| Audio | AAC LC, 48 kHz, stereo |
| File size | 2,441,982 bytes |

An extracted frame was visually inspected after rendering. Logo, headline, subtitle safe area, and Vietnamese diacritics rendered correctly with Noto Sans.

## Automated checks

- Python API + worker: 26 tests passed.
- Renderer: 8 tests passed across contract parsing, composition output, subtitle timing/safe area, missing assets, invalid manifests, structured failures, progress mapping, and completion response.
- TypeScript: `tsc --noEmit` passed.
- Remotion: bundle check passed.
- n8n: workflow JSON parsed successfully, remained inactive, and imported successfully with the n8n CLI; it contains bounded polling plus request-error, job-failure, and timeout output.
- Docker Compose: API, Redis, worker, and renderer started; the sample request reached `awaiting_review`; worker FFprobe QC passed.

## Scope confirmation

No Vision AI, ComfyUI, stock provider, AI image/video generation, YouTube publishing, analytics, dashboard, or multi-channel work was added.
