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

- [ ] Deterministic providers produce repeatable pipeline artifacts end-to-end.
- [ ] Restarting after each stage resumes from the last validated artifact.
- [ ] Transient renderer/provider errors are retried with a bounded policy.
- [ ] Non-retryable manifest errors terminate in `failed`.

## Renderer tests

- [ ] Composition is 1080x1920 at 30 fps.
- [ ] Output uses H.264 video and a broadly compatible audio codec.
- [ ] Output duration is 45 seconds within 250 ms.
- [ ] Subtitles remain inside mobile-safe margins.
- [ ] Logo and CTA appear during the expected timeline ranges.

## End-to-end test

1. [ ] Place at least five licensed local fixture clips under the configured project asset folder.
2. [ ] Start the Compose stack.
3. [ ] Import the inactive n8n smoke workflow and configure its API base URL.
4. [ ] Submit the committed Vinhomes Green Paradise request.
5. [ ] Observe bounded polling until `awaiting_review` or `failed`.
6. [ ] Verify the final MP4 exists, is playable, and passes metadata assertions.
7. [ ] Record the job ID, manifest validation result, video metadata, and test command output in the implementation PR.
