# NPD Agent Hub and Video Factory handoff

## Purpose

This is the canonical repository-level handoff for Agent Hub and its legacy
Video Factory integration in `vangnguyen/npd-ai-video-factory`. Active Video
Factory V2/V3 acceptance is maintained separately in
`vangnguyen/npd-video-factory-v2`; it has its own `HANDOFF.md` and
`handoff.json`. The workstreams retain separate runtime, approval, evidence,
and production-mutation boundaries.

The structured companion is [`handoff.json`](handoff.json). Detailed historical
and architectural context remains in:

- [`docs/NPD_UNIFIED_SALEHUB_AGENTHUB_FULL_HANDOFF.md`](docs/NPD_UNIFIED_SALEHUB_AGENTHUB_FULL_HANDOFF.md)
- [`docs/technical-handoff.md`](docs/technical-handoff.md)
- [`docs/AGENT_HUB_HANDOFF_AND_ROADMAP_20260911.md`](docs/AGENT_HUB_HANDOFF_AND_ROADMAP_20260911.md)

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
- Historical approved operation (terminal, window expired):
  `PHASE9-LIMITED-PILOT-FRESH-V2-20260911-d55d6333-c18f-4069-91bb-00ebee26abb5`.
- Terminal state of the approved operation:
  `LIMITED_PHASE9_PILOT_ABORTED`.
- Approved operator-controlled window: 20:00-22:00 ICT on 11 September
  2026; local dispatcher must start before 20:05 ICT and target mutation must
  start before 20:20 ICT.
- Historical scope of the expired approval was only
  `npd-agent-hub-prod/agent-hub`. No scheduler, automation, Run Now, second
  claim, or whole-stack Compose action is authorized.
- Phase 10 and AH-R01 are not authorized. AH-03 and AH-04 remain NO-GO.
- The sealed dispatcher started at `20:00:19.4406767 ICT` and its remote
  read-only preflight invocation failed closed with
  `REMOTE_PREFLIGHT_FAILED_e3b0c44298fc1c14`. No final preflight receipt,
  local/remote claim, candidate staging, target mutation, deployment, UAT, or
  rollback occurred. The operation must not be retried or reused.
- Read-only RCA `AH-P9-RCA-01` identified the underlying remote reason as
  `PROTECTED_SERVICE_DRIFT`: the protected SaleHub service
  `n8n-marketing-pricing-policy-sync-1` had been recreated before the pilot
  window, changing the protected-set digest from the sealed
  `dafe99c16a9f3059cb20d5d5e746c35ae5438668fe8155d5df034a87b02d9302`
  to `6e0167343174e4cb719b3799015dc5d438b8cdcc545774dc72d53f61cf2c648e`.
- The visible `e3b0c44298fc1c14` suffix is the empty-stderr SHA-256 prefix. The
  remote runtime wrote its sanitized failure reason to stdout, while the local
  launcher derived its error label from stderr and did not persist the child
  stdout, child return code, or generated invocation UUID. This capture gap
  makes the RCA disposition `REVIEW_REQUIRED` even though the causal chain is
  strongly identified.
- Repository binding is `VALID`: Agent Hub Phase 9 lives in this intentional
  Agent Hub/legacy Video Factory integration monorepo. No code was moved or
  copied between repositories during the RCA.
- Read-only follow-up `AH-P9-RCA-02` on 12 September revalidated the same
  protected digest, the same single changed service, unchanged Agent Hub target
  signature/config hashes, and absent claim/attempt/state/stage paths. A real
  strict-SSH sentinel independently reproduced child exit `2`, reason JSON on
  stdout and empty stderr. Observation remains `NOT_STARTED`.
- New branch `fix/agent-hub-p9-preflight-capture-20260912` contains a source-only
  capture library and 19 passing regression tests. The candidate atomically
  retains sanitized failure stdout, separate stream hashes/lengths, child return
  code and invocation UUID before raising a bounded reason. Wrapped transport
  timeouts/start failures also produce receipts. It has no execution authority
  and has not been adopted into a pilot dispatcher; the old sealed package is
  unchanged.
- Fresh gate preparation is `HOLD_EVIDENCE_INSUFFICIENT`: primary historical
  child stdout/return code/UUID remain unrecoverable, owner RCA/candidate review
  is pending, and a freshly sealed dispatcher, protected-set snapshot/change
  coordination and new bindings are required. No new operation, approval,
  confirmation token or window was prepared.
- Phase 9 UAT/business acceptance remains incomplete. Its completion precedes
  Sales SLA + Backup Copy 2, then AH-T01B, AH-R01 and AH-03. Phase 10 is `NO-GO`.

### Video Factory

- This repository retains legacy Video Factory integration and V1
  decommission evidence. Active V2/V3 acceptance belongs to the separate
  `vangnguyen/npd-video-factory-v2` repository.
- No Video Factory runtime, provider, publishing, or production action was
  performed in this documentation milestone.

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
- Consolidated Agent Hub status and roadmap:
  `docs/AGENT_HUB_HANDOFF_AND_ROADMAP_20260911.md`
- Read-only RCA bundle for `AH-P9-RCA-01`:
  `C:/Users/VANG NGUYEN/Documents/Codex/2026-08-28/ho-n-t-t-to-n/outputs/ah-p9-rca-01-20260911`
- Follow-up RCA and source capture candidate:
  `docs/AH_P9_REMOTE_PREFLIGHT_RCA_20260912.md`
- Follow-up evidence bundle for `AH-P9-RCA-02`:
  `C:/Users/VANG NGUYEN/Documents/Codex/2026-09-12/referenced-chatgpt-conversation-this-is-an/outputs/ah-p9-rca-20260912`

## Latest milestone

- Task: `AH-P9-RCA-02`, read-only RCA revalidation, independent local/remote
  reproductions and minimal source-only capture candidate.
- Result: `REVIEW_REQUIRED`. Protected-service drift is independently confirmed;
  the exact extracted old launcher/verifier behavior reproduces the masked
  error. The candidate is tested; the immutable historical capture gap remains.
- Tests: new capture regressions 19/19 PASS; historical RCA tests 12/12 PASS;
  exact extracted old behavior 2/2 PASS; independent remote sentinel and local
  exit-code wrapper PASS; historical manifest 14/14 and sealed hashes 4/4 PASS.
- CI: source exact-main 7/7 PASS reverified; candidate branch CI NOT_RUN.
- Production writes: none.
- Real provider calls: none.
- Actual cost: zero.
- Fresh gate: HOLD; no retry, replacement operation or executable gate prepared.
- Next safe action: Owner reviews the RCA and source capture candidate. A
  subsequent source-only task may adopt/reseal a fresh dispatcher and prepare a
  new gate after protected-set snapshot/change coordination and fresh bindings
  are sufficient. No pilot execution follows automatically.
