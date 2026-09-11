# NPD Agent Hub and Video Factory handoff

## Purpose

This is the canonical repository-level handoff for the Agent Hub and Video
Factory workstreams in `vangnguyen/npd-ai-video-factory`. The two workstreams
share this repository but retain separate runtime, approval, evidence, and
production-mutation boundaries.

The structured companion is [`handoff.json`](handoff.json). Detailed historical
and architectural context remains in:

- [`docs/NPD_UNIFIED_SALEHUB_AGENTHUB_FULL_HANDOFF.md`](docs/NPD_UNIFIED_SALEHUB_AGENTHUB_FULL_HANDOFF.md)
- [`docs/technical-handoff.md`](docs/technical-handoff.md)

## Required operating protocol

After every task or milestone:

1. Update this file and `handoff.json` in the applicable repository.
2. Return a `HANDOFF RECEIPT` directly in the final response.
3. Do not require the owner to download or attach these files on every turn.
4. Request full evidence only when review is required, a hash/scope mismatch is
   found, or a production write, paid-provider call, merge, release, RC gate, or
   deep audit is being prepared.
5. Record `NEXT_SAFE_ACTION`, then stop. Do not execute it without a subsequent
   user task or a separately required owner gate.

The response receipt uses these fields exactly:

```text
WORKSTREAM:
TASK:
VERDICT: PASS / BLOCKED / REVIEW_REQUIRED
REPO:
BRANCH:
HEAD SHA:
PR:
TESTS:
CI:
PRODUCTION WRITES:
REAL PROVIDER CALLS:
ACTUAL COST:
HANDOFF UPDATED: YES/NO
HANDOFF SHA-256:
EVIDENCE POINTER:
SCOPE DRIFT: PASS/FAIL
BLOCKERS:
NEXT_SAFE_ACTION:
```

## Current workstream state

### Agent Hub

- Source baseline recorded for the current Phase 9 pilot package:
  `43a1cca354d12893ee33b6e43cd9117794f78e04`.
- Approved operation:
  `PHASE9-LIMITED-PILOT-FRESH-V2-20260911-d55d6333-c18f-4069-91bb-00ebee26abb5`.
- Terminal state of the approved operation:
  `LIMITED_PHASE9_PILOT_ABORTED`.
- Approved operator-controlled window: 20:00-22:00 ICT on 11 September
  2026; local dispatcher must start before 20:05 ICT and target mutation must
  start before 20:20 ICT.
- Scope of the approved mutation is only
  `npd-agent-hub-prod/agent-hub`. No scheduler, automation, Run Now, second
  claim, or whole-stack Compose action is authorized.
- Phase 10 and AH-R01 are not authorized. AH-03 and AH-04 remain NO-GO.
- The sealed dispatcher started at `20:00:19.4406767 ICT` and its remote
  read-only preflight invocation failed closed with
  `REMOTE_PREFLIGHT_FAILED_e3b0c44298fc1c14`. No final preflight receipt,
  local/remote claim, candidate staging, target mutation, deployment, UAT, or
  rollback occurred. The operation must not be retried or reused.

### Video Factory

- No Video Factory code, runtime, provider, publishing, or production action was
  performed in this documentation milestone.
- Video Factory remains an independently gated workstream even though it shares
  this repository with Agent Hub.
- Before any future Video Factory action, revalidate its current branch/RC,
  provider authority, CI provenance, production state, and the relevant owner
  gate. Historical health or handoff evidence is not current execution authority.

## Shared safety boundaries

- Never store or disclose plaintext credentials, confirmation tokens, cookies,
  API keys, or recovery material in this handoff.
- Green CI, a mergeable PR, a sealed package, or a recorded approval is not by
  itself authority for a production write or paid-provider call.
- Hash, time, operator, scope, topology, backup, or approval drift fails closed.
- A task that only prepares evidence must report zero production writes and zero
  real-provider calls.

## Evidence pointers

- Phase 9 Fresh V2 immutable package:
  `outputs/agent-hub-phase9-limited-pilot-fresh-v2-gate-20260910-d55d6333`
- Phase 9 Fresh V2 owner approval record:
  `outputs/agent-hub-phase9-limited-pilot-fresh-v2-owner-approval-20260911-d55d6333`
- Detailed Agent Hub/SaleHub architecture and governance:
  `docs/NPD_UNIFIED_SALEHUB_AGENTHUB_FULL_HANDOFF.md`
- Video Factory technical history:
  `docs/technical-handoff.md`

## Latest milestone

- Task: execute the exact approved Limited Phase 9 Pilot Fresh V2 operation.
- Result: terminal fail-closed abort during the first remote read-only preflight,
  before claim, staging, or target mutation.
- Production writes: none.
- Real provider calls: none.
- Next safe action: wait for a separate owner task authorizing read-only RCA of
  the remote preflight failure. Do not retry this operation or infer authority
  to create a replacement gate.
