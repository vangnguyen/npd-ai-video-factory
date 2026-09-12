# AH-P9-RCA-04 — Fresh Evidence & Dispatcher Reseal

Verdict: **BLOCKED**. Fresh pilot gate: **HOLD_NOT_PREPARED**.

The Owner's current request accepts the observed protected-service drift and
fresh capture substitution for preparation/reseal only. It grants no execution,
claim, staging, deployment, scheduler, provider or other production authority.
The task stops at the incomplete full execution snapshot. No execution gate,
operation ID or confirmation token was created.

Starting candidate: `fd33418fd8e5b83b6326cc2a80bcbefce5ea58ac`, branch
`fix/agent-hub-p9-preflight-capture-20260912`, repository
`vangnguyen/npd-ai-video-factory`. The accepted canonical protected-service digest
is `6e0167343174e4cb719b3799015dc5d438b8cdcc545774dc72d53f61cf2c648e`.
Owner disposition receipt SHA-256:
`5119b51224d70bfb553f0c5a10727e1b9c8e1cd55ec8cdbdccc063641ef6cb8c`.
The receipt binds the exact starting candidate, previous handoff and current
request's attachment hash. Acceptance does not extend to additional unreviewed
runtime drift.

## Evidence obtained

1. A fresh read-only protected baseline verifies 18 services, the accepted
   digest, healthy/ready Agent Hub, unchanged target/configuration, exact Compose
   version and absence of operation claim/attempt metadata. SSH uses the same
   pinned host fingerprint and rehashed trusted binaries/known-hosts file;
   there is no host-check fallback or known-hosts mutation.
2. A fresh Agent Hub namespace export performs only SCAN, TYPE, GET, LRANGE,
   ZRANGE and PTTL. Repeated scans/value hashes/expiry checks establish source
   consistency. It contains 10,692 keys: 10,375 strings, 302 lists and 15 zsets.
   The exact running rollback image is also freshly exported read-only.
   Both streams are AES-256-GCM encrypted before local storage with a fresh
   random key protected by CurrentUser Windows DPAPI. Cipher/plaintext hashes,
   byte lengths, stdout/stderr, exit and invocation UUID are preserved before
   result classification. No plaintext data or key is put in the review package.
3. The actual fresh backup is decrypted in memory and restored to a disposable
   local Redis fixture. Every value/type/absolute expiry matches: 10,692/10,692
   before and after a Redis process restart using its RAM-only RDB. The fixture
   uses a Unix socket, TCP port 0, network none, private tmpfs, no published
   ports, bind mounts or Docker volumes, and receives no production credentials.
   It starts no application/task consumers and is removed after verification.
   Production Redis receives no SAVE, BGSAVE, restore, restart or write.
   The fresh rollback archive's config identity, OCI manifest and layers also
   verify. This proves data restore and image integrity; application restore
   and browser UAT were not run and are not implied.
4. Fresh role configuration and read-only whoami validate Owner/operator/viewer
   3/3, one account in each allowlist, the established identity fingerprints,
   removed viewer absence and no external executor. Fresh Agent Hub namespace,
   task/report/action/execution/audit/cohort counters verify; namespace count
   matches the new backup and the cohort remains negotiation. No CRM, Sales Hub,
   customer system or Video Factory database/application request is performed.

The exact received transport streams are represented by lengths/hashes in
sanitized receipts; backup/image streams are additionally preserved encrypted
in private local custody. Fresh accepted read-only JSON is separately sealed.
Historical child stdout/exit/UUID remain **unavailable**. Fresh captures and
independent fixtures are never labeled recovered historical primary evidence.
`PROTECTED_SERVICE_DRIFT` remains the confirmed historical root cause.

## Why full snapshot and pilot reseal stop

The existing immutable pilot runtime's `safety()` requires Video Factory idle
checks, and its safety counter set includes:

- `video_factory_job_count`
- `video_factory_queue_count`
- `video_factory_processing_count`
- `video_factory_in_flight_count`

Those values require reading a separate Video Factory namespace in shared Redis
DB0. The current instruction is Agent Hub ONLY and prohibits touching Video
Factory V2/V3. This task did not access that namespace. Protected container
metadata and green Agent Hub counters do not prove queue/in-flight idleness.
Missing values were not assumed zero or imported from expired evidence. The
existing safety requirement was preserved rather than bypassed.

`FULL_EXECUTION_SNAPSHOT.json` is therefore `INCOMPLETE_FAIL_CLOSED`, not an
executable snapshot. Hardened capture has been adopted and verified for actual
fresh read-only collectors, with an explicit mandatory success verifier.
Pilot execution dispatcher/runner/runtime/rollback/finalizer/token/window/Owner
approval integration remains unverified. Its dependent package/payload/runner/
dispatcher/verifier hashes are **NOT_RESEALED**. Only the fresh evidence package
is sealed; its inventory/verifier/hash proves review integrity and grants no
execution authority. No old gate, approval, token or aborted operation is reused.

## Regression and collector disposition

Relevant local suites were rerun: capture 29/29, Agent Hub 299/299, mock business
eval 20/20, historical RCA 12/12, gate fixtures 31/31, transport fixtures 24/24
and extracted historical launcher/verifier reconstruction 2/2. Four fresh
independent remote fixtures verify stdout-only exit 2, empty stdout exit 0,
missing verifier and verifier mismatch all stop after stream/exit/UUID capture.
Fixture output containing `LIMITED_PHASE9_PILOT_PASS` is a local test result,
not a production pilot verdict. The old entrypoint/authorization is never run.

Rejected collector attempts are retained separately. Two archive checks failed
because an in-memory decrypted stream was not rewound before parsing. The first
unsupported OCI-only diagnosis was explicitly withdrawn. Another actual Redis
restore readback was rejected because Lua JSON rounded zset scores; direct
Redis score text converted to Python floats resolves it and the same fresh
backup then verifies all keys before/after restart. A role collector was rejected
for inserting an import before `__future__`; the corrected payload compiles
before dispatch and its accepted replacement alone feeds the evidence seal.
These defects do not establish backup corruption, runtime drift or mutation.

The final evidence bundle records secret/scope scan, all immutable historical
file hashes, manifest/inventory/tamper checks and actual GitHub CI for the exact
final documentation HEAD. CI must be queried after push; no result from the
starting candidate is reused as proof for a changed HEAD. The final commit
changes Agent Hub documentation/handoffs only and preserves all executable
trees and the Video Factory handoff sections. No merge or PR is performed.

## Blocker runbook and next safe action

Owner reviews a scope-compatible plan to obtain auditable fresh evidence for
the four missing idle counters. One option is an independently authorized
read-only collector outside this task supplying a sealed artifact; this task
does not authorize that work or perform it. Its evidence must bind timestamp,
exact Redis identity/reference hash and DB, protected baseline/target, explicit
scope, stdout/stderr hashes, integer exit, UUID, source/payload/verifier hashes,
the four actual integer values and zero queue/processing/in-flight counts.
Old counters, inferred zeroes and protected-service status are insufficient.
Any alternative equivalent safety proof needs review before changing the guard.

A separately assigned preparation task must then recheck exact candidate/main
CI and live target/config/protected drift, refresh all time-dependent evidence,
validate the independent counter artifact, complete the execution snapshot,
adopt hardened capture into a fresh pilot execution dispatcher with mandatory
full-binding verification, test all failure paths, and reseal every affected
execution dependency. Only internally consistent fresh evidence can prepare a
new limited pilot gate and proposed operation for Owner review. Application
restore limitations/custody/rollback/UAT requirements must remain explicit.

If that gate is eventually prepared, its next action is **OWNER REVIEW + EXPLICIT
EXECUTION APPROVAL**. This request provides neither execution approval nor an
execution window. Do not claim, stage, deploy, mutate production, schedule,
call providers, contact customers or open another workstream. Stop after RCA-04.

Evidence directory:
`C:/Users/VANG NGUYEN/Documents/Codex/2026-09-12/referenced-chatgpt-conversation-this-is-an-2/outputs/ah-p9-rca-04-20260912`.
The final HANDOFF RECEIPT and HASH_SUMMARY provide externally anchored hashes
without a self-referential handoff/commit cycle. Production writes, real
provider calls and actual cost are **0 / 0 / 0**.
