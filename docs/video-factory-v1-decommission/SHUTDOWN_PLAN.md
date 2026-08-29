# Video Factory V1 staged shutdown plan

## Current stage

`AH-01 / audit only` — **NO-GO for Stage A**.

No deprecation, drain, disable, observation, removal, traffic switch, restart, deployment, Caddy
change, provider call, data mutation, or PR merge was performed. The inventory contains eight
`UNKNOWN` decisions, which is a hard stop.

## Global gates

Every transition requires a fresh dated evidence package. Evidence from an earlier stage or the
AH-01 snapshot cannot be reused as proof of current queue/caller absence.

All of the following are mandatory before Stage A:

- zero components classified `UNKNOWN`;
- owner accepts the component inventory, data ownership and retention policy;
- the 29/08 local-time renderer caller is identified and assigned a replacement/retirement plan;
- every mixed-storage top-level directory has an owner and explicit retention action;
- external CMS/social/internal artifact references are inventoried or explicitly accepted as a
  residual risk by the owner;
- exact running API/worker/renderer images are exported, checksummed and restore-tested;
- V1 Redis DB0, storage, protected configuration and operational evidence have an independent,
  checksummed backup with a successful restore drill;
- Agent Hub DB1 has a separate tested backup and an approved rehome/split plan;
- Agent Hub has a reviewed replacement/deprecation behavior for `video.jobs.create`;
- any V2 replacement used by Agent Hub is a documented, accepted bridge contract—not a non-bridge
  endpoint—and has mock contract/HMAC/replay/idempotency tests;
- owner decides the disposition of draft PRs #34 and #35 without changing V2/V3 gates;
- rollback owner, change window, observation owner and explicit abort thresholds are named.

CI green, provider HTTP success, queue emptiness, container health, mergeability, or a dated lack of
calls is not owner authorization.

## Stage A — Deprecation

Goal: prevent new V1 work while preserving read access and producing attributable evidence.

Owner-gated implementation requirements:

1. Add an Agent Hub `VideoFactoryClient` against the accepted signed bridge contract.
2. Require explicit policy/approval for business actions that create or advance media work.
3. Replace or block `video.jobs.create` so it cannot enqueue a new V1 job.
4. Change V1 POST behavior through a compatibility/deprecation layer:
   - proxy only when an equivalent accepted bridge action exists;
   - otherwise fail closed with a stable deprecation response;
   - never silently submit to both V1 and V2;
   - never start V2 pipeline/render/publish through an undocumented endpoint.
5. Keep legacy status/artifact reads available under a documented retention policy.
6. Log every attempted V1 create/render/media access with timestamp, authenticated caller identity,
   request correlation ID and outcome, without request bodies or secrets.
7. Add counters/alerts for legacy calls, unknown callers, queue growth, worker activity and direct
   renderer use.
8. Restrict public exposure only through a separately approved network change that preserves known
   consumers and rollback. Do not use Caddy as an unreviewed workaround.

Stage A exit criteria:

- no new `npd:video-job:*` record created after the cutover timestamp;
- no V1 queue growth;
- every denied/proxied call has an attributable audit record;
- Agent Hub regression and bridge contract tests pass;
- no V2 provider or external publish action was invoked by acceptance tests;
- rollback from the deprecation behavior has been exercised in a non-production environment;
- owner accepts the Stage A evidence.

## Stage B — Drain and classify

Goal: leave no V1 work in an executable non-terminal state and preserve all required evidence.

At the start of the maintenance window, capture atomically or as closely as the systems permit:

- queue and processing list order;
- all V1 job IDs, status, stage, progress and update timestamps;
- worker/renderer in-flight processes and recent logs;
- storage directory/file count, size, mtime and SHA-256 manifest;
- Redis DB0 export/checksum;
- Agent Hub DB1 backup/checksum;
- exact image IDs/checksums and Compose/config hashes;
- active n8n workflow/schedule inventory;
- public/direct route counters since Stage A.

Job policy:

| Job state | Required action |
|---|---|
| `running` | Allow safe completion when appropriate; otherwise stop only through an explicit per-job owner decision and preserve state |
| `queued` | Migrate only through an accepted bridge contract or cancel explicitly with an audited owner decision; never drop the list |
| `processing` | Reconcile with job record and worker process before requeue/cancel; do not rely on automatic recovery alone |
| `awaiting_review` | Treat as retained terminal production output for V1 drain; record owner retention/acceptance disposition separately |
| `failed` | Preserve terminal state, error and available artifacts; do not automatically retry |
| abandoned/malformed | Mark only through a reviewed migration tool with prior export; preserve original evidence |

The AH-01 snapshot had zero queued/running/processing jobs, seven `awaiting_review`, and five
`failed`, but Stage B must remeasure.

The renderer bypass path is part of drain. Queue emptiness is insufficient while direct `/render`
calls continue.

Stage B exit criteria:

- queue=0 and processing=0 in two separated observations;
- no `queued` or `running` job record;
- no renderer process/request in flight;
- every terminal job has a retained metadata/artifact disposition;
- no active V1 n8n/cron/systemd scheduler;
- no unknown API/renderer consumer;
- backup and rollback evidence revalidated after the drain snapshot;
- owner accepts the drain ledger.

## Stage C — Disable execution, retain audit reads

Goal: stop V1 media execution without deleting code or data.

Order matters:

1. Confirm Stage A write blocking is still effective.
2. Disable any V1 scheduler if one exists at the fresh snapshot.
3. Disable/stop the V1 worker.
4. Disable the V1 create route or leave only the accepted compatibility adapter.
5. Disable the direct renderer route/service only after its caller has been migrated and zero-use
   evidence exists.
6. Disable public `/media`; retain any required archive through an authenticated read-only path.
7. Keep legacy job/status/artifact audit reads only for the accepted retention period.
8. Keep V1 DB0 and storage immutable/read-only where practical.
9. **Do not stop or remove the Redis container** while Agent Hub DB1 still uses it.
10. **Do not run project-wide Compose down or volume removal.**
11. Keep exact images, config, queue export, Redis export, storage archive and rollback instructions.

Stage C abort/rollback triggers include:

- any authorized consumer requires V1;
- Agent Hub task, approval, provider-health, CRM or n8n regression;
- missing legacy job/artifact read;
- unexpected queue/key write;
- new direct call to port 8000/3001;
- checksum or restore mismatch;
- any V2/V3 acceptance, provider, publication or security gate not satisfied.

## Stage D — Observe

Minimum: 7 complete days. Preferred and required by this plan: **14 complete days**.

The timer starts only after Stage C production acceptance. It resets on any unexplained legacy call
or dependency regression.

Monitor at least:

- V1 create/status/artifact/render/media call counts by authenticated caller;
- denied/proxied requests and correlation IDs;
- Redis DB0 queue, processing and job-key changes;
- renderer/worker process state;
- Agent Hub bridge request/error/replay/idempotency metrics;
- Agent Hub task, approval and audit health;
- n8n workflow/schedule state;
- archived artifact read failures;
- Caddy/shared route health;
- V2 bridge event delivery/receipt state without accessing V2 internals;
- cost anomalies and any provider/external-action signal.

Stage D exit criteria:

- 14 full days with zero unexplained V1 create/render/media use;
- zero queue/processing growth;
- no missing business flow or artifact dependency;
- Agent Hub remains healthy and independent;
- rollback set remains restorable and checksums still match;
- owner signs off the observation report.

## Stage E — Removal

Removal is a new, separate PR and production change request. It is never implied by Stage D.

Only after explicit owner approval may the project:

- remove V1 API/worker/renderer source;
- remove obsolete Docker services and ports;
- remove obsolete Agent Hub V1 config/network membership;
- remove obsolete n8n workflow definitions;
- remove V1 provider configuration and secrets from retired services;
- archive or expire V1 Redis DB0 keys according to policy;
- archive or delete V1 storage according to owner-specific manifests;
- update backup jobs and retention;
- change branch-protection checks and remove V1 CI;
- update the repository identity and final architecture docs.

Data deletion, source deletion and rollback-image expiry should be separate owner decisions even
within Stage E. Mixed owner-review/V2/V3 material is never a V1 deletion target.

## Gate matrix

| Action | Earliest stage | Required approval |
|---|---|---|
| Merge AH-01 docs/tooling | AH-01 | Existing repository governance/owner gate |
| Implement mock bridge client/tests | AH-02 | Reviewed PR; no production traffic |
| Deploy Agent Hub bridge configuration | AH-02/AH-03 | Explicit owner deploy approval |
| Block new V1 jobs | Stage A | Explicit owner approval |
| Restrict public V1 ports | Stage A or urgent containment | Separate owner network-change approval |
| Migrate/cancel queued jobs | Stage B | Explicit per-policy owner approval |
| Stop V1 worker | Stage C | Explicit owner approval |
| Stop direct renderer | Stage C | Caller resolved + zero-use evidence + owner approval |
| Stop/rehome shared Redis | Separate Agent Hub data migration | Explicit owner data/deploy approval |
| Remove Caddy route | Not applicable now; no V1 route exists | Separate approval if state changes |
| Delete V1 keys/media/code | Stage E | Separate explicit deletion approval |
| Switch production traffic to V2/V3 | AH-03/Stage A | Explicit owner approval plus V2/V3 acceptance |

## Evidence package for each stage

Every stage PR/change record must contain:

- exact source and production revisions;
- current component inventory with zero unexplained `UNKNOWN`;
- before/after service, route, queue, key and storage snapshots;
- no-secret config presence report;
- backup paths, checksums and restore-test result;
- test/CI results separated into mock, real-provider, production-path and human quality evidence;
- rollback command owner and abort thresholds;
- confirmation that no V2/V3 repository, provider, database, secret or acceptance gate was changed;
- explicit owner approval reference;
- final statement of what was not merged/deployed/published/deleted.
