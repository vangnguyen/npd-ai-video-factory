# Sprint 1 Acceptance Tests

## Contract tests

- The sample request is accepted and unknown properties are rejected.
- A generated manifest validates against `video-manifest.schema.json`.
- Scene order is monotonic and total duration is within 100 ms of metadata duration.
- Only `video` and `image` local visual types are accepted in Sprint 1.

## API tests

- Create returns HTTP 202 and a unique `vid_` job ID.
- Repeating the same `Idempotency-Key` returns the original job.
- Status transitions never move backward.
- Missing jobs and path-traversal artifact requests fail safely.
- Failure responses contain a stable code and do not expose secrets or host paths.

## Worker tests

- Deterministic providers produce repeatable artifacts.
- Restarting after each stage resumes from the last validated artifact.
- Transient renderer/provider errors are retried with a bounded policy.
- Non-retryable manifest errors terminate in `failed`.

## Renderer tests

- Composition is 1080x1920 at 30 fps.
- Output uses H.264 video and a broadly compatible audio codec.
- Output duration is 45 seconds within 250 ms.
- Subtitles remain inside mobile-safe margins.
- Logo and CTA appear during the expected timeline ranges.

## End-to-end test

1. Place at least five licensed local fixture clips under the configured project asset folder.
2. Start the Compose stack.
3. Import the inactive n8n smoke workflow and configure its API base URL.
4. Submit the committed Vinhomes Green Paradise request.
5. Observe bounded polling until `awaiting_review` or `failed`.
6. Verify the final MP4 exists, is playable, and passes metadata assertions.
7. Record the job ID, manifest validation result, video metadata, and test command output in the implementation PR.
