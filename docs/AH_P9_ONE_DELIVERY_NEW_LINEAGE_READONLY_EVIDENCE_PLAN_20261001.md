# Agent Hub Phase-9 new-lineage read-only evidence plan

Date: 2026-10-01
Lineage: `AH_P9_ONE_DELIVERY_NEW_LINEAGE_V1`
Disposition: `RUNTIME_PATH_TWO_HIGH_REMEDIATED_REVIEW_PENDING_LIVE_EVIDENCE_NOT_COLLECTED`
Production execution authority: `NOT_GRANTED`

## Current status

The deterministic offline package/rehearsal milestone remains valid. The next
source-only milestone adds
`one_delivery_new_lineage_readonly_evidence.py`, a pure verifier for a future
fresh read-only collection. It has no SSH, subprocess, socket, HTTP, Redis,
credential, claim, stage, image-load, delivery or recovery entry point.

The v2 verifier binds all four inputs separately:

1. a deterministic authorization-intent payload tied to the new operation,
   candidate HEAD, exact transport-profile hash, collector-bytes hash, pinned
   target hash and exact candidate/rollback OCI and custody identities;
2. a narrow structural fixture bound to the complete authorization-intent
   digest and repeated transport/collector/target hashes for exactly four DB0
   aggregate counters;
3. a transport capture receipt with invocation UUID, raw stdout/stderr hashes
   and lengths, exact request/profile/source hashes and zero child exit; and
4. the strict raw JSON evidence bytes themselves.

Offline passing status is
`READONLY_EVIDENCE_STRUCTURAL_FIXTURE_VERIFIED_EXECUTION_NOT_AUTHORIZED`.
The dictionary fixture is explicitly `STRUCTURAL_FIXTURE_ONLY`; it cannot
certify that a human Owner approved anything or mint read-only authority. A
genuine future evidence collection requires a separately trusted verifier for
the human-approval source. This module intentionally does not implement or
generate that approval. It cannot create an operation claim, stage/load an
image, perform a delivery, authorize recovery or turn evidence-only consent
into execution consent.

The intent digest avoids a circular request/scope hash: it contains every
request field except the later scope-receipt digest and its fixture-only
classification. The final request binds both digests. The capture and raw
evidence repeat/bind the intent, request, transport, collector and pinned
target identities. Reusing one scope with a different transport, collector,
target or request payload fails closed even when the operation ID is unchanged.

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
| Capture freshness | `scope_start <= started <= observed <= completed <= scope_end`, `completed <= now`, UTC-only timestamps, zero future skew, and the entire capture no more than 600 seconds old at verification | Not collected. |
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
access, a later collection needs one bounded evidence-only dossier plus a
separately verified human-approval source. A caller-created dictionary is not
that source. The future trusted scope may combine the Agent Hub read and the
indispensable DB0 exception, but it must say all of the following explicitly:

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

1. a new-lineage transport-profile verifier, deterministic strict-argv
   renderer and rendered read-only collector whose source hash is sealed and
   whose only output matches this evidence contract;
2. a pure durable claim/stage state machine for `PREFLIGHT -> CLAIMED -> STAGED ->
   PRE_POST_INTENT -> POST_OBSERVED -> PASS/HOLD`, with one attempt and no retry;
3. candidate stage verification, pre-POST recovery transitions and post-
   observation HOLD/Owner-review plans that cannot run automatically; and
4. a production-review builder that seals the executable, recovery, image,
   custody, JIT, window and approval-source bindings without granting access or
   execution.

Live target values are needed only to instantiate and seal the final profile,
candidate, rollback and custody manifests, run the JIT collection, and create a
production-review package. A separate exact Owner execution gate is required
after source review, package review and exact-head CI.

## Next safe action

Independent review confirmed both High findings closed at
`e2339d4debb6e6736beb8b94a23cf01931055a96`. The follow-on transport,
collector, offline state-machine, recovery boundary and production-review
builder milestone was initially implemented at `2faa60c`, whose independent
review found two additional High issues: Windows junction/reparse sandbox
escapes and unobserved/fabricated target safety facts. Both are remediated in
exact tested source commit `09beb25e1d35a24a87c1671cca00b6218652c890`.

The executor now fails closed on symlink, junction or reparse components and
uses exclusive owned-directory creation plus identity revalidation. Real
Windows junction tests cover root, operation and recovery paths with no outside
writes. The collector now requires and binds observed whitelisted Docker
inspect labels/environment for Compose identity, runtime mode, scheduler and
external-write state. Unsafe or missing metadata fails closed, and mock-inspect
tests exercise both the source helper and parser extracted from the rendered
collector. The generated collector and strict argv remain sealed and unexecuted;
real entry points still refuse execution.

Independently review exact source commit `09beb25`. If both High findings are
confirmed closed, publish that exact commit for exact-head CI. Do not request or
spend the bounded 600-second evidence-only read
scope until current candidate/rollback OCI and custody bytes plus a trusted
human-approval verification path exist. The later production transport driver,
capture wrapper and claim/stage/load/delivery/recovery executors require their
own source/package review. Keep R5 uncreated, keep the execution gate separate,
keep Phase 9 open with four outcomes remaining and keep Phase 10 `NO-GO`.
