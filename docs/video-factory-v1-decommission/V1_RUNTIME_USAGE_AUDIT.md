# Video Factory V1 production runtime usage audit

## Result

The V1 job queue is drained at the dated snapshot, but V1 is **not unused** and cannot be stopped:

- all four V1 containers are running;
- Agent Hub is still configured for the V1 API and shared Redis;
- the renderer handled a direct render on `2026-08-29` local time, now attributed by AH-01B to a
  one-off Codex V3 owner-review workflow;
- the storage root mixes V1 data with recently generated owner-review material;
- V1 API/renderer ports are directly reachable from the public network;
- exact rollback images and a V1 restore-tested backup set are now technically proven for the dated
  AH-01B snapshot, but custody/retention acceptance and a second protected copy remain pending.

Production inspection and backup capture performed reads only. They did not submit a V1 job, invoke
a provider, change a key, alter a workflow, restart a production container, edit Caddy, or touch
V2/V3 runtime. The restore ran only in an isolated local environment.

## Snapshot identity

| Field | Value |
|---|---|
| Host | `157.10.201.169` |
| Host time at start | `2026-08-29T09:49:35+07:00` |
| Host time at final inventory query | `2026-08-29T10:04:30+07:00` |
| V1 Compose project | `npd-ai-video-factory`, running 4 services |
| Agent Hub Compose project | `npd-agent-hub-prod`, running 1 healthy service |
| V1 checkout | `/opt/npd-ai-video-factory`, `ca535a6a4cea67beeb0cae97b8fb5ea3c6c1743c` |
| Audited main | `02c31be4729bf19f150791ee623dfb25d957ada7` |

The production checkout had untracked `.runtime`, `production-pilot-artifacts`, and four
`storage/owner-review-v3-*` directories. These were inventoried by path/size/mtime only; no secret
backup contents were read.

## Container state

| Service | Runtime state | Started (UTC) | Restarts | Exposure/dependency |
|---|---|---:|---:|---|
| V1 API | running | `2026-08-14T08:09:20Z` | 0 | `0.0.0.0/[::]:8000`; Redis DB0; storage bind |
| V1 worker | running | `2026-08-14T08:19:48Z` | 0 | Redis DB0; renderer; storage bind; no healthcheck |
| V1 renderer | running | `2026-08-14T08:19:47Z` | 0 | `0.0.0.0/[::]:3001`; storage bind; no auth |
| Redis | running, healthy | `2026-08-14T06:46:07Z` | 0 | Docker volume; DB0 V1 and DB1 Agent Hub |
| Agent Hub | running, healthy | `2026-08-26T09:59:19Z` | 0 | loopback port 8010; joins V1 and n8n networks |

External read-only health requests succeeded:

| URL | Response |
|---|---|
| `http://157.10.201.169:8000/healthz` | `{"status":"ok"}` |
| `http://157.10.201.169:8000/readyz` | `{"status":"ready"}` |
| `http://157.10.201.169:3001/healthz` | Remotion `real-estate-short-v1` reported OK |

Only health routes were called. The unauthenticated POST routes were not exercised.

## V1 Redis DB0

The snapshot used `SCAN`, `GET`, `LLEN`, `LRANGE`, `TTL`, and aggregate parsing only.

| Metric | Value |
|---|---:|
| DB size | 12 keys |
| `npd:video-job:*` records | 12 |
| Parse errors | 0 |
| `npd:video-jobs:queue` length | 0 |
| `npd:video-jobs:processing` length | 0 |
| `npd:video-idempotency:*` keys | 0 |
| Oldest job created | `2026-08-14T06:46:35.454626Z` |
| Newest job created | `2026-08-14T08:19:59.261507Z` |
| Newest job update | `2026-08-14T08:22:44.641836Z` |

Terminal state counts:

| State | Count | Policy |
|---|---:|---|
| `awaiting_review` | 7 | Retain metadata/artifacts; obtain retention/acceptance disposition |
| `failed` | 5 | Archive terminal state and error code; never silently retry during shutdown |
| `queued` | 0 | Recheck at each stage gate |
| `running` | 0 | Recheck and allow safe completion if later present |
| Processing list | 0 | Recheck; reconcile with job state before a rollback restart |

All five failed jobs have `TTS_PROVIDER_FAILED`. No job key was modified.

## Runtime log evidence

Docker log aggregation retained only category counts, timestamps, status codes and safe job IDs.

### API

For the currently running API container:

- four `POST /api/v1/video-jobs` responses, all HTTP 202;
- first logged POST: `2026-08-14T08:09:22.793836896Z`;
- last logged POST: `2026-08-14T08:19:59.269831940Z`;
- four logged status/artifact GETs, all HTTP 200;
- last grouped GET: `2026-08-14T08:09:37.953821298Z`.

The log window begins with the current container, so it is not a complete history of the 12 Redis
jobs. Redis timestamps remain the durable job evidence.

### Worker

For the currently running worker container:

- one job was claimed at `2026-08-14T08:19:59.270069711Z`;
- it reached `awaiting_review` at `2026-08-14T08:22:44.642329970Z`;
- no later worker job event was observed;
- queue and processing are empty.

### Renderer

The current renderer log contains progress for two job IDs:

| Job ID | First event (UTC) | Last event (UTC) | DB0 relationship |
|---|---|---|---|
| `vid_1786695599261_60dbfd66ed` | `2026-08-14T08:20:12.501903624Z` | `2026-08-14T08:22:44.167564089Z` | Present, `awaiting_review` |
| `vid_1787989200000_a1b2c3d4e5` | `2026-08-28T17:42:07.681444152Z` | `2026-08-28T17:44:48.378506689Z` | Absent |

The second render occurred from approximately `00:42` to `00:44` on `2026-08-29` in
Asia/Saigon. AH-01B correlated the exact job ID, manifest/output paths, command result, renderer
completion time, and artifact SHA-256 values with Codex thread
`01a04949-b7d1-7520-a46a-8e5fa5a8cb4e`. The request was a host-local
`http://127.0.0.1:3001/render` call for the V3 owner-review package, not an Agent Hub or n8n
execution. See [AH01B_EVIDENCE.md](AH01B_EVIDENCE.md).

This attribution resolves the observed request, not the broader absence-of-callers question. The
renderer still does not log caller identity or request receipt, so identity-safe telemetry and a
fresh observation window remain required before any disable or stop.

### Agent Hub

Production Redis DB1 and logs show:

- 178 indexed Agent Hub tasks;
- one report contained a `video_producer` marker;
- zero `video.jobs.create` execution records;
- zero external video job IDs recorded by Agent Hub;
- zero logged execute-action requests matching the video path;
- zero logged `video API request failed` messages.

This proves no recorded Agent Hub execution, not that the configured adapter is harmless or
unreachable.

## Network and route usage

The V1 Docker network currently contains only:

- V1 API;
- V1 worker;
- V1 renderer;
- V1-owned Redis;
- production Agent Hub.

The production n8n container is not on this network. Its inactive smoke workflow points to
`http://api:8000/api/v1`, so it cannot currently resolve that service name from its deployed
network topology.

The V1 API OpenAPI document exposes:

- `GET /healthz`;
- `GET /readyz`;
- `POST /api/v1/video-jobs`;
- `GET /api/v1/video-jobs/{job_id}`;
- `GET /api/v1/video-jobs/{job_id}/artifacts/{artifact_name}`.

The renderer exposes:

- `GET /healthz`;
- `POST /render`;
- static `GET /media/*` under the entire storage root.

Source inspection shows no authentication on these routes. The create route permits a missing
idempotency header. The renderer validates that filesystem paths remain under the storage root but
does not authenticate or rate-limit the caller.

## n8n, scheduler, webhook, and PostgreSQL audit

| Area | Result |
|---|---|
| n8n workflow | `019ffe50-ec05-7b13-b722-08bbb5e8482b`, manual trigger, `active=false`, `triggerCount=0` |
| n8n execution rows | 0 for the V1 workflow |
| n8n network access | No membership in `npd-ai-video-factory_default` |
| V1 inbound webhooks | None in V1 API/renderer source |
| n8n Wait webhook | Workflow-only resume node; inactive and no execution |
| Cron | No matching V1 entry |
| systemd units/timers | No matching V1 unit or timer |
| V1 PostgreSQL | No service; no table name containing `video` in n8n PostgreSQL |

Scheduler and workflow state can drift. These checks must be rerun immediately before Stage C;
the dated AH-01 result is not a permanent assertion.

## Storage and media

| Path | Files | Bytes | Newest mtime (UTC) |
|---|---:|---:|---|
| `/opt/npd-ai-video-factory/storage` | 194 | 212,365,362 | `2026-08-28T17:46:38.344239Z` |
| `storage/jobs` | 98 | 168,719,888 | `2026-08-14T08:23:19.957020Z` |
| `storage/assets` | 8 | 8,496,188 | `2026-08-14T06:39:42.651809Z` |
| Four `storage/owner-review-v3-*` dirs | 88 | 35,149,286 | `2026-08-28T17:46:38.344239Z` |
| `production-pilot-artifacts` | 45 | 38,408,292 | `2026-08-14T08:09:37.953899Z` |
| `.runtime` | 17 | 9,145,104 | `2026-08-14T08:09:38.074908Z` |

The V1 `storage/jobs` directories include `script.json`, `storyboard.json`, `narration.wav`,
`subtitles.srt`, `video-manifest.json`, `final.mp4`, `qc.json`, frames and contact sheets depending
on job outcome. Failed TTS jobs contain only early-stage artifacts.

No whole-root action is safe. The four owner-review directories are explicitly protected from
V1 decommission work until ownership is established.

## Persistence, backup, and rollback evidence

- Redis AOF is enabled and reports last write status OK.
- Redis uses the Docker volume `npd-ai-video-factory_redis-data`.
- AOF is local persistence, not an independent backup.
- `/var/backups/npd-agent-hub` contains Agent Hub backups; these do not constitute V1 DB0/media
  backups.
- `.runtime/env-before-v2-20260814T080332Z.backup` exists; its bytes were captured only inside the
  AES-256-GCM runtime payload and its protected contents were not decoded, displayed or logged.
- AH-01B later produced an independent 16-payload, 1,895,938,306-byte encrypted bundle outside
  production/Git. It includes V1 DB0, selected V1 storage, pilot/runtime evidence, exact
  API/worker/renderer images, the pinned Redis image and source/audit evidence.
- A real isolated restore/restart verified 12/12 DB0 keys, file counts/checksums, exact image
  mappings, API/renderer reads, no provider/publish path and cleanup. Production postcheck remained
  unchanged with restart count zero.
- Agent Hub DB1 was deliberately excluded and remains a separate backup/rehome gate.

`v1-backup-restore-coverage` is therefore `KEEP`; owner custody/retention acceptance, a second
protected copy and a fresh pre-change snapshot remain required.

## Runtime provenance

The local V1 images were created on 14/08 and have no registry digest or git revision label:

| Image | Image ID prefix | Created (+07) |
|---|---|---|
| API | `5c7597d6da75` | `2026-08-14T15:09:09` |
| Worker | `8d367182ab9c` | `2026-08-14T15:19:36` |
| Renderer | `e42b8c5bf9a` | `2026-08-14T15:19:12` |

AH-01B compared every tracked source input copied into the running images and found zero
mismatches:

- API: 10/10 files match `78273a6d082dc90f8eae0ea57c2b30165e4328cc`;
- worker: 25/25 files match `a92785dc1721ec4e991bf12655629d809e13c241`;
- renderer: 8/8 files match `a92785dc1721ec4e991bf12655629d809e13c241`.

The host checkout has advanced independently and is not the image build source of truth. Exact
image IDs and created timestamps are recorded in [AH01B_EVIDENCE.md](AH01B_EVIDENCE.md).

The exact images are now exported, checksummed and restore-tested in the encrypted bundle. Before
any future stop/rebuild, verify the protected copy and compare a fresh production snapshot.
Rebuilding from the current checkout is not a valid rollback plan.

## Secret presence and least privilege

Presence-only inspection found `OPENAI_API_KEY` configured in the V1 API, worker, and renderer
containers because root Compose passes the same `.env` to each service. Only the worker requires
TTS provider access. No secret value was displayed, copied, or persisted by AH-01.

Future least-privilege work must be owner-gated and must not transfer V2/V3 secrets into Agent Hub.

## Conclusions and required refresh

At the snapshot:

- active/running V1 jobs: none;
- queued/processing V1 jobs: none;
- scheduled V1 jobs: none found;
- stored V1 media: present;
- Agent Hub caller: configured but no recorded execution;
- n8n caller: inactive and currently network-disconnected;
- observed direct renderer request: attributed to Codex V3 owner-review; independent caller
  telemetry and observation still pending;
- published/external references: unknown;
- independent V1 restore capability: technical PASS for the dated snapshot; owner custody and
  second-copy gates pending.

Before any AH-03/AH-04 production action, rerun every volatile check in this document and record a
new timestamped snapshot. The AH-01 snapshot alone never authorizes a shutdown.
