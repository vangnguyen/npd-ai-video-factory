# AH-P9-RCA-16 — Proposed retention/custody contract

Status: **OWNER POLICY REQUIRED / NOT_GRANTED**. Agent Hub only. This is source
design and a local reference model. No production retention change, archive,
ingest, source/campaign creation, JIT or pilot is authorized or performed.

Baseline `e5d3510d0b7e38a18990cdd27a56cc2491e0b295`; RCA15 receipt
`24f3721f05d99503886a5b20c84d40ae497f737670f736246f3fddbafe4252ee`.
RCA15's 835 accessible Leads supplied no affirmative safe internal source; all
native `campaignId` values were null. Its two historical eviction entries already
left the active audit list, but exact local primary/linked custody was preserved.
Specific old observation hashes never grant a future trim.

## Store inventory and existing semantics

All Redis locations below use Agent Hub DB1 namespace `npd:agent-hub:v1`. A reader
limit of 5000/1000 does not establish a persisted retention cap.

| Store | Existing write/retention | Proposed treatment |
| --- | --- | --- |
| `attribution-os:audit` | `store.py` RPUSH/LTRIM last5000, insertion FIFO; no hold/class guard | Central writer enforcement; unknown class HOLD |
| task audit and `audit:global` | per-task last2000; global last5000 | Protect owned pilot/task/approval/security provenance; apply guard to both affected lists |
| campaign/experiment audits | per-entity last2000 | Policy required; protect cohort policy/mapping/owner decisions |
| task, report, execution records/indexes | task/report SET; execution list last1000 | Current/terminal Phase9 records and exact pre/post bytes protected; ordinary history policy required |
| immutable touchpoints/identity mappings | SET NX; separate indexes; no automatic persisted cap in these writers | Preserve source/event/mapping provenance; no migration/overwrite into authority |
| data-quality/reconciliation snapshots | SET/index; quality acceptance and historical ledger fingerprints | Original and accepted cohort snapshots protected; normal category disposition required |
| delivery receipts/dead letters | exact immutable payload comparison/SET NX; read limits, no cap in these save methods | Protected when source/pilot/incident-related; other receipts need policy and independently verified custody |
| signed heartbeat receipts | immutable comparison; separate5000 cap/payload cleanup | Archive primary raw signed bytes/key ID and verify signature before eligibility; existing cap is not a hold rule |
| provider-health snapshots | separate5000 cap, sorted by observation index, SET may replace same ID, cleanup deletes payload/index | Primary evidence needs approved durable copy; frozen model is not Redis immutability |
| provider-health alerts/status | cached SET/index, open/acknowledged/resolved lifecycle; scheduler lease TTL | Incident evidence protected; lease is ephemeral coordination, not evidence custody |
| NBA review repository | `nba_review_repository.py` SET NX/immutable comparison; separate5000 cap, reviewed-at ZSET and record/global/subject index cleanup | Owned Phase9 review/telemetry and referenced subject records protected; guard its actual `_prune` deletion too |
| remote operation claim/state/attempt files | consumed grant, exact attempt/inventory and terminal custody in sealed contracts | MUST_NOT_EVICT; preserve originals and terminal/recovery receipt bytes |
| recovery receipts/override/capture files | sealed owned recovery, raw before-state and post-read bindings | MUST_NOT_EVICT, including aborted and recovered operations |
| local/remote Phase9 packages and manifests | exact archive/manifest/artifact/runner/verifier hashes, raw capture sidecars | MUST_NOT_EVICT; obsolete packages remain non-authority provenance |
| encrypted namespace/image backups and approval/confirmation custody | DPAPI CurrentUser/current sealed custody; portable Copy2 unavailable | Preserve ciphertext/raw custody and verification bindings; no decrypt/reseal/cleanup here |

The signed delivery/heartbeat receipt proves delivery integrity, not natural
source creation or business non-customer status. Raw audit/receipt/snapshot bytes
must never be replaced by JSON reserialization. Capture's existing
`raw_stdout_sha256` and domain-separated `canonical_payload_sha256` remain distinct.

## Category policy proposed for Owner adoption

1. **MUST_NOT_EVICT**: active operation evidence; owned terminal pilot/recovery,
   consumed Owner grants and confirmation provenance; owned task/report/audit/NBA
   records; source/campaign/policy/mapping/clock proof for the cohort; evidence
   referenced by an active security incident or an explicit hold. An archived
   duplicate does not automatically permit eviction of a protected original.
2. **EVICTABLE_AFTER_DURABLE_CUSTODY**: only exact event classes and reference
   criteria adopted by Owner. Routine scheduled provider-health audit/snapshot
   pairs are a proposed candidate, **not currently disposable**. Verify complete
   raw/link custody, no protected reference/hold, retention lifetime and independent
   archive receipt first. Unclassified ordinary audit/receipt history stays HOLD.
3. **EPHEMERAL**: existing expiring scheduler lease/coordination state, not a primary
   audit or signature. A bounded health cache may be secondary only after its
   primary evidence has approved custody. No primary audit class is declared
   best-effort here.

These are proposed system policy, not invented statutory obligations. Legal,
business/security holds, retention durations, custodians, archive backend and hold
release authority are **OWNER POLICY REQUIRED**. No default expiry or automatic
deletion of Phase9 provenance. Keep audit cap5000; do not silently raise it.

## Durable archive design

Use an Owner-selected Agent Hub-owned archive outside Redis. Smallest existing-host
option: content-addressed raw blobs plus append-only manifests on existing host
storage, with separate custodian permissions/backup and independently verified
restore. Actual root/ACL/custodian/lifetime remain unbound. No new service, volume,
mount, port, provider or credential is provisioned by this design.

Each manifest binds source namespace/ledger, event ID/type/original timestamp,
capture/archival UTC and correlation, exact raw byte count/SHA256, every linked
snapshot/receipt byte count/SHA256, signature verification/key ID where applicable,
policy version/digest, holds/reference classification, storage identity,
independent verification receipt and retention status/lifetime. Store raw grants
and sensitive custody encrypted under the existing accepted boundary; never log
keys or contact data. No overwrite/delete API. Existing digest collision with
different bytes fails closed. Preserve partial/orphan archive attempts as custody;
they never grant trim or retry authority.

The local reference uses O_EXCL, file fsync and independent binary re-read. It is
**not WORM or production crash/durability proof**; it does not fsync a directory or
prevent privileged deletion. Production eligibility requires the separately
accepted backend's atomic publication, file/directory sync where supported,
no-delete/no-overwrite enforcement, independent durable custody and recovery test.
Single-cache existence, a frozen Pydantic object or a SHA alone is insufficient.

## Atomicity recommendation and option comparison

| Option | Assessment |
| --- | --- |
| pre-read/current head-tail digest only | Insufficient: old writer can change list/holds after observation; partial/error audit budget also matters |
| archive copy inside Redis transaction | Redis cannot make an external filesystem durable; not a cross-store atomic solution |
| Lua CAS guard | Valid if all exact ledger/policy/hold/attestation inputs are checked; introduces another script/contract to maintain |
| explicit verified archive state alone | Required binding, but not a substitute for atomic writer checks |
| archive first + explicit WATCH/MULTI writer CAS | **Recommended minimum**: existing Redis transaction primitive, exact raw list/current policy/hold watch, no hidden retry |

Future writer flow:

1. Bind one exact authorized request and success/partial/error audit budget. Read
   the current insertion-ordered lists under WATCH, plus policy/hold registry,
   referenced custody keys and idempotency/commit record. No stale RCA14 hash rule.
2. Compute exact prospective evictees for **all lists** affected by the batch.
   Unknown class, protected original/reference, missing policy or archive backend
   stops before a business mutation. Resolve raw links before eligibility.
3. Publish complete immutable external archive and independent verification. Bind
   immutable archive attestation to exact raw entries/links/current policy. Missing,
   failed, incomplete or mismatched archive cannot authorize append/trim.
4. In one explicit MULTI/EXEC, confirm watched ledger/policy/holds/custody remain
   unchanged and write exactly the approved audit append/trim and commit/custody
   binding. A WatchError means STOP; do not use redis.transaction automatic retries.
   New hold/concurrent append invalidates preparation; orphan archives stay evidence.
5. Exact duplicate commit returns the original receipt without a second append.
   Changed payload/identity is rejected. This audit idempotency does **not** permit
   ingest max_attempts>1 or any expired/aborted/terminal pilot reuse.

All append/trim/cleanup writers must consume the coordinator. Old unguarded writers
or direct Redis mutation are a deployment blocker; they can still destroy custody.
Provider-health/heartbeat primary cleanup must consume the same archive/hold rules.
Business writes and success/error audits need a staged/prepared complete scope and
single transaction or an explicit separately tested partial-write custody contract.
A guard added only after touchpoint creation is not enough. Do not freeze scheduler
or restart a service as a workaround in this task.

Fail closed on missing archive, wrong digest/type/link, protected boundary, current
list/policy/hold change, concurrent writer, unknown category, active operation
reference, missing policy, incomplete write budget, unguarded writer or ambiguous
partial publication/commit. Partial custody is review, never permission to retry.

## Source preparation and limits

`scripts/ops/agent_hub_phase9/retention_design.py` and its local tests prove the
design's boundary/CAS/custody/idempotency conditions on synthetic lists and temporary
files. No Redis client, CLI production entry, HubStore/API import or runner hook is
added. Existing source implementations and every prior Phase9 fix stay unchanged.
Production TOCTOU remains unresolved **until future all-writer integration, backend
validation, exact CI and separately authorized Agent Hub adoption/deployment**.

Source integration needed later: central audit coordinator; all capped writer and
snapshot/heartbeat cleanup hooks; verified archive/hold policy state; exact batch and
partial/error write handling; RBAC-preserving policy management; backend crash and
real concurrent Redis tests. Reference tests are not those production proofs.

## Owner decision 1 — Retention/Custody Policy Adoption

Status: **NOT_GRANTED**. Separate from cohort creation.

- Exact requested disposition: adopt the above category/reference/hold rules;
  decide routine scheduled-health eligibility, custody backend/root/permissions,
  independent verifier/copy, retention periods and hold release authority. Bind
  reviewed document/source hashes and exact future implementation before activation.
- Expected writes of policy adoption now: repository/governance record only;
  **0 production writes**. No Redis trim or archive activation is granted.
- Future activation requires separately approved archive files/attestations,
  policy/hold/commit metadata and guarded writer appends/trims, with exact scopes.
- Prohibited: backdated stale eviction approval, cap increase, protected evidence
  loss, credential/provider/customer/CRM/Sales/Video action, ingest or pilot/JIT.
- Rollback: keep new raw custody; return writer to HOLD. Never redeploy an unguarded
  writer against a ledger whose safety depends on the new policy. Image rollback
  needs its own bounded approved contract; no data deletion is a rollback.
- Evidence: store inventory, exact category disposition, reference/hold checks,
  raw linked archive verification/durability/restore, concurrent Redis/all-writer
  integration and exact candidate CI. Current local reference proof is insufficient
  activation authority.
- Restart/deploy: **NO for policy review/adoption; YES for later Agent Hub writer
  integration**, separately gated. No production action is executed here.
