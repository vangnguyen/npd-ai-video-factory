# Sprint 1 Acceptance Evidence

Re-verified on 2026-08-19 after review found that the original 1x1 fixture was an opaque black pixel and narration ended around 21 seconds while scene-based subtitles continued to 45 seconds.

## End-to-end result

- Local review job ID: `vid_1787135157091_37c35efc39`
- Terminal status: `awaiting_review`
- Terminal stage/progress: `awaiting_review` / `100`
- Output: `storage/jobs/vid_1787135157091_37c35efc39/final.mp4`
- Registered artifacts: request, script, storyboard, narration, subtitles, resolved assets, manifest, final video, and QC report
- Manifest: validated against `packages/contracts/video-manifest.schema.json`

The test now uses five generated copyright-safe, visibly distinct 360x640 PNG fixtures. The worker measures central-frame luminance once per second and rejects a render when more than 10% of samples are effectively black. Production-quality source media remains an operator input.

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
| File size | 3,026,921 bytes |
| Visual content QC | 45 samples, 0.0 black ratio, luma 110.898-127.792 |
| Audio content QC | mean -23.5 dB, peak -3.0 dB |

The generated contact sheet confirms visible scene media, logo, headline, subtitle safe area, CTA, and Vietnamese diacritics. Narration is synthesized per scene into a 45-second PCM master; subtitle cues use measured speech activity and remain inside their scene ranges.

## Automated checks

- Python API + worker: 29 tests passed (12 API, 17 worker).
- Renderer: 8 tests passed across contract parsing, composition output, subtitle timing/safe area, missing assets, invalid manifests, structured failures, progress mapping, and completion response.
- TypeScript: `tsc --noEmit` passed.
- Remotion: bundle check passed.
- n8n: workflow JSON parsed successfully, remained inactive, and imported successfully with the n8n CLI; it contains bounded polling plus request-error, job-failure, and timeout output.
- Docker Compose: API, Redis, worker, and renderer started; the sample request reached `awaiting_review`; FFprobe plus visual/audio content QC passed.

The offline eSpeak voice remains a deterministic smoke-test provider, not a commercial voice. Automated checks prove clean decode, non-silent activity in every cue, exact source-master duration, and correct subtitle alignment. Human listening remains a merge gate for perceived pronunciation and fluency.

## Scope confirmation

No Vision AI, ComfyUI, stock provider, AI image/video generation, YouTube publishing, analytics, dashboard, or multi-channel work was added.
