# Agent Hub Phase-9 new-lineage read-only evidence plan

Date: 2026-10-01  
Lineage: `AH_P9_ONE_DELIVERY_NEW_LINEAGE_V1`  
Disposition: `SOURCE_CONTRACT_PASS_LIVE_EVIDENCE_NOT_COLLECTED`  
Production execution authority: `NOT_GRANTED`

## Current status

The deterministic offline package/rehearsal milestone remains valid. The next
source-only milestone adds
`one_delivery_new_lineage_readonly_evidence.py`, a pure verifier for a future
fresh read-only collection. It has no SSH, subprocess, socket, HTTP, Redis,
credential, claim, stage, image-load, delivery or recovery entry point.

The verifier binds all four inputs separately:

1. a deterministic request tied to the new operation, candidate HEAD,
   transport profile, collector source and exact candidate/rollback OCI and
   custody identities;
2. a fresh, narrow Owner evidence-only scope receipt for exactly four DB0
   aggregate counters;
3. a transport capture receipt with invocation UUID, raw stdout/stderr hashes
   and lengths, exact request/profile/source hashes and zero child exit; and
4. the strict raw JSON evidence bytes themselves.

Passing status is
`READONLY_EVIDENCE_VERIFIED_EXECUTION_NOT_AUTHORIZED`. It cannot create an
operation claim, stage/load an image, perform a delivery, authorize recovery
or turn evidence-only consent into execution consent.

## Exact missing evidence

| Dependency | Exact fresh evidence required | Current usable state |
|---|---|---|
| Pinned transport | Exact SSH executable, SCP executable, keygen, identity and known-hosts file hashes; host fingerprint; target; strict no-fallback argv; collector source hash and raw capture receipt | The 2026-09-30 handoff reports pinned read-only PASS, but its volatile files/receipt are not in the new-lineage package. No current connector or SSH action was used in this task. |
| Agent Hub protected baseline | Sanitized current target identity/signature; project `npd-agent-hub-prod`; service `agent-hub`; healthy/ready; restart count zero; exactly 18 protected services matching the reviewed canonical digest; runtime `phase9_creation`; scheduler/external writes false | Digest `ada185efdf1398bd4053d1301882b18f1bdf439f2f649b6396900296a73caac6` is a dated reported comparison anchor only. It is not treated as a current receipt. |
| Absence preconditions | Exact new operation claim absent; new-lineage attempt/stage absent; candidate not loaded; exact delivery/source event/receipt absent | Not collected for a new operation. Historical R4/RCA claims and identities are non-reusable. |
| Candidate | Reviewed application source HEAD; local OCI archive SHA/size; linux/amd64 index, manifest and config digests; revision binding; exact delivery binding; custody-manifest digest; archive verification; not staged/loaded | Offline tests use synthetic hashes. No production candidate archive or OCI identity is claimed. |
| Rollback | Current running target config identity; retained rollback OCI archive SHA/size/index/manifest/config; custody-manifest digest; archive verification; image present and exact current target | Historical R4 rollback source is unknown. Older RCA/phase5 image IDs are provenance only and cannot be selected as the new rollback binding without a fresh match. |
| Custody | Exact candidate and rollback custody manifests; raw transport capture custody; no public secret/key material; retained source/hash provenance; a recoverable evidence location; no overwrite | Only the local source/test receipt is current. Production artifact custody has not been established for this lineage. Portable V1 Copy 2 is not a Phase-9 prerequisite and is not silently added here. |
| Video Factory DB0 safety aggregates | One server-enforced `EVAL_RO` on DB0 returning only `video_factory_job_count`, `video_factory_queue_count`, `video_factory_processing_count`, and `video_factory_in_flight_count`; queue/processing/in-flight exactly zero; raw keys/values/credentials/job payloads not emitted | `OUT_OF_SCOPE_NOT_COLLECTED`. Older `12/0/0/0` observations are expired and are not reused. |
| Capture freshness | Observation and raw capture inside the exact evidence-only scope window and no more than 600 seconds old at verification | Not collected. |
| Exact-head review | Review of every collector/transport/runtime/recovery byte, full tamper suite, Agent Hub regression, evaluator and exact-head CI | Local tests pass on the unpublished source commit; exact-head CI is not available and not inferred. |

## Existing collector inventory

The repository contains useful source patterns, but none is current authority:

- `remote_preflight_capture.invoke_preflight` already persists raw stream
  lengths/hashes, exit, timeout, UUID and sanitized context before
  interpretation. Its capture pattern can be adopted after removing historical
  package/identity coupling.
- `pilot_transport.strict_argv` demonstrates Windows OpenSSH strict host-key
  checking and no fallback. It is hard-bound to the historical target/profile
  and cannot be imported as new-lineage authority.
- `runtime_template.py` contains the established protected-service observation
  and an `EVAL_RO` DB0 aggregate probe. That runtime belongs to an RCA pilot,
  combines broader historical bindings and must not be executed or relabeled
  as the new collector.
- `gate_bindings.verify_snapshot` demonstrates the prior 600-second freshness,
  exact four-counter, capture and custody checks. Its RCA operation schemas and
  package identities remain historical.

The historical target recorded by those sources is pinned root SSH to
`157.10.201.169:22`, followed by the redacted remote shape
`python3 -B - readonly-evidence <redacted canonical request>`. The exact new
transport profile, file hashes and fingerprint must be freshly sealed before
use; this document does not authorize that target or command.

The DB0 command scope is narrower: from the Agent Hub container's configured
Redis endpoint, select DB0 and run one atomic `EVAL_RO` using only SCAN, GET and
LLEN internally. There is no `EVAL` fallback. Only the four integer aggregates
and sanitized metadata may leave the host. No Video Factory API, workflow,
provider, configuration or job action is in scope.

## Minimum read-only Owner scope

Because the current assignment explicitly forbids remote SSH and Video Factory
access, a later collection needs one bounded evidence-only dossier. It may
combine the Agent Hub read and the indispensable DB0 exception, but it must say
all of the following explicitly:

- one named new-lineage operation and exact request/collector/transport hashes;
- one short UTC evidence window;
- pinned read-only access to the exact Agent Hub host only;
- exactly the four named DB0 aggregates through server-enforced `EVAL_RO`;
- no raw Redis keys, values, credentials or job payloads leave the host;
- no claim, stage, SCP, image load, deploy, delivery POST, retry, rollback,
  provider/customer action, scheduler action or Video Factory workstream;
- production and Video Factory writes both zero; and
- Agent Hub execution approval remains `NOT_GRANTED`.

This is an evidence-only scope, not the later execution gate. If a connected,
already authorized read-only collector becomes available, it may satisfy the
same exact receipt contract; no such connector is available in the current
context.

## Source work that does not need live bindings

After review of this milestone, the following can still be implemented and
tested offline without claiming any current production fact:

1. a new-lineage transport-profile verifier and deterministic strict-argv
   renderer with no historical operation IDs;
2. a rendered read-only remote collector whose source hash is sealed and whose
   only output matches this evidence contract;
3. a pure durable state machine for `PREFLIGHT -> CLAIMED -> STAGED ->
   PRE_POST_INTENT -> POST_OBSERVED -> PASS/HOLD`, with one attempt and no retry;
4. candidate stage verification and pre-POST recovery transitions against
   synthetic filesystem/OCI fixtures; and
5. post-observation HOLD/Owner-review recovery plans that cannot run
   automatically.

Live target values are needed only to instantiate and seal the final profile,
candidate, rollback and custody manifests, run the JIT collection, and create a
production-review package. A separate exact Owner execution gate is required
after source review, package review and exact-head CI.

## Next safe action

Review the new evidence contract. In parallel, continue the offline transport
profile/collector/state-machine implementation. Request the bounded read-only
scope only when the candidate and rollback OCI/custody identities are ready, so
the 600-second JIT evidence is not collected prematurely. Keep R5 uncreated,
Phase 9 open with four outcomes remaining and Phase 10 `NO-GO`.
