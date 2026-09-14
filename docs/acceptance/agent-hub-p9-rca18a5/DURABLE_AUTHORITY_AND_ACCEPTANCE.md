# AH-P9-RCA-18A5 — durable authority, preparation only

Owner accepted RCA18A4 three-party SOURCE/DESIGN, branch
`feat/agent-hub-p9-rca18a4-custody-authority`, exact baseline
`b44d39ee66e41588f0fc625b4167c94329c25417`, handoff
`f013590838fd8987b2f21b26976e31bd6c987bf931dc58568a47155fc3617b72`.
No identity, credential, backend, production archive or activation authorization.
Internal campaign/Lead work is excluded. No custody hold release or delete path.

## Journal contract and local implementation

`AuthorityJournal` separates replay/actor/receipt persistence from archive storage.
The accepted authority state machine is unchanged. `DurableCustodyAuthority`
loads it only inside a verified journal transaction, authenticates each signed
action again, then commits exact state and receipts before returning ALLOW.
Authenticated denial and consumed token ID are durable too. Idempotent reads do
not append. Missing/corrupt/unknown journal or unavailable backend means HOLD;
no memory fallback. Both concrete journal and wrapper explicitly deny production
mode. The only backend is SQLite in an explicit isolated OS-temp fixture scope.
It cannot connect to Redis, S3, network storage or a configured production path.

SQLite WAL, synchronous FULL, BEGIN IMMEDIATE and zero busy timeout provide
local disk transactions and single-writer exclusion. A conflict is DENY, without
retry. Every commit appends the complete deterministic UTF-8 state as raw BLOB,
state SHA-256 and a domain-separated commit digest bound to journal UUID, pinned
credential-trust digest, sequence and previous commit. Previous receipt bytes
are immutable prefixes. Input/actors/archive digest are immutable, action order
only advances, consumed cannot revert and expiry cannot extend. Readback verifies
all history and reconstructs the exact authenticated action/capability chain.
Public action requests never accept caller identity, role or capability fields.

Opening an existing journal requires an independently supplied minimum checkpoint
(journal ID, sequence, state and commit digests). Missing checkpoint is HOLD.
A retained latest checkpoint rejects a fully consistent restore to older state.
Unkeyed hashes alone cannot detect an attacker replacing the entire database
and its independently trusted checkpoint. Production must independently retain
and attest each acknowledged latest checkpoint before any restored journal can
grant authority. This local backend proves ordinary process restart/replay and
checkpoint-fenced rollback, not power-loss, storage-administrator or real backend
disaster recovery acceptance. No journal compaction, transaction/JTI deletion,
automatic restore, reactivation or automatic retry is implemented.

## Backend comparison and recommendation

| Journal option | Atomicity and recovery | Preparation disposition |
|---|---|---|
| Redis CAS/Lua | Existing infrastructure; atomic local commands. Persistence, fsync, no-eviction, restore fencing and replica ACK semantics must be proved | Alternative, not accepted from current Redis presence alone |
| Relational SQL (PostgreSQL) | Unique transaction/JTI keys, row locks, transactional receipt sequence, durable commit and explicit recovery/export | Recommended production journal target; instance, cost and configuration UNBOUND |
| Append-only files | Exact raw custody, but process locking, atomic index, partial append and cross-host recovery require new machinery | Suitable exported custody/checkpoints, not primary concurrent journal |
| Object-store chain | Immutable/versioned receipts; conditional create can reject a duplicate object, but concurrent transaction head/action/JTI coordination is separate | S3 archive target, not sufficient primary journal authority |
| Existing DB1/Memory stores | DB1 is capped mutable operational storage; Memory loses replay on restart. Existing terminal file custody is operation-specific | Not reusable as journal without a separately verified adapter |

Production recommendation: PostgreSQL transactional journal, S3 Object Lock
archive, independent attested checkpoint export. SQLite is a deterministic local
proof of the abstraction, not a production SQL driver. A future SQL adapter must
use unique journal/transaction/JTI constraints, locked revision comparison,
append-only receipts, synchronous commit, least privilege, encrypted transport,
backups and latest-checkpoint restore fencing. Provisioning/spend is separate.
If Owner chooses Redis instead, an explicit no-eviction persistent journal namespace,
durable ACK/restore fence and complete race/outage acceptance are prerequisites.

SQL journal consume and DB1 writer CAS are not one distributed transaction.
Consume is durably acknowledged BEFORE writer CAS. Crash/conflict/lost ACK may
leave consumed authority with no business write; this is HOLD/review, never
automatic reuse. A future recovery reconciliation may read transaction/CAS
evidence only; it cannot rearm a consumed transaction. Production activation
also needs complete all-writer enforcement and independently attested journal
ACK/checkpoint ordering. No distributed exactly-once claim is made here.

## Identity contract and current issuer blocker

Current Agent Hub static tokens yield role subjects, not named issuer/sub.
Google login validates a human and creates an HMAC email/role session; it does
not issue custody-scoped service tokens or preserve stable Google issuer/sub
through an authenticated custody bridge. The source contains a scoped RS256
verifier, not a custody issuer or service-principal provisioning interface.
**Production issuer and ability to issue three independent stable principals
are UNBOUND/NOT_PROVEN. Stop production identity acceptance until Owner selects
an issuer/bridge and provides authenticated configuration evidence.** Do not
invent an issuer URL, named Owner subject or production key fingerprint.

| Principal | Required production binding | Capability maximum |
|---|---|---|
| Requester | Selected exact HTTPS issuer; immutable authenticated human sub; independent trusted Agent Hub Owner binding; audience `npd-agent-hub-custody-p9` (proposed); typ `npd-custody+jwt`; separately pinned requester key | `custody.hold.request` |
| Verifier | Same selected issuer or separate issuer in a future separately reviewed federation; proposed stable sub `npd-agent-hub-custody-verifier-p9`; independent service enrollment; separately pinned verifier key | `custody.archive.verify` |
| Custodian | Selected exact issuer; proposed stable sub `npd-agent-hub-custody-custodian-p9`; third service enrollment; separately pinned custodian key | `custody.archive.write`, `custody.commit` |

Proposed strings are configuration requirements, never authenticated identities.
Current source authenticator pins one issuer per authority instance; federation
is not implemented. Actual issuer, stable human subject, service enrollment IDs,
key IDs/fingerprints and controller identities must be exact before Gate A.
Every scoped bearer binds action, custody UUID, input/result/previous-receipt
digests, JTI, iat/nbf/exp, issuer/audience/type and maximum lifetime 900 seconds.
No token refresh/retry or role/session-to-custody automatic conversion exists.

`IndependentCredentialAuthenticator` enforces three different actual RSA public
key fingerprints and key IDs, with server-pinned key-to-subject bindings. The
same public key under aliases is rejected. A valid Owner-key signature claiming
verifier/custodian subject is rejected. One verifier key cannot impersonate the
custodian. Each credential has exact least-privilege capabilities; neither
business role aliases nor frontend state grant custody. These are distinct
delegated per-principal signing credentials under an approved issuer policy,
not one issuer signing secret shared with all three actors. A future issuer
must explicitly support and attest this key-subject issuance/enrollment model.

Credential independence requirements: human requester keys remain under the
trusted issuer/Owner-auth bridge; verifier and custodian credentials are stored
in separate service secret controllers/workload boundaries. Each has a separate
issuance/rotation operator and access audit. No credential is created by this
task. Rotation/revocation changes the pinned trust digest and must pause journal
authority pending a separately verified trust migration; old journal trust is
not silently replaced. A compromised requester can request but not archive/
verify/commit; compromised verifier can attest but not archive/commit; compromised
custodian can archive/commit only independently verified exact transactions.
Issuer or common infrastructure compromise remains a trust-domain risk requiring
independent enrollment/controller attestation, not solved by subject names.

## Authority to archive to retention

Owner request → custodian creates immutable archive/raw+linked receipt →
independent verifier reads exact version/checksum/retention and signs verification
→ same custodian commits exact chained transaction → durable journal consumes
the bound commit → unchanged retention writer validates current policy/raw/links/
holds/generation and atomic ledger CAS → append/trim eligibility. Local fixtures
exercise the actual coordinator hook, including failed CAS leaving consumed
authority after restart. This does not deploy an archive adapter/resolver.

Protected/unknown evidence never reaches trim eligibility. Active/terminal
pilot/recovery, Owner authority and unreplaced custody remain indefinite HOLD;
security incident hold is indefinite until a separately authorized release model
(currently deferred). Owner minimum periods remain compliance 365, business 180,
operational 90 days only after verified custody/no hold. Existing stricter 365-day
mixed source default remains unchanged. Category expiry never grants deletion.
The original 50 DB1/Memory functions, 67 call sites, 22 file dispositions and
RCA18A4 three local authority writers remain inventoried. New journal/control
writers have a separate exact static census and no production mount.

## Gate A — production identity provisioning acceptance preparation

HOLD_NOT_PREPARED; requirements only. No approval, credentials or identities.
Owner must choose issuer/enrollment/Owner bridge and exact three principals,
three credential-controller bindings, audiences, public key pins, lifetimes,
rotation/revocation and service IAM rights. Acceptance, if separately authorized,
must prove stable authenticated identity, key-subject separation, wrong issuer/
aud/type/key/subject/capability denial, self-verification denial, receipt replay
across restart, and that existing business tokens/session flags cannot impersonate.
Expected later writes: selected identity provider's specifically enumerated
three enrollments/credential records and audit entries only, still UNBOUND until
that provider is selected. Backend resources, archive/Redis/business writes and
deploy are excluded. Rollback must revoke scoped credentials and preserve
issuance/authority audit custody; never delete committed transaction history.

## Gate B — real archive/journal backend acceptance preparation

HOLD_NOT_PREPARED; requirements only, separate from identity issuance. Owner
must bind existing/proposed backend IDs, region, resource/key namespaces,
cost/budget, IAM identities and isolated synthetic acceptance prefix. Do not
provision or connect until a separate exact authorization. Production evidence
upload, migration, trim and activation are excluded from backend acceptance.

S3 requirements: versioning enabled; Object Lock enabled and verified before any
acceptance upload; recommend COMPLIANCE mode for independently verified minimum
periods (90/180/365 or stricter); protected/unknown legal hold ON, indefinite;
no general hold-release/bypass/delete permission. Approval must bind actual
bucket/region/ownership, HTTPS-only bucket policy, bucket owner enforced access,
SSE-KMS key and separate create/read/checksum/retention IAM scopes. Object creation
uses conditional `If-None-Match: *`; duplicates fail, without automatic retry.
Object Lock alone does not prohibit creating a new version, so conditional
no-overwrite enforcement and exact VersionId pinning are both mandatory.
See [S3 conditional writes](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html)
and [PutObject](https://docs.aws.amazon.com/AmazonS3/latest/API/API_PutObject.html).

Proposed key layout: `agent-hub/custody/v1/<policy-id>/<category>/<ledger-id>/<raw-sha256>/raw.bin`,
linked objects and create-only manifest/receipt under the same scoped prefix.
Metadata binds source ID, raw/linked SHA-256, bytes, observed UTC, category,
policy/version, custody transaction and retention-until. Bind returned VersionId,
checksum and object retention/legal-hold response; ETag is not a raw SHA-256.
Independent verifier uses version-specific GET and recomputes raw/linked digests,
checks exact retention/legal hold, encryption and manifest. No lifecycle deletion
or automatic expiration of protected/unknown or journal/control custody.

Future acceptance matrix: create-only put, duplicate rejection, lock/version
proof, independent readback/checksum, permission denial, outage, concurrent
archive single winner, immutable exact versions, export/restore plus attested
latest journal checkpoint. Expected writes are isolated synthetic acceptance
objects and journal fixtures only, exact counts/namespace must be approved later.
Failure/ambiguous ACK: HOLD, no trim and no retry. Recovery/export reads exact
VersionIds and journal checkpoint into independently verified custody; preserve
all consumed transaction/JTI facts. No archive deletion or production rollback
is authorized by preparation.

Migration/rollback preparation: new journal starts explicitly, never on missing
read; existing active/terminal receipt and consumed history require verified
archive/import/anchor before authority. Existing 5000 capped DB1 ledger is not
migrated by this task. Pending unknown writers and absent live inventory block
activation. Source rollback is discard/revert the child commit; there is no
production state to recover. A later backend rollback must preserve consumed
authority and fail closed on checkpoint/history disagreement.

Primary technical references, verified during preparation:
[SQLite transactions](https://www.sqlite.org/lang_transaction.html),
[SQLite synchronous](https://www.sqlite.org/pragma.html#pragma_synchronous),
[PostgreSQL isolation](https://www.postgresql.org/docs/current/transaction-iso.html),
[Redis persistence](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/),
[S3 Object Lock](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html).

NEXT_SAFE_ACTION: OWNER REVIEW + SEPARATE IDENTITY PROVISIONING PREPARATION +
SEPARATE REAL BACKEND ACCEPTANCE PREPARATION. No provisioning/deploy/activation.
