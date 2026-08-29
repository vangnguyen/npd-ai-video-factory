# Video Factory V1 backup and restore plan

Status: **TECHNICAL RESTORE PASS; owner acceptance pending; shutdown remains NO-GO**

AH-01B captured production V1 data by read-only streams, created no temporary file on the VPS,
did not invoke `SAVE`/`BGSAVE`, stop a writer, restore production, or export Agent Hub DB1. It built
an encrypted off-production bundle and completed a real isolated restore/restart drill. Protected
runtime bytes remained encrypted at rest and were not decoded into logs.

Local Docker/Redis is available. On `2026-08-29`, the stream-only DB0 exporter, validator and
guarded isolated restore verifier passed a two-key synthetic drill (one job string and one queued
item), followed by a container restart and a read-only 2/2 checksum/type/queue recheck. The test
container used Redis 7, `--network none`, no published port and the required
`npd.ah01b.restore-test=true` label. This validated the tooling and synthetic restart boundary
first; an empty DB0 also validated, and an unrelated key was rejected. The subsequent dated
production-data bundle and restore evidence are recorded in
[`v1-backup-restore-evidence.json`](v1-backup-restore-evidence.json).

## Required bundle boundary

The bundle must be stored outside production and outside Git, encrypted at rest, access-controlled,
and assigned an owner, retention deadline and deletion procedure. A valid bundle contains:

| Dataset | Capture requirement | Restore requirement |
|---|---|---|
| Redis DB0 V1 keys | Per-key binary `DUMP`, type and PTTL; include explicit empty queue/processing snapshot | Restore into isolated Redis 7; compare per-key dump hashes and job-state aggregates |
| `storage/jobs` | 98-file checksummed archive at current baseline | Extract to isolated path; verify all paths, sizes and SHA-256 values |
| `storage/assets` | Separate owner-approved archive because assets are shared/rights-sensitive | Restore only for V1 rollback; never import automatically into V2/V3 |
| `production-pilot-artifacts` | Checksummed archive with ownership/retention metadata | Verify manifest/media hashes and path safety |
| V1 contracts/source | Immutable schema plus exact source commits from the provenance manifest | Validate retained job manifests without rebuilding production |
| Exact application images | `docker image save` streams for the three recorded image IDs | Load locally, verify loaded IDs/content and run isolated health/fixture checks |
| Redis base image | Pin current digest `redis@sha256:e7723ff73d963f5cc6d9c4643ea3d989527a402a319239054e9472a7fb9219a2` | Pull/load by digest and perform persistence restart test |
| Runtime logs/protected backup | Opaque encrypted archive with separate sensitivity metadata; never print/decode secret values during capture | Restore only inside the isolated encrypted workflow; never co-locate plaintext credentials with general artifacts |

The four `owner-review-v3-*` directories are not V1 rollback data. They are `KEEP` datasets in the
storage ownership manifest and must not be copied, moved, deleted or treated as V1 backup payloads.
The protected `.runtime/env-before-v2-20260814T080332Z.backup` was included only as bytes inside the
AES-256-GCM runtime payload. AH-01B did not decode, display or log its contents. Retention and DPAPI
key custody remain an explicit owner gate.

## Bundle manifest contract

The top-level manifest must record:

- unique bundle ID, capture window, source host and checkout;
- every artifact's relative path, byte size, SHA-256, sensitivity and owner;
- Redis key count/type/TTL histogram and per-key dump SHA-256 without decoded values in logs;
- exact Docker image IDs, source commits, exported tar SHA-256 and loaded-image verification;
- exclusions with explicit reason;
- encryption method/key owner reference without key material;
- tool versions and capture exit statuses;
- restore-test environment, start/end time, assertions, failures and operator approval.

Capture must stream read-only data directly to the approved off-production encrypted destination.
It must not create a server-side tar/RDB/temp bundle, call `SAVE`/`BGSAVE`, alter Redis persistence,
or include Agent Hub DB1 in the V1 DB0 export.

## Isolated restore drill

1. Verify bundle-manifest signature/checksum before decrypting.
2. Create an isolated network with no provider credentials and no outbound media/provider action.
3. Load the pinned Redis base image and exact API/worker/renderer images.
4. Restore DB0 per-key dumps and the approved storage datasets into isolated volumes.
5. Start Redis first; validate 12 job records, 7 `awaiting_review`, 5 `failed`, queue 0 and
   processing 0.
6. Start API/renderer without provider credentials and run health, status and retained-artifact
   reads. Do not start a paid-capable worker unless it is hard-disabled from provider/network calls.
7. Compare every restored file and Redis dump checksum with the bundle manifest.
8. Restart the isolated Redis/API and repeat persistence/read checks.
   Use `verify-isolated-existing --phase post-restart` to compare the existing Redis DB0 without
   issuing a second `RESTORE`; preserve independent container lifecycle evidence because the phase
   label itself is an operator assertion.
9. Destroy only the explicitly named isolated test environment after preserving the signed report.

## PASS criteria

PASS requires all datasets, exact image exports, checksums, Redis semantic checks, restored media,
restart persistence and negative safety tests to succeed in the same dated drill. Partial capture,
source-code reconstruction, Docker image IDs without exports, synthetic tests, AOF presence, or a
green CI run cannot satisfy this gate.

## Current result and remaining gates

The `2026-08-29` bundle contains 16 AES-256-GCM payloads totaling 1,895,938,306 bytes. Its key is
protected by Windows DPAPI CurrentUser. The isolated restore verified all 12 DB0 keys and restart
parity, 106 selected storage files, 45 pilot files, 17 protected runtime files, exact application
and Redis images, API/renderer reads, internal-only networking and complete cleanup. Technical
restore status is **PASS**, and `v1-backup-restore-coverage` is `KEEP`.

This result is dated evidence, not production authorization. The owner must still accept retention
and DPAPI key custody, a second protected copy must exist before any shutdown, and a fresh
forward-recovery snapshot must be captured at the approved change gate. Agent Hub DB1 requires its
own approved backup/restore and rehome plan. The remaining publication-reference `UNKNOWN`,
telemetry/observation, Redis ownership and all explicit owner gates keep AH-03 and shutdown NO-GO.
