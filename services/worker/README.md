# Pipeline worker

The Sprint 1 worker claims Redis jobs and runs the resumable vertical-slice pipeline:

`content -> storyboard -> Vietnamese TTS -> subtitles -> local assets -> manifest -> Remotion -> QC -> awaiting_review`

## Reliability

- claimed jobs move to `npd:video-jobs:processing`;
- inflight jobs are recovered to the queue when the single Sprint 1 worker restarts;
- validated artifacts under `storage/jobs/{job_id}` are reused after restart;
- progress never moves backward because state changes go through the shared API `RedisJobStore`;
- renderer network/502/503/504 failures receive one bounded retry;
- stage failures are persisted with stable error codes.

## Sprint 1 TTS

`TTS_PROVIDER=espeak` uses the offline `espeak-ng` Vietnamese voice inside the worker container. This removes external credentials from the smoke test while preserving the provider interface for later production adapters.

## QC

The worker runs FFprobe after render and requires:

- MP4 larger than 100 KB;
- H.264 video;
- 1080x1920 dimensions;
- 30 fps;
- audio stream;
- duration within 3 seconds of the requested duration.
