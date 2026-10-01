# Agent Hub Phase-9 one-delivery new-lineage proposal

Date: 2026-10-01
Source baseline: `a417b7caea23f4e886ba3b4100e18d8adec1c679`
Disposition: `ADOPTED_FOR_SOURCE_ONLY_IMPLEMENTATION`
Production authority: `NOT_GRANTED`
R5: `NOT_CREATED`

## Decision and boundary

The historical R4 manifest, runner and helper bytes are not recoverable from
the accessible authoritative sources recorded in the 2026-09-30 recovery
handoff. Their digests cannot reconstruct those sources, and the generic
RCA05/RCA06 limited-pilot modules are not equivalent one-delivery runners.

The repository policy permits source, test, documentation and package-design
preparation before a production Owner gate. It therefore permits a replacement
to be designed under a new lineage, but it does not permit that replacement to
be represented as R4, as a byte-equivalent recovery, as R5, or as executable
production authority. Historical R4 approval, operation identity and window
remain terminal and non-reusable.

This proposal uses lineage `AH_P9_ONE_DELIVERY_NEW_LINEAGE_V1` and operation
family `AH-P9-ONE-DELIVERY-NL1-<canonical UUIDv4>`. It is deliberately a new
contract. The Owner adopted this replacement for continued source-only
implementation by replying `Xác nhận đồng ý` at 2026-10-01T07:48:36Z to the
explicit proposal. That decision is not production execution approval. Any
later production operation still requires a complete fresh production-capable
package, fresh JIT evidence, a new window and a separate exact Owner execution
gate.

## Offline milestone implemented

`scripts/ops/agent_hub_phase9/one_delivery_new_lineage.py` provides only:

- strict package inventory, path, duplicate-JSON, length and SHA-256 checks;
- explicit rejection of the historical R4 identity and all RCA pilot families;
- required new-lineage bindings for the current one-delivery envelope, server
  allowlist, candidate/rollback images, preflight, recovery, campaign digest
  evidence and readback contract;
- preservation of raw HTTP-byte and semantic-model digest domains;
- exactly one event, attempt `1/1`, no retry and no failure fallback;
- an operation-bound, atomic exclusive claim plus local fixture journal in a
  derived evidence directory; these are offline evidence semantics, not a
  claim of production durability;
- an atomic one-observation claim, so the evaluator has no retry path;
- fail-closed `POST_OUTCOME_AMBIGUOUS_HOLD_OWNER_REVIEW` after any invalid or
  uncertain post-observation fixture result, preserving the original cause
  even when final journal persistence also fails, with no automatic retry or
  automatic rollback. The HOLD boundary begins at function entry for an
  already-observed result, including observation-claim write/collision,
  crash re-entry, package reverify and evidence-store re-resolution failures;
- exact readback deltas for the touchpoint, source-event match, receipt,
  two retained Campaign audit events, no dead letter, signed receipt validity
  and the existing 2,000-record internal audit capacity. Snapshot evidence must
  explicitly be exact and uncapped; boundary tests cover 1,998/1,999/2,000.

The module contains no SSH, SCP, Docker, Redis, HTTP client, subprocess or
provider implementation. It has no transport or callback entry point and never
performs a POST. It only evaluates caller-supplied local fixture response,
receipt, canonical receipt-verification and exact store snapshots. Receipt
fields are schema-bound and its HMAC is independently recomputed with a local
verification key; a true boolean alone is insufficient. It cannot claim,
stage, load an image, deploy, contact production or create an R5 operation.

The package's `body_exported`/related privacy flags are validated as structural
contract fields only. They are not treated as independent proof that source
bytes are secret-free; the changed-file pattern scan is reported separately.

The integration test binds its readback contract to the existing
`phase9_delivery` fence, `Phase9InternalDeliveryBinding`, atomic internal store,
receipt verification and Campaign audit lane. This reuses current product
contracts rather than inventing another write path. It reads exact in-memory
cardinalities directly for this local test and does not infer a count from the
store's 1,000-row list view.

## Adopted source-only builder and rehearsal milestone

The adopted source milestone adds:

- `one_delivery_new_lineage_builder.py`, which writes an exact-allowlist,
  deterministic review package into a unique local staging directory,
  self-verifies every artifact/hash/binding, atomically publishes only to a
  non-existing destination, and refuses historical identities or overwrite;
- `one_delivery_new_lineage_rehearsal.py`, a closed in-process rehearsal with
  no injected transport/callback, network, subprocess or production action;
- terminal PASS/HOLD journal verification bound to the operation, manifest,
  claim and observation claim; PASS also requires a schema/invariant/digest-
  bound `result.json`, including tamper detection; and
- an end-to-end local path from built package through exact pre-observation
  checks, one synthetic signed receipt/readback observation and terminal
  evidence. A raw/semantic ambiguity fixture reaches Owner HOLD with zero
  module POSTs, no retry and no automatic rollback.

These artifacts remain offline review tools. They do not implement or claim a
sealed concrete SSH transport, remote JIT collector, production claim/stage
executor or evidence-bound production recovery executor.

## Read-only evidence contract milestone

`one_delivery_new_lineage_readonly_evidence.py` now defines the v2 exact intake
contract for a future fresh JIT observation without implementing any transport.
It binds a new operation, candidate HEAD, exact transport-profile hash,
collector-bytes hash, pinned-target hash, protected-service anchor and exact
candidate/rollback OCI plus custody identities into one authorization-intent
digest. A structural scope fixture must bind that entire intent plus repeated
transport/collector/target hashes. The final request adds the scope digest,
avoiding a circular request/scope hash without leaving request fields unbound.
The capture and raw evidence bind those identities again. Same-operation
transport, collector, target or payload substitution fails closed.

The current scope receipt is deliberately
`STRUCTURAL_FIXTURE_ONLY`. A synthetic dictionary cannot claim or verify human
Owner approval and the module cannot generate real approval. Production
collection remains blocked until a separate trusted verifier supplies a
genuine human-approval source; no such source is inferred from these tests.
The module then verifies raw capture bytes, exit/UUID/timestamps, protected 18,
the healthy `phase9_creation` target, claim/stage/delivery absence, OCI/custody
verification, and only the four server-enforced DB0 `EVAL_RO` aggregates.

Any raw key/value/credential/job-payload export, `EVAL` fallback, nonzero
queue/processing/in-flight counter, protected/candidate/rollback drift,
non-UTC or misordered timestamps, any capture outside the scope window, a
future completion, a whole-capture age over 600 seconds, or any
write/claim/stage/load/delivery flag fails closed. Zero clock skew is allowed.
Its offline fixture PASS is
`READONLY_EVIDENCE_STRUCTURAL_FIXTURE_VERIFIED_EXECUTION_NOT_AUTHORIZED`;
evidence-only and execution authority both remain `NOT_GRANTED`. The module
contains no SSH, subprocess, socket, HTTP, Redis or other live-access surface.
The dependency and minimum-scope inventory is recorded in
`docs/AH_P9_ONE_DELIVERY_NEW_LINEAGE_READONLY_EVIDENCE_PLAN_20261001.md`.

## Explicit evidence gap

The historical package used Video Factory DB0 counters as a safety input. This
Agent Hub-only task did not query or modify Video Factory. The offline preflight
contract records:

`video_factory_db0_counter_evidence = OUT_OF_SCOPE_NOT_COLLECTED`

and therefore:

`production_qualification = BLOCKED_EXTERNAL_READONLY_EVIDENCE_REQUIRED`.

A later review must either retain that dependency and supply independently
authorized read-only evidence, or approve a source change proving it is not a
required Agent Hub invariant. This proposal does neither.

## Completion criteria for a production-review candidate

The offline milestone is complete when its focused tests, complete Phase-9 ops
suite, Agent Hub regression and evaluator pass locally. Promotion beyond this
milestone requires all of the following, in order:

1. **Satisfied for source-only work:** Owner selected this new-lineage
   replacement instead of requiring the exact non-secret R4 archive/builder.
2. A reviewed production transport, remote preflight/JIT collector, claim and
   staging contract, recovery program, terminal verifier and deterministic
   package builder are implemented under the new lineage. None may import an
   RCA family identity or claim historical equivalence.
3. Pre-POST failures remain abort-before-POST; post-POST uncertainty remains
   `HOLD_OWNER_REVIEW`. Any rollback after a possible business write must be an
   explicit evidence-driven decision, never an automatic retry/rollback.
4. Candidate and rollback image identities, current Agent Hub-only protected
   baseline, exact delivery/allowlist, receipt/readback indexes, capacity,
   source HEAD and every executable/recovery byte are sealed together.
5. Full negative/tamper/failure tests, Agent Hub regression, evaluator and new
   exact-head CI pass for the changed source.
6. A fresh read-only rehearsal uses the same sealed collector intended for the
   future claim and proves no claim, stage, load, deploy, delivery or DB1 write.
7. Only then may a new package version be named, a fresh operation/window be
   proposed and an exact Owner execution approval be requested.

No old R4 consent, record, window, token, operation or rehearsal receipt may be
copied into the new lineage as authority.

## Decision status and next genuine gate

The minimum design choice is satisfied: new lineage was selected. Historical
R4 approval remains expired and non-reusable; the new decision cannot create
R5 or authorize execution.

The next source milestone remains one agreed four-component scope: (1) the
transport-profile verifier, deterministic strict-argv renderer and rendered
read-only collector; (2) the claim/stage state machine; (3) the recovery
boundary; and (4) the production-review builder. It is on hold until
independent review confirms both High findings in the prior read-only contract
are closed by source commit
`e2339d4debb6e6736beb8b94a23cf01931055a96`. Promotion remains HOLD until a
bounded scope from a separately verified human-approval source can bind fresh
protected services, current candidate/rollback artifacts, custody and the four
retained Video Factory DB0 safety aggregates. Only after those source bytes,
bindings and exact-head CI are reviewed may a fresh execution package/window
and separate Owner execution gate be requested.

Phase 9 remains open with four acceptance outcomes remaining, Phase 10 remains
`NO-GO`, and production writes, provider calls, customer actions and Video
Factory actions remain zero.
