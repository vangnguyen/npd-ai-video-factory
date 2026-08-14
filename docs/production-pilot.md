# Production Pilot Runbook

This runbook turns the proven Sprint 1 stack into a controlled real-media pilot. It does **not** auto-publish to TikTok, Facebook, or YouTube.

## 1. Required server assets

Place licensed/owned project media under:

```text
storage/assets/<project-folder>/
```

For the current pilot:

```text
storage/assets/vinhomes-green-paradise/
```

Supported project media: MP4, MOV, WEBM, JPG, JPEG, PNG.

Place the production NPD logo at:

```text
storage/assets/brand/npd-logo.png
```

Do not use CI fixture images for the production pilot.

## 2. Production environment

Start from `.env.example` and override these values on the VPS:

```dotenv
APP_ENV=production
TTS_PROVIDER=openai
OPENAI_API_KEY=<server-secret>
OPENAI_TTS_MODEL=gpt-4o-mini-tts
OPENAI_TTS_VOICE=marin
OPENAI_TTS_INSTRUCTIONS=Đọc tiếng Việt tự nhiên, rõ ràng, đáng tin cậy, nhịp vừa phải; phong cách tư vấn bất động sản chuyên nghiệp, không cường điệu.
PILOT_STRICT_ASSETS=1
NPD_LOGO_PATH=/workspace/storage/assets/brand/npd-logo.png
```

Never commit the real API key. Keep it in the VPS environment/secret store.

`PILOT_STRICT_ASSETS=1` disables the Sprint 1 logo placeholder. A production job fails early when the real logo is absent or invalid.

## 3. Asset preflight

After `.env` and assets are present, validate them before creating a job:

```bash
docker compose build worker
docker compose run --rm worker \
  python -m npd_worker.preflight \
  --project-folder vinhomes-green-paradise \
  --minimum-clips 5
```

A successful result prints JSON containing the project folder, asset count, logo path, and asset root. Missing logo, too few media files, invalid project paths, unsupported logo formats, and empty media files fail the command.

## 4. VPS deployment checklist

Use this order for the first controlled deployment:

1. Check out the approved production-pilot commit/branch on the VPS.
2. Confirm Docker Engine and Docker Compose are available.
3. Create the persistent `storage/assets`, `storage/jobs`, and Redis volume paths with enough free disk space for source media and rendered MP4 files.
4. Copy only licensed/owned project footage to `storage/assets/vinhomes-green-paradise/`.
5. Copy the approved production logo to `storage/assets/brand/npd-logo.png`.
6. Create the VPS `.env` from `.env.example`; set `APP_ENV=production`, `TTS_PROVIDER=openai`, `PILOT_STRICT_ASSETS=1`, and inject `OPENAI_API_KEY` through the server secret/environment. Do not put the key in Git or the n8n workflow JSON.
7. Run the asset preflight from section 3 and stop deployment if it fails.
8. Build and start the stack:

```bash
docker compose up -d --build
```

9. Verify service health:

```bash
curl --fail http://localhost:8000/readyz
curl --fail http://localhost:3001/healthz
```

10. Inspect container status/logs before accepting jobs:

```bash
docker compose ps
docker compose logs --tail=100 api worker renderer
```

11. Keep API/renderer ports private to the Docker/VPS network unless a reverse proxy, authentication, and firewall policy are intentionally configured.
12. Run one manual pilot job before enabling the n8n workflow.
13. Keep publishing manual until the reviewed pilot video and QC evidence are accepted.

Rollback for this pilot is operationally simple: deactivate the n8n workflow, stop the stack if necessary, and check out the last known-good commit. Job artifacts stay in persistent storage for diagnosis.

## 5. Start the stack and create the real-media pilot job

Use the committed request as a starting point and update only approved product facts and the project asset folder.

```bash
curl --fail --show-error \
  -X POST http://localhost:8000/api/v1/video-jobs \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: production-pilot-v1' \
  --data-binary @examples/vinhomes-green-paradise.request.json
```

Poll the returned job ID until `awaiting_review` or `failed`.

## 6. Review gate

Before publishing, review:

- `final.mp4`
- `qc.json`
- `video-manifest.json`
- narration pronunciation and pacing
- project facts and prices/policies
- subtitle safe-zone placement
- NPD logo rendering
- final CTA

Publishing stays manual in the Production Pilot.

## 7. n8n import and activation checklist

The committed workflow is:

```text
workflows/n8n/sprint-1-smoke-test.json
```

It is deliberately committed with `active: false` and a Manual Trigger. Import it into the self-hosted n8n instance only after the manual VPS pilot reaches `awaiting_review`.

Activation sequence:

1. In n8n, import `workflows/n8n/sprint-1-smoke-test.json` as a new workflow; keep it inactive during configuration.
2. Open **Configure Smoke Test** and verify `apiBaseUrl`. If n8n runs in the same Docker network, `http://api:8000/api/v1` is appropriate; otherwise point it to the authenticated/private API endpoint reachable by n8n.
3. Verify the request payload uses the approved `project_asset_folder`, minimum clip count, duration, CTA, audience, and only approved project facts.
4. Do not place `OPENAI_API_KEY` in n8n. The worker reads it from the VPS environment.
5. Execute the workflow once manually. Confirm it creates exactly one job and polls every 10 seconds.
6. Confirm polling terminates at `awaiting_review` or `failed`; the committed workflow also has a bounded polling limit rather than an infinite loop.
7. On `awaiting_review`, open/download the registered `final.mp4` and run the human review gate in section 6. n8n must not publish the file automatically during the pilot.
8. On `failed`, inspect the job error code/stage and worker logs; do not auto-retry permanent asset/manifest/content errors.
9. After at least one successful n8n-triggered pilot is reviewed, the workflow may be activated for internal job creation only. Keep social publishing disconnected until a later explicit release.
10. Before any future webhook/scheduled trigger is enabled, add authentication, rate limits/idempotency policy, and an explicit human approval step.

Recommended first production operation remains **Manual Trigger -> Create Video Job -> Poll -> Human Review**. Scheduled content generation and social publishing are outside the Production Pilot scope.

## 8. Optional OpenAI TTS smoke test

The repository includes `scripts/production-tts-smoke.py`. It never makes an external request unless both conditions are true:

1. `RUN_EXTERNAL_TTS_SMOKE=1`
2. `OPENAI_API_KEY` is present

Example on the VPS:

```bash
RUN_EXTERNAL_TTS_SMOKE=1 \
TTS_PROVIDER=openai \
python scripts/production-tts-smoke.py
```

GitHub Actions exposes the same check only through a manual `workflow_dispatch` input. Normal pushes and pull requests continue to use mocked/offline tests and the espeak CI fallback.

## 9. Pilot completion evidence

A pilot is complete only when the real-media job reaches `awaiting_review` and QC confirms:

- 1080x1920
- H.264 video
- audio stream present
- duration within the configured tolerance
- final MP4 larger than the minimum QC threshold

Record the job ID, commit SHA, `qc.json`, and reviewed `final.mp4` in Issue #5. Then run the same request through the imported n8n workflow and record that execution result before considering the Production Pilot operationally ready.
