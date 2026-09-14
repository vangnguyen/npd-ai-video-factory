# AH-P9-RCA-18A2 — Retention source integration review

Agent Hub ONLY. This branch implements and tests retention boundaries. It is a
source review candidate, not an adopted runtime, production backend or activation.
No Campaign/Lead preparation, ingest or Phase 9 execution is included.

Baseline: design HEAD `3991b7e881aaa8162525f7759cfdd4a0c547867a`, RCA18A
receipt `bcfaec8c0622fd2997d09cb2a9ddad711f1eaa61bbeb161ca23363115b629b87`.
Owner conditionally adopted S3 Object Lock, the 90/180/365 framework and three
independent hold authorities for this source integration. Provisioning, production
connections, credentials, spending, archive upload and activation are unauthorized.

## Resulting behavior

Factory Memory/Redis coordinators are inactive. Writer and multi-writer operation
boundaries reject before mutation. The read-only application stays available;
business writes receive HTTP 503 `RETENTION_CUSTODY_HOLD`. Scheduler startup cannot
write or start through an inactive coordinator. Legacy maintenance confirmation
cannot bypass retention; file backup output is HOLD, stdout export remains read-only.
There is no activation, hold release, deletion, automatic retry or production
backend connector in this candidate.

Explicit Memory, fakeredis and selected TemporaryDirectory fixtures provide local
simulation only. They cannot activate a remote Redis client. An actual S3 transport,
authenticated configuration/principal binder, production category/link resolver,
live writer census and backend/real-Redis acceptance remain separate prerequisites.
The S3 module validates static requirements/readback shapes and produces no request.

## Exact category to period proposal — Owner review required

These are archive minimums starting at independently verified archive UTC, not
automatic disposal dates. An active Redis entry may leave the ledger only after
current policy, exact raw/linked archive verification and atomic writer checks.

| Canonical category | Minimum archive period | Required classification proof |
| --- | --- | --- |
| routine_provider_health_nonincident_nonpilot | 90 days | Ordinary aggregate; no active incident/hold/operation/pilot reference; all linked custody resolved |
| ordinary_nonpilot_signed_delivery_and_deadletter | 180 days | Closed ordinary nonpilot delivery; exact signed receipt/deadletter/index links; no active/terminal/security reference |
| ordinary_nonpilot_audit_and_linked_snapshot | 365 days | Ordinary nonpilot audit/snapshot; exact linked raw bytes; no active/terminal/Owner/security reference |
| active_operation | indefinite HOLD / MUST_NOT_EVICT | No period releases the original |
| terminal_phase9_recovery | indefinite HOLD / MUST_NOT_EVICT | All historical pilot, claim-only and recovery custody, including links |
| owner_authorization | indefinite HOLD / MUST_NOT_EVICT | Authorization/grant/consumption provenance |
| held_security_incident | indefinite HOLD / MUST_NOT_EVICT | Hold remains until a separately verified disposition; no release API here |
| unknown or unresolved links | indefinite HOLD / MUST_NOT_EVICT | Missing classification is never an evictable fallback |

`provider_health_scheduled_evaluation` is not blanket-disposable. The production
resolver must prove it belongs to the first category, with no incident/hold/pilot
reference. Synthetic fixture classifiers are not that proof. Category mapping,
classification schema, policy digest and legitimate lifecycle closures are UNBOUND.

## Named hold authorities — identities UNBOUND

| Responsibility | Exact identity to supply before activation | Evidence |
| --- | --- | --- |
| Request/adopt disposition | Named authenticated Owner principal | Authenticated subject, approved role and immutable policy/authorization receipt |
| Verify | Independent named verifier principal | Independent raw/version/linked readback and explicit verification digest |
| Execute custody administration | Separate named custodian principal | Least privilege role, exact scope and independent authorization |

Three distinct stable identities are required. Cosmetic name/case differences do
not provide separation. Fixture labels are not production principals. Period expiry
never releases a hold or authorizes archive deletion. Release/deletion implementation
and authority are deliberately absent; they need a separate source/security review.

## S3 configuration decision package

Primary architecture is conditionally adopted; account, region/residency, bucket,
prefix, encryption key identity, cost ceiling and exact IAM principals remain UNBOUND.
Owner must select fixed GOVERNANCE or COMPLIANCE mode after reviewing recovery and
irreversibility. GOVERNANCE requires denied bypass; the writer receives no bypass,
delete, hold-release, policy-update or provisioning permission.

Required: versioning and Object Lock; enforced conditional `PutObject` with
`If-None-Match: *`; unique content-bound key and pinned returned VersionId; separate
raw/linked object digests; independently authenticated version-specific readback;
retention readback sufficient from verified UTC; deletion/deletemarker denial;
no lifecycle deletion; encryption and recovery readback. Failure/unknown result
preserves custody and stops, rather than retrying an upload or trimming.

Object Lock protects a version, permits newer versions/deletemarkers, and therefore
does not alone prove create-only key behavior. See [S3 Object Lock](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html)
and [conditional writes](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html).
B2/R2 remain alternatives; no AWS/B2/R2 resource or credential is selected/created.
Actual backend acceptance is NOT_RUN, and local dictionaries are not WORM custody.

## All-writer and reference coverage

The sealed source inventory identifies 50 DB1/Memory functions: prior 47 plus three
previously missed Memory scheduler-state/lease writers. All 67 prior call sites are
covered: 62 external calls enter a store operation batch; five nested `_touch`/`_prune`
calls use the same guarded writer. Nested Redis WATCH callbacks receive the staged
transaction facade within their guarded parent; CI verifies that call path.

All 22 file candidates are dispositioned: 11 actual writer helpers use one canonical
registry-first guard; one isolated design `_write` already uses O_EXCL/fsync and its
local archive contract; ten are read-only string/timestamp replacement false positives.
Maintenance file backup is an additional explicit HOLD boundary. The renderer inlines
the identical file contract into the standalone runtime, preserving default HOLD.

File scopes preserve exact prior/new local versions and register bound references
before publication. Source file/path errors stop and preserve partial custody.
The actual production reference/category/link binder is absent: zero references
must never be inferred from a fixture's empty relation. A live unintegrated referencing
producer, unknown helper or bypassing credential blocks activation.

## Atomicity and uncertainty

Local Redis tests stage all commands, archive current raw victims and links, independently
verify, then execute one WATCH/MULTI journal. WATCH includes all observed keys plus
shared reference registry and writer epoch. Every guarded commit advances the epoch,
detecting another integrated writer even when it appends an unobserved new key.
Reference publication uses CAS; a race stops without automatic retry. Policy/backend,
hold, reference, ledger type and generation mismatches stop before commit.

Two control keys per namespace may be created: references and writer-epoch, under
`npd:agent-hub:custody-control:<namespace-digest>:` outside the business namespace.
They must be explicitly authorized in future migration/activation and cannot be
counted as unchanged infrastructure. Existing ledger/snapshot caps remain 5,000.

SET replacement, LTRIM, DELETE, ZREM/score replacement and TTL boundaries preserve
prior/current raw custody; index members use an explicitly encoded member/score
record, not a falsely named stdout digest. Memory prior versions are local model
bytes, never substituted for captured transport bytes. Async operations serialize
their local batches; child tasks cannot borrow active or committed batch contexts.

WATCH conflicts perform no guarded commit. Redis EXEC runtime errors can leave
successful commands applied; response loss is also uncertain. Both stop the coordinator
for review with original archive preserved, and no retry/rollback inference. See
[Redis transactions](https://redis.io/docs/latest/develop/using-commands/transactions/).
No local result claims real Redis/server/filesystem/S3 crash or durability acceptance.

## Migration/rollback and 5,000-entry compatibility

1. Separately authorize a quiesced all-writer census, real isolated backend acceptance
   and activation preparation. Do not enable this review candidate as a pilot.
2. Capture current DB1 ledger/index/TTL/reference and terminal filesystem custody.
   Compare all exact raw hashes; historical pre-read eviction hashes are not authority.
3. Classify legacy entries UNKNOWN/HOLD until accepted current policy/link proof.
   Do not change the cap, reorder records, backfill timestamps or migrate receipts
   into execution authority. Preserve terminal Phase 9/recovery metadata and archives.
4. Archive-before-any-destructive-boundary, read back exact versions and links,
   then bind policy/principals/backend and guarded writer/control namespace scope.
5. Simulate 4999/5000 append, protected oldest, whole-operation rejection, types,
   TTL, concurrent new keys/reference publication and uncertain EXEC. Local migration
   restore defaults HOLD and protected replacement cannot delete the original.
6. In a later activation gate, require actual backend ACL/version/create-only/retention
   readback/recovery/crash acceptance, actual Redis concurrency and independent
   production all-writer/reference coverage. No source-only green test substitutes.
7. Safe rollback first freezes writers and retains guarded HOLD/control/archive/hold
   state. Do not roll back to the unguarded 3991 writer at cap. Do not delete archives,
   release holds, retry consumed batches or restore Redis as an automatic rollback.
   An uncertain/partial transition requires exact custody reconciliation and Owner review.

## Production activation gate

HOLD_NOT_PREPARED. Backend provisioning NOT_AUTHORIZED. Production activation
NOT_AUTHORIZED. Exact category mapping/principals/backend configuration, production
adapters/resolvers, census and real acceptance are missing. No executable approval
text, operation, execution window, confirmation, JIT or ingest is generated.

Requested next decision: retention-only source review plus exact category mapping,
named Owner/verifier/custodian and backend configuration/acceptance plan. Any provisioning,
production connection, archive, migration/deploy or activation needs a separate exact
current approval after the missing proof is prepared.
