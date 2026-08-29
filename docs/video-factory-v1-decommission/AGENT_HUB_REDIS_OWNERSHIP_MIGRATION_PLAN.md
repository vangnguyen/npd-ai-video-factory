# Agent Hub Redis ownership migration plan

Status: **AH-R01 offline candidate PASS; production M1/M2/M3 not accepted or executed**

This plan separates Agent Hub data ownership from the Redis container owned by Video Factory V1.
It does not authorize a deployment, write pause, export, restore, network change, container action,
configuration change, or deletion.

## Current evidence

Production Agent Hub uses DB1 of `npd-ai-video-factory-redis-1` through
`redis://redis:6379/1` and joins the V1 Compose network. The V1 API and worker use DB0 of the same
Redis instance.

The read-only AH-01B scan observed ongoing Agent Hub activity:

| Observation | Value |
|---|---:|
| DB1 size at `2026-08-29T04:21:00Z` | 6,405 keys |
| DB1 size during type/TTL scan | 6,409 keys |
| Keys under `npd:agent-hub:v1:*` | 6,409 |
| Non-Agent-Hub DB1 keys | 0 |
| Strings / lists / sorted sets | 6,092 / 302 / 15 |
| Unsupported types | 0 |
| Keys with positive TTL at the scan | 0 |

A fresh AH-01C read-only scan at `2026-08-29T06:31:55Z` observed 6,483 namespace keys
(6,166 strings, 302 lists and 15 sorted sets), zero outside-namespace keys and zero positive TTLs.
The increase from the earlier scan confirms that a production export still requires an approved
writer-quiesce window.

The changing key count proves that migration cannot use an uncoordinated copy. DB1 activity is
Agent Hub activity, not V1 queue activity. DB0 remained 12 job records with queue/processing empty.

The AH-01C version 2 logical maintenance format now records per-value checksums, absolute expiry,
source stability, type counts and namespace/content fingerprints. It fails closed on source drift,
unsupported types, checksum corruption, namespace mismatch and an unexpected non-empty target.
Version 1 restore remains supported as non-expiring legacy input.

## Accepted target architecture

The future target should have these properties before cutover approval:

- Redis is owned by the Agent Hub deployment, not by Video Factory V1.
- It uses a dedicated instance and persistent volume; Agent Hub may use DB0 because instance-level
  isolation replaces shared logical-database isolation.
- It is attached only to an Agent Hub data network and has no host-published port.
- Authentication/ACL material is supplied through an external protected secret, never committed or
  printed.
- AOF persistence and an independent encrypted backup policy are enabled and tested.
- The namespace remains `npd:agent-hub:v1` so application identity does not change during the
  infrastructure move.
- V1 DB0 keys are never copied into the Agent Hub-owned instance.
- The V1 network remains attached to Agent Hub only while the separately owner-gated legacy video
  API dependency exists; Redis separation must not be coupled to a traffic switch.

## Migration stages and gates

### M0 — Offline proof

1. Add a TTL-aware export contract or a preflight that rejects any positive TTL and unsupported
   type.
2. Export a representative synthetic namespace and restore it into an isolated Redis 7 instance.
3. Compare key names, types, values, order, sorted-set scores, TTL semantics, and application
   read-model results.
4. Exercise backup corruption, namespace mismatch, non-empty target, and rollback cases.

Exit: CI and independent local Redis restore pass. This is tooling proof only, not production-data
restore evidence.

Result: **PASS on 29/08/2026**. Two disposable Redis 7 containers exercised string/list/sorted-set
data plus an expiring scheduler lease. Namespace/value/type/TTL parity, fail-closed cases, explicit
replace rollback and AOF-backed restart persistence passed. The containers and volume were removed;
no production connection or write occurred. See
[`agent-hub-redis-m0-evidence.json`](agent-hub-redis-m0-evidence.json).

### M1 — Owner-approved target provisioning

Provision the Agent Hub-owned Redis/network/volume without changing `AGENT_REDIS_URL`. Verify
health, persistence, authentication, no host exposure, monitoring, free disk, and an empty target
namespace.

Gate: owner approves the production deployment and secret/config changes.

Candidate result: **offline PASS; production NOT RUN**. The AH-R01 override, external password-file
contract, exact-image/commit preflight and guarded empty-target provisioner are implemented. See
[`AH_R01_REDIS_INDEPENDENCE_GATE.md`](AH_R01_REDIS_INDEPENDENCE_GATE.md). Their presence in Git is
not an M1 approval.

### M2 — Restore rehearsal outside production

Create the owner-approved encrypted DB1 logical export, restore it to an isolated target, and verify:

- source/export/target key count and type histogram;
- canonical per-key checksums without logging values;
- no key outside `npd:agent-hub:v1:*`;
- expected TTL behavior;
- task, report, audit, campaign, attribution, experiment, receipt and provider-health read models;
- target restart persistence.

Gate: signed restore report and rollback rehearsal accepted by the Agent Hub data owner.

Candidate result: the namespace-only age streaming exporter and identity-safe read-model probe are
prepared, but no production export, decryption or restore has run. Portable recovery identity
access remains a separate owner/custody gate.

### M3 — Quiesced cutover

This stage requires a separately approved change window. Stop or block Agent Hub writers only;
never stop V1 or Redis as a shortcut. Release/expire the scheduler lease, capture a final logical
export plus source fingerprint, restore the empty target, compare fingerprints, update only
`AGENT_REDIS_URL`, recreate Agent Hub, and run read-only health/read-model checks before controlled
mock-only writes.

Abort on any source drift, unsupported type, positive TTL without explicit handling, count/hash
mismatch, target persistence failure, or Agent Hub health regression.

Candidate result: **not automated, not approved and not run**. The action-time owner must review a
fresh snapshot and exact cutover/rollback commands; the readiness PR cannot authorize M3.

### M4 — Rollback window

Rollback changes Agent Hub back to the old DB1 endpoint using the pre-cutover configuration and
forward-recovery export. Do not merge divergent writes automatically. Keep both Redis instances and
all evidence for the accepted 7–14 day observation window.

Only after the owner accepts the observation evidence may the old DB1 copy become an archived
dataset. V1 Redis still cannot be stopped until all other V1 gates pass.

## Acceptance checklist

- [ ] Target architecture/security design accepted at the production M1 owner gate.
- [x] TTL-aware or fail-closed export behavior implemented, merged and locally tested.
- [x] Synthetic isolated Redis restore PASS.
- [x] Dedicated Redis topology/password-file/AOF candidate PASS offline.
- [ ] Agent Hub-owned production Redis target provisioned and verified empty.
- [ ] Encrypted production DB1 export captured outside production.
- [ ] Production export restored and verified outside production.
- [ ] Source/target key, type, checksum and application read-model parity PASS.
- [ ] Target restart persistence PASS.
- [ ] Cutover and rollback change windows explicitly approved.
- [ ] Fresh snapshot shows no unexplained source drift.
- [ ] 7–14 day observation accepted.

Until every applicable item passes, `shared-redis-runtime` remains a migration blocker and no V1
Compose-level stop is safe.
