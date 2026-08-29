# Video Factory V1 rollback plan

## Current rollback readiness

**Not ready for a shutdown change.**

AH-01 found Redis AOF persistence and an older protected environment backup, but did not find a
complete, independent, restore-tested set covering V1 DB0, storage, exact images, configuration and
queue order. The running API/worker/renderer images are local `:latest` builds without git revision
labels or registry digests. AH-01B recorded exact image IDs and matched all 43 copied source inputs,
so source provenance is resolved. `v1-backup-restore-coverage` remains `UNKNOWN` because no exact
image export or real restore drill exists.

This document defines the required future procedure. It is not permission to execute it. Any
production restore, container recreation, route change, queue mutation or data replacement requires
an explicit owner-approved change window.

## Safety invariants

- Never use `docker compose down -v`, volume removal, `FLUSHALL`, or broad filesystem deletion.
- Never restore or clear all Redis databases. V1 DB0 and Agent Hub DB1 share one Redis service.
- Never rebuild from the current checkout and call it the V1 rollback image.
- Never overwrite live storage before restoring to a separate validated path and checking hashes.
- Never include secret values in the backup manifest, logs, chat, Git, or PR body.
- Never restore V2/V3 data, secrets, databases, images or provider state from this runbook.
- Never add/remove a Caddy V1 route during rollback; no V1 Caddy route exists at the AH-01 baseline.
- Stop and request owner direction on any mismatch in image ID, checksum, target path, queue order,
  job state, data ownership, or caller identity.

## Required pre-change rollback bundle

Create this bundle before Stage A or Stage C and restore-test it outside production:

| Item | Required evidence |
|---|---|
| Exact API image | Exported image archive, SHA-256, image ID `5c7597d6da75...`, creation timestamp |
| Exact worker image | Exported image archive, SHA-256, image ID `8d367182ab9c...`, creation timestamp |
| Exact renderer image | Exported image archive, SHA-256, image ID `e42b8c5bf9a...`, creation timestamp |
| Redis image/config | Image ID, Redis config/persistence metadata, volume identity |
| Compose/config | Checksums of reviewed Compose and non-secret config; protected secret file backup recorded by path/checksum only |
| Redis DB0 | Namespace-scoped export of job records, queue, processing and idempotency keys; type/TTL/order manifest |
| Agent Hub DB1 | Separate Agent Hub backup and successful restore result |
| V1 storage | SHA-256 manifest, owner classification, permissions, bytes/counts for every included path |
| Mixed storage exclusions | Explicit manifest of `owner-review-v3-*` and every non-V1 path that must not be touched |
| Pilot/runtime evidence | Separate archive for `production-pilot-artifacts` and `.runtime`; secret-safe handling |
| n8n state | Export of matching workflow, active/version state and execution summary |
| Network/routes | Listener, Docker network, Caddy and firewall snapshot |
| Logs/metrics | Stage baseline, legacy-call counters and correlation IDs |

The bundle manifest must record UTC timestamps, source revision, production checkout revision,
container/image IDs, file checksums, Redis counts, owner, retention class and restore-test result.

## Rollback triggers

Rollback immediately or stop the change when any of the following occurs:

- an authorized business flow still needs V1 create/render/read access;
- Agent Hub API, task, approval, audit, provider-health, CRM, n8n or Redis behavior regresses;
- V1 queue or processing state changes unexpectedly;
- legacy job/status/artifact reads fail;
- renderer calls continue from an unresolved or unmigrated caller;
- V2 bridge signature, replay, idempotency, event or project mapping is inconsistent;
- checksums, image IDs, storage ownership or restore-test results do not match;
- any paid provider, external publish, V2/V3 acceptance or security gate is unexpectedly crossed.

## Stage A rollback — restore V1 create behavior

Use only when an owner-approved Stage A change must be reversed.

1. Freeze further deploy activity and record the exact failure/correlation IDs.
2. Confirm DB0 queue/processing and job state before changing request routing.
3. Restore the prior Agent Hub image/config that contains the reviewed V1 adapter, using the exact
   pinned rollback image and `--no-build` semantics.
4. Restore the prior API compatibility/deprecation image/config in the same way.
5. Recreate only the affected service; do not recreate Redis, worker, renderer, Caddy, n8n or
   unrelated services.
6. Verify service/image IDs and health.
7. Run read-only smoke checks only:
   - Agent Hub health/readiness;
   - V1 API health/readiness;
   - V1 status read for a retained job;
   - queue/processing counts unchanged;
   - Redis DB1 health and Agent Hub task count.
8. Do not create a video job as a rollback smoke unless the owner separately authorizes the cost
   and provider path.
9. Record the rollback result and keep the Stage A incident open until cause is understood.

If a compatibility adapter had begun proxying to V2, exact idempotency/request mappings must be
reconciled before V1 creation is restored. Never submit the same business request to both systems.

## Restore the V1 worker

The worker may be restored only after queue reconciliation:

1. Confirm the exact worker image archive checksum and load it if the local image is absent.
2. Confirm its runtime source-hash manifest matches the captured baseline.
3. Keep the worker stopped while comparing:
   - DB0 queue order;
   - processing order;
   - each referenced job's current status/stage/progress;
   - artifact existence/checksum;
   - whether V2 has already accepted the same business request.
4. Move no key manually until the reconciliation report is accepted.
5. Restore only the worker service with the exact image and no build/recreate of dependencies.
6. Watch the first claim before allowing normal consumption.
7. Stop immediately if an ID is terminal, duplicated in V2, missing its record, or has mismatched
   artifacts.

The V1 worker's startup logic moves every item from `npd:video-jobs:processing` back to
`npd:video-jobs:queue`. This is useful for a consistent crash recovery but unsafe when restored
processing state is stale. Reconcile first; do not rely on automatic recovery as the migration
tool.

## Restore V1 API/read routes

1. Restore the exact captured API image and reviewed prior Compose/config.
2. Recreate only the API service with `--no-build` behavior.
3. Confirm Redis DB0 and storage binds point to the expected validated targets.
4. Verify `/healthz`, `/readyz`, one retained status read and one authorized retained artifact read.
5. Confirm create-route behavior matches the rollback stage and is not accidentally public without
   the approved containment policy.
6. Do not alter Caddy: the baseline has no V1 Caddy route.

If public-port containment is rolled back, restore only the reviewed listener/firewall state and
record why the exposure is necessary. The observed renderer request was an attributed Codex V3
owner-review call, but network rollback still requires telemetry evidence and caller-owner
participation for any newly observed use.

## Restore the renderer

1. Identify the consumer requiring restoration and confirm it is not V2/V3 runtime being modified
   through the wrong repository.
2. Restore/load the exact captured renderer image; do not rebuild from current main or PR #34/#35.
3. Validate the storage root and V1 manifest schema bind without moving mixed owner-review data.
4. Recreate only the renderer service.
5. Verify renderer health.
6. Use a deterministic, no-provider fixture render in a non-production path only if separately
   approved; otherwise rely on health and captured contract tests.
7. Ensure `/media` exposure matches the owner-approved rollback state and does not become a public
   archive by accident.

## Restore a scheduler or n8n workflow

At the AH-01 baseline:

- no matching cron/systemd scheduler exists;
- the V1 n8n workflow is manual and inactive;
- it has zero retained execution rows;
- n8n is not on the V1 Docker network.

Therefore there is nothing to start as part of the baseline rollback. If a later stage disables a
newly discovered or intentionally added scheduler:

1. restore only from the captured versioned export;
2. compare workflow ID, version, node types, endpoint, credentials-by-reference and active state;
3. keep it inactive until its endpoint/network and idempotency behavior are proven;
4. activate only with separate owner approval;
5. never place media-engine logic in n8n.

## Recover Redis DB0 and queue state

V1 has no PostgreSQL job database. Its durable job/queue state is Redis DB0.

Required recovery design:

1. Restore the DB0 export into a separate staging Redis instance, never directly over production.
2. Verify key names, types, values, TTLs, job status counts, queue order and processing order against
   the manifest.
3. Confirm there are no Agent Hub (`npd:agent-hub:v1:*`) keys in the DB0 export.
4. Stop the V1 API/worker write paths for the approved maintenance window.
5. Export current production DB0 again for a last-resort forward recovery point.
6. Apply a reviewed namespace-specific restore tool with compare-and-set/conflict reporting.
7. Never use `FLUSHDB`, `FLUSHALL`, database-wide replace, or a raw volume overwrite while Agent Hub
   depends on the same Redis service.
8. Verify DB1 namespace count/health is unchanged.
9. Start at most one reconciled worker and observe its first claim.

If the queue was empty in both captured and current state, restore no list merely to recreate an
empty key. Preserve the evidence instead.

## Restore storage

1. Restore the archive into a new, explicitly validated directory under the intended backup/restore
   workspace.
2. Verify the full SHA-256 manifest, byte count, file count, ownership and permissions.
3. Compare V1 job IDs with Redis DB0 and the retained schema.
4. Confirm all mixed-owner and `owner-review-v3-*` paths are excluded unless their owner explicitly
   requested an independent restore.
5. Stop only the services that write the exact target paths.
6. Move the current target to a timestamped rollback path; do not delete it.
7. Switch the exact reviewed bind/path atomically where supported.
8. Start the minimum read path and validate retained job/artifact access.
9. Keep both old and restored copies until owner acceptance and retention expiry.

Do not copy V1 media into V2 automatically. A V2 import requires an explicit business need and
rights/provenance contract under V2 ownership.

## Agent Hub Redis DB1 protection

Any rollback involving the shared Redis container must independently prove:

- Agent Hub backup checksum and restore test;
- DB1 namespace/key count before and after;
- task, audit, provider-health and scheduler state;
- no V1 DB0 key was written into DB1 and no Agent Hub key into DB0.

If Agent Hub DB1 has already been rehomed, rollback must not silently point Agent Hub back to the V1
Redis service. That is a separate data migration decision.

## Post-rollback validation

Minimum read-only checks:

- exact container/image/config identity;
- Agent Hub and V1 health/readiness as applicable;
- queue, processing, status and error counts;
- retained legacy status/artifact read;
- storage counts/checksums;
- Agent Hub DB1 health and task/audit availability;
- n8n/Caddy/CRM/SaleHub routes unaffected;
- no unexpected direct port call;
- no provider, publish, messaging, Ads or V2/V3 external action.

Rollback is complete only when the owner accepts the evidence. A running container or HTTP 200
alone is insufficient.
