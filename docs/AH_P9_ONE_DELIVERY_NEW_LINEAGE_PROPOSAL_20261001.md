# Agent Hub Phase-9 one-delivery new-lineage proposal

Date: 2026-10-01
Source baseline: `a417b7caea23f4e886ba3b4100e18d8adec1c679`
Disposition: `OFFLINE_CONTRACT_IMPLEMENTED_REVIEW_REQUIRED`
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
contract. Adoption requires an Owner decision after review; any later
production operation also requires a complete fresh package, fresh JIT
evidence, a new window and a separate exact Owner execution gate.

## Offline milestone implemented

`scripts/ops/agent_hub_phase9/one_delivery_new_lineage.py` provides only:

- strict package inventory, path, duplicate-JSON, length and SHA-256 checks;
- explicit rejection of the historical R4 identity and all RCA pilot families;
- required new-lineage bindings for the current one-delivery envelope, server
  allowlist, candidate/rollback images, preflight, recovery, campaign digest
  evidence and readback contract;
- preservation of raw HTTP-byte and semantic-model digest domains;
- exactly one event, attempt `1/1`, no retry and no failure fallback;
- a durable local pre-POST intent journal for offline simulation;
- fail-closed `POST_OUTCOME_AMBIGUOUS_HOLD` after any uncertain POST outcome,
  with no automatic retry or automatic rollback;
- exact readback deltas for the touchpoint, source-event match, receipt,
  two retained Campaign audit events, no dead letter, signed receipt validity
  and the existing 2,000-record internal audit capacity.

The module contains no SSH, SCP, Docker, Redis, HTTP client, subprocess or
provider implementation. Its simulation entry accepts only an explicitly
marked in-process fake transport. It cannot claim, stage, load an image,
deploy, contact production or create an R5 operation.

The integration test binds its readback contract to the existing
`phase9_delivery` fence, `Phase9InternalDeliveryBinding`, atomic internal store,
receipt verification and Campaign audit lane. This reuses current product
contracts rather than inventing another write path.

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

1. Owner selects this new-lineage replacement instead of supplying the exact
   non-secret R4 archive/builder.
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

## Minimum Owner decision

Choose exactly one:

- **Adopt new lineage:** accept `AH_P9_ONE_DELIVERY_NEW_LINEAGE_V1` as the
  replacement design, including one attempt only and
  `POST_OUTCOME_AMBIGUOUS_HOLD` with no automatic rollback, and authorize
  continued source-only implementation of the missing production-review
  components. This is not execution approval.
- **Require historical recovery:** do not adopt the replacement; provide an
  accessible non-secret R4 archive or sealed deterministic builder matching
  the recorded manifest/runner/helper digests. Historical approval still
  remains expired and non-reusable.

Until that choice and later gates, Phase 9 remains open with four acceptance
outcomes remaining, Phase 10 remains `NO-GO`, and production writes, provider
calls, customer actions and Video Factory actions remain zero.
