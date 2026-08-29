# AH-01B — UNKNOWN resolution evidence

Status: **investigation in progress; V1 decommission remains NO-GO**

AH-01B is a read-only production investigation and an offline documentation/tooling change. It
does not deploy, restart, stop, block writes, change Caddy, migrate Redis, move/delete storage,
close ports, mutate n8n, call a provider, read a secret, or modify Video Factory V2/V3.

## Evidence snapshots

| Snapshot | UTC | Result |
|---|---|---|
| AH-01 baseline | `2026-08-29T02:49:35Z`–`2026-08-29T03:04:30Z` | 8 `UNKNOWN`; shutdown NO-GO |
| AH-01B runtime recheck | `2026-08-29T04:21:00Z` | Same checkout and image IDs; V1 DB0 12 keys; queue/processing 0; Agent Hub DB1 6,405 keys |

The DB1 increase from the AH-01 snapshot is Agent Hub state activity. It is not V1 queue activity.
The V1 queue and processing list remained empty at the AH-01B snapshot.

## Observed direct renderer request attribution

The specific renderer request previously recorded as unattributed is now attributed to the Codex
V3 owner-review workflow. This finding resolves the identity of the **observed request only**; it
does not prove that no historical or future caller exists.

Evidence chain:

1. Local Codex thread `01a04949-b7d1-7520-a46a-8e5fa5a8cb4e`, rollout ordinal 974 at
   `2026-08-28T17:42:04.456Z`, issued a host-local HTTP request to
   `http://127.0.0.1:3001/render` over the existing strictly host-key-pinned SSH session.
2. The request used job ID `vid_1787989200000_a1b2c3d4e5`, manifest
   `/workspace/storage/owner-review-v3-final-20260829/video-manifest-v3.json`, and output
   `/workspace/storage/owner-review-v3-final-20260829/production-pilot-v3-owner-review.mp4`.
3. The command result at `2026-08-28T17:44:48.333Z` returned `status=complete` for that exact job
   and output path. Renderer progress for the same ID ended at
   `2026-08-28T17:44:48.378506689Z`.
4. Production and the preserved local V3 review package match exactly:

| Artifact | SHA-256 |
|---|---|
| `video-manifest-v3.json` | `e2db8c77edc5b19651b5d4cee99c1e9e86bd043a85632bfd76869aa6f60ae44c` |
| `production-pilot-v3-owner-review.mp4` | `9add7bf1b94b1d0a34eddb3a3acd6392d627c4342a3e67c14251f268094bddaf` |
| `production-pilot-v3-narration-owner-review.wav` | `79e5d739d92473a05207aff07290ad0d17b5a0108f9963aeaa9f9ef6d22d7d55` |

This was a one-off owner-review render initiated by Codex, not an Agent Hub or n8n execution. It
was not a V2/V3 runtime call, deployment, publication, or owner acceptance. The V3 human-listening
gate remains independent.

The caller attribution permits the component decisions to become directional:

- `v1-renderer-service`: `DEPRECATE`;
- `v1-render-route`: `DISABLE` as a future target.

Neither decision authorizes a production change. Identity-safe request telemetry and a fresh
observation window remain prerequisites for any port, route, or service action because current
renderer logs do not independently identify callers.

## Running image source attribution

Read-only image inspection and source hashing at `2026-08-29T04:21:00Z` established:

| Service | Exact running image ID | Created | Source-input match |
|---|---|---|---|
| API | `sha256:5c7597d6da754baaac21effe6c3511ab16460659ead7233b2fde1fe5af75e2f7` | `2026-08-14T15:09:09+07:00` | 10/10 copied inputs match `78273a6d082dc90f8eae0ea57c2b30165e4328cc` |
| Worker | `sha256:8d367182ab9ca08d17b5d30b524281b951d27bc5a91168bc340adab0f79c962c` | `2026-08-14T15:19:36+07:00` | 25/25 tracked copied inputs match `a92785dc1721ec4e991bf12655629d809e13c241` |
| Renderer | `sha256:e42b8c5bf9a047d4b5031ddf9fdadffbd0acd38bfa34b50a7a23227a71ecaf33` | `2026-08-14T15:19:12+07:00` | 8/8 copied inputs match `a92785dc1721ec4e991bf12655629d809e13c241` |

All three application images are local `:latest` images without registry digests or revision
labels. Source attribution is now resolved, but rollback portability is not: no exact image export,
checksum, independent retention location, or restore drill exists yet. Those requirements remain
under `v1-backup-restore-coverage`; rebuilding from any checkout is not a substitute.

The complete 43-file evidence is recorded in
[`v1-runtime-image-provenance.json`](v1-runtime-image-provenance.json).

## Storage ownership resolution

A read-only metadata/SHA-256 scan classified all 194 files and 212,365,362 bytes under the mixed
storage root. It found six top-level groups and no unclassified group:

- `jobs/`: 98 V1 files, 168,719,888 bytes, `MIGRATE`;
- `assets/`: 8 legacy shared assets, 8,496,188 bytes, `MIGRATE` and owner-gated;
- four `owner-review-v3-*` groups: 88 files, 35,149,286 bytes, `KEEP` and protected from V1
  decommission.

See [`v1-storage-ownership-manifest.json`](v1-storage-ownership-manifest.json). Ownership is now
resolved by path prefix, so `mixed-storage-root` becomes `MIGRATE`; whole-root mutation remains
prohibited and the manifest itself grants no storage action.

## Local backup-tooling proof

On `2026-08-29`, a disposable local Redis 7 source and guarded target validated the stream-only
DB0 exporter and verifier using two synthetic keys: one V1 job string and one queued item. Export
schema/checksums validated, the isolated restore matched 2/2 keys, and queue/processing lengths
matched 1/0. After restarting the target container, the read-only existing-state check again
matched 2/2 keys, their serialized checksums/types, and queue/processing lengths. Both containers
used `--network none`, exposed no ports, and were removed afterward. An empty DB0 validated as a
zero-key export, while a DB0 containing an unrelated key failed closed with no accepted payload.

This is synthetic tooling evidence only. No production data was exported or restored, no full V1
bundle was built, and the lifecycle phase in the verifier report remains an operator assertion.
The `v1-backup-restore-coverage` decision therefore remains `UNKNOWN` and real restore status
remains `NOT RUN`.

## Remaining boundary

`destructive_change_allowed` remains `false`. A resolved classification is not an authorization to
act, and a design or runbook is not restore evidence. The inventory and risk register remain the
canonical gate sources.
