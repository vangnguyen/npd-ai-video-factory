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

### RCA-03 review and reseal preparation

- Task: `AH-P9-RCA-03`; verdict `REVIEW_REQUIRED`.
- Original candidate and canonical handoff bindings were verified clean.
  The complete exact-main `43a1cca...` to `9eed9fb...` diff was reviewed.
- Source hardening `4a3ab94ca72398afd11aa10e1509741f5866da91` requires a
  successful full-binding verifier, explicit sanitization, integer child exit
  and empty stderr for PASS. Capture remains library-only; no pilot adoption.
- Tests: capture 29/29; Agent Hub 299/299; business eval 20/20; historical RCA
  12/12; historical gate fixtures 31/31; transport fixtures 24/24; extracted
  old launcher/verifier 2/2; fresh independent remote failure sentinel PASS.
- Actual scoped candidate CI at the code head: 3/3 PASS on Linux/Windows;
  source exact-main 7/7 PASS. Final receipt-head CI evidence is saved externally
  in the assigned output bundle, without a self-referential handoff commit.
- Accepted snapshot `AH-P9-RCA-03-SNAPSHOT-247cd494-a466-426a-956a-983f01c009af`
  is passive-only: 18 protected services, target/config unchanged from RCA-02,
  health/ready PASS, restart 0, no historical claim/attempt/state/stage paths.
  Protected digest remains `6e0167343174e4cb719b3799015dc5d438b8cdcc545774dc72d53f61cf2c648e`.
- Two rejected diagnostic attempts are retained as collector defects, not
  runtime drift; only the corrected third snapshot is used for sealing.
- A fresh review package binds source, tests, real CI and accepted snapshot
  bytes, passive diagnostic payload/collector and local integrity verifier.
  Its hashes grant no execution authority. Pilot OCI/runner/payload/verifier
  dependencies remain `NOT_RESEALED`; fresh execution gate `HOLD_NOT_PREPARED`.
- All 43 historical package/approval files were freshly rehashed unchanged.
  No execution operation, window, approval, token, claim, staging or deployment
  was created. Production writes/provider calls/actual provider cost: 0/0/0.
- Blockers: Owner review and historical-gap disposition; protected-workstream
  coordination; full fresh execution snapshot/backup/restore/role/counter
  bindings; separate fresh dispatcher adoption; Phase 9 UAT remains incomplete.
- Detailed review/runbook: `docs/AH_P9_CANDIDATE_REVIEW_RESEAL_20260912.md`.

### RCA-04 fresh evidence and dispatcher reseal

- Task: `AH-P9-RCA-04`; verdict `BLOCKED`; gate `HOLD_NOT_PREPARED`.
- Owner accepted protected-service drift and substitution of fresh capture for
  preparation/reseal only. Historical stdout/exit/UUID remain unavailable;
  the new captures are not recovered historical primary evidence.
- Disposition bound to exact starting HEAD `fd33418fd8e5b83b6326cc2a80bcbefce5ea58ac`;
  receipt SHA-256 `5119b51224d70bfb553f0c5a10727e1b9c8e1cd55ec8cdbdccc063641ef6cb8c`. Execution approval is
  `NOT_GRANTED`. No operation, token, claim, stage or deployment was created.
- Fresh protected baseline: 18 services; canonical digest `6e0167343174e4cb719b3799015dc5d438b8cdcc545774dc72d53f61cf2c648e`;
  target, file configuration and health match RCA-03. No additional drift.
- Fresh namespace backup: 10,692 keys (10,375 strings, 302 lists, 15 zsets),
  read-only source consistency verified and AES-256-GCM encrypted locally.
  The exact running rollback image was freshly exported and encrypted.
  A new CurrentUser-DPAPI key is kept outside the public review package.
- Actual fresh restore: 10,692/10,692 values/types/absolute TTLs verified,
  including a Redis process restart from the fixture's RAM RDB. Rollback
  config/OCI/layer integrity PASS. Local fixture had network none, TCP port 0,
  no published ports/bind mounts/Docker volumes and was removed. Production
  Redis received read commands only. Application restore/browser UAT not run.
- Fresh role assignment and whoami: 3/3 PASS. Fresh Agent Hub safety counters
  PASS, namespace count matches backup, cohort remains negotiation.
- Full execution snapshot `INCOMPLETE_FAIL_CLOSED`: the existing pilot contract
  requires four Video Factory DB0 counters. They were not queried under the
  explicit Agent Hub ONLY / no Video Factory instruction, not assumed zero,
  and not filled from stale evidence. The guard was preserved.
- Hardened capture was adopted for actual fresh read-only collectors with a
  mandatory verifier. Pilot runner/dispatcher/runtime/token/approval/window
  integration and all affected execution dependencies remain unverified and
  `NOT_RESEALED`; no execution gate was prepared.
- Regressions rerun: capture 29, Agent Hub 299, mock business eval 20, historical
  RCA 12, gate fixtures 31, transport fixtures 24, extracted old behavior 2;
  all PASS. Four independent fresh remote fail-closed fixtures PASS.
  Historical fixture output labeled PILOT_PASS is test-only, not a real pilot.
- Collector failures and corrections are retained: two pre-fixture BytesIO
  cursor errors, rejected Lua numeric-precision readback, and a rejected role
  collector import-order error. Only accepted replacements feed the seal.
- Fresh evidence/package sealing, secret/scope/inventory/tamper results and
  actual exact final-HEAD CI are saved externally in the RCA-04 output bundle.
  A docs-only commit does not alter Agent Hub or any other executable tree.
- Production writes/provider calls/actual cost: 0/0/0. Phase 9 UAT is pending.
- Runbook: `docs/AH_P9_FRESH_EVIDENCE_DISPATCHER_RESEAL_20260912.md`.

### RCA-05 counter bridge and fresh pilot preparation

- Task: `AH-P9-RCA-05`; verdict `REVIEW_REQUIRED`; execution approval `NOT_GRANTED`.
- Owner evidence-only exception authorizes exactly four existing DB0 counter
  reads. Video Factory remains closed to all execution and mutation.
- Observed counters: job count 12; queue/processing/in-flight 0/0/0. EVAL_RO
  enforces read-only execution. Primary streams/exit/UUID/UTC are captured.
- Full snapshot PASS: protected 18/6e0167343174e4cb719b3799015dc5d438b8cdcc545774dc72d53f61cf2c648e, roles 3/3, fresh namespace/
  rollback-image evidence and actual 10,692/10,692 isolated restore PASS.
- Hardened dispatcher is integrated into the actual fresh sealed preparation
  package. Real read-only preflight and all eleven counter bindings PASS.
  Local 454 regression checks and ten actual-package tamper cases PASS.
- New final identity `PHASE9-LIMITED-PILOT-RCA05-29db0877-9203-4796-bf3a-8046ab19a0f5`. The final current-HEAD package/seal,
  exact-HEAD CI and hashes are defined by the external final receipt. Missing
  or mismatched receipt/package means HOLD; a handoff alone is not authority.
- New confirmation is protected outside the public package. UTC window UNBOUND.
  Historical terminal operation, gate, approval and confirmation stay immutable.
- Owner review + explicit fresh execution approval is the only next action.
  No pilot execution/claim/stage/deploy; production/VF writes/calls/cost 0.
- Runbook: `docs/AH_P9_COUNTER_EVIDENCE_BRIDGE_PILOT_RESEAL_20260912.md`.

### RCA-06 final freshness and exact window preparation

- Task `AH-P9-RCA-06`; reserved fresh identity `PHASE9-LIMITED-PILOT-RCA06-9459bd18-56a2-4bdf-8592-54b7d94abc7b`.
- RCA-05 counter evidence has expired. Its approval/window material is not
  execution authority; previous sealed package remains immutable provenance.
- Exact window/hash, 600-second initial TTL, captured initial dispatch proof
  and separate forward/UAT/recovery deadlines are enforced fail-closed.
- Final evidence, window and hashes are defined by the exact committed HEAD's
  external receipt/package only. Missing/mismatch/expiry means HOLD_NOT_PREPARED.
- Immutable backup/restore/image evidence is retained; no unrelated RCA redo.
- Owner execution approval NOT_GRANTED; no pilot/claim/stage/deploy.
- Runbook: `docs/AH_P9_FINAL_FRESHNESS_WINDOW_BINDING_20260912.md`.

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

- Task: `AH-P9-RCA-06 — Final Freshness Refresh & Execution Gate Binding`.
- Verdict `REVIEW_REQUIRED`; gate is PREPARED only when the current HEAD's
  external final receipt and verified package/window are PASS and still fresh.
  Otherwise HOLD_NOT_PREPARED. This handoff is not execution authority.
- Reserved new operation: `PHASE9-LIMITED-PILOT-RCA06-9459bd18-56a2-4bdf-8592-54b7d94abc7b`. Owner execution approval NOT_GRANTED.
- Exact UTC/ICT window, dispatcher/mutation/UAT/recovery deadlines, fresh
  four-counter receipt and all affected hashes: `C:/Users/VANG NGUYEN/Documents/Codex/2026-09-12/referenced-chatgpt-conversation-this-is-an-2/outputs/ah-p9-rca-06-20260912`.
- Old RCA-05 receipt is expired and cannot authorize initial dispatch. The
  historical terminal operation and previous sealed packages remain immutable.
- Final real CI, tests, integrity, package seal and copyable draft approval
  are in HANDOFF_RECEIPT.json, RESEALED_DEPENDENCIES.json and OWNER_APPROVAL_TEXT.txt.
- CurrentUser DPAPI only; portable copy2 unavailable; historical primary
  capture unavailable; actual browser UAT/Phase 9 acceptance remain pending.
- OPERATION_EXECUTION/CLAIM/STAGE/DEPLOY NONE; production/VF writes, real
  provider calls and actual cost all zero. Other workstreams remain closed.
- NEXT_SAFE_ACTION: OWNER REVIEW + EXPLICIT EXECUTION APPROVAL. Stop.

## Fast-track to Phase 9 closure — 2026-09-23

- Task: `AH-P9-FAST-TRACK-TO-CLOSURE`; workstream: Agent Hub only.
- Product/artifact source HEAD: `915ba10845e25de60aacb474b4b2a4c7f623fddc` on
  `feat/agent-hub-p9-owner-fence-canonical-contract`. The bounded
  `phase9_delivery` runtime permits only the exact server-owned one-delivery
  binding; scheduler initialization and unrelated routes remain denied.
- ACL RCA classification: `ACL_RESPONSE_CONTRACT_MISMATCH`, not a real QC
  permission denial. The App/user response carries `acl.table.Lead.create` as
  the effective string representation; the old runner re-entered the already
  extracted ACL map through a second `acl` lookup. The shared canonical parser
  now accepts the exact authenticated QC shape, remains fail-closed for
  missing/unknown/wrong-QC input and contains no QC-ID special case.
- Gate C is historical, terminal and already consumed successfully. Attempt
  `8c10479e-8a74-40f9-a25f-2a724f2fb4d3` produced Lead
  `6aabc611758efd76b` (`createdBy=6aab5af0215b97ba2`,
  `assignedUserId=6a4dd6d5c8ee64bed`) and Campaign
  `CMP-AHINTERNAL-P9SLACOHORT-202609-01`; terminal verdict
  `AUTHENTIC_INTERNAL_COHORT_CREATED_VERIFIED`, receipt SHA-256
  `43c5e075371d55e6c2467767e8e61cd2277d6406e2bd22df2801953a06a10783`.
  It is not a reusable Gate C authority.
- Fresh read-only runtime observation: `phase9_creation`, health/ready PASS,
  scheduler disabled, Owner fence `6a4dd6d5c8ee64bed`, DB1 10,700 keys,
  protected services 18/18 with canonical SHA-256
  `6e0167343174e4cb719b3799015dc5d438b8cdcc545774dc72d53f61cf2c648e`,
  and custody intact. This observation must be revalidated JIT before mutation.
- Gate 2 is Owner-approved but not yet executed. Operation
  `AH-P9-ONE-DELIVERY-7f30c64e-9d40-483f-ac90-ae1acdb7faed`; immutable package
  manifest SHA-256
  `63dc77f39b1c0244c38dd0c09f33f5c33a9b93224c85102d328f77d4c653bb3b`;
  approved window 20:00–21:30 ICT on 24/09/2026, latest target mutation start
  before 20:20 ICT. Target is only `npd-agent-hub-prod/agent-hub` and delivery
  `P9DELIVERY:e340bc60-7e98-4593-8414-0cca844507c0`, attempt 1/1, no retry.
- Gate 2 target archive SHA-256
  `03b03412617fc3320fdefec3310596933c82258a2d0a895ea63b98bf7b08c9df`,
  target Docker config
  `sha256:2097e3cb4e711f0dc6a6479f2b51ac524432910576a12e932c0be030efb1e6d7`,
  rollback config
  `sha256:dce8d804e0b1b5186b2571a617ca9985682d2eb0e2d5b46b5c942fc729232056`.
- Gate 2 runner proves strict pinned SSH, claim-before-stage, exact staged code,
  exact Operator bearer identity, one business POST, durable post-intent,
  no retry, signed receipt, direct DB1 record and five-index readbacks,
  Lead-index 0→1, exactly +2 internal Campaign audits, unchanged identity
  mappings/global attribution audit, protected-service parity, and bounded
  Agent-Hub-only pre-POST rollback. Any post-launch ambiguity preserves state.
- Downstream delivery/SLA preparation is fully bound to the authentic Gate C
  values. The SLA clock is `2026-09-17T10:50:57Z`, deadline
  `2026-09-17T11:05:57Z`; no backdating or synthetic response evidence is
  allowed. The authentic SLA result remains pending the one delivery and real
  response-evidence evaluation.
- Final UAT is `READY_FOR_REAL_COHORT`; acceptance dossier is
  `READY_FOR_FINAL_EVIDENCE`. Remaining authentic evidence is the delivery/SLA
  receipt, final bounded production UAT, and Owner internal-use acceptance.
- Failure contracts are sealed: pre-Lead abort has no business mutation;
  partial/ambiguous Gate C states preserve evidence without deletion or retry;
  delivery and UAT failures preserve state and require Owner review.
- Verification: Gate 2 focused 49/49, delivery/SLA 90/90, final UAT/dossier
  36/36, failure-contract focused 18/18, Agent Hub regression 509/509,
  evaluator 20/20, ops 187 PASS/1 skipped, exact-source GitHub checks 4/4,
  package integrity 15/15 and secret scan 0 findings.
- Exact Gate 2 package:
  `C:/Users/VANG NGUYEN/Documents/Codex/2026-08-28/ho-n-t-t-to-n/outputs/ah-p9-one-delivery-gate-20260923`.
  External seal evidence SHA-256:
  `62524d1b213ca1480d58c2fe81a992b9cb46210ad2342aadf94409eaa8c98198`.
- Independent post-seal audit: 21/21 negative/harness checks and 3/3
  AST/static checks PASS; audit manifest SHA-256
  `19767fb88cc368f81143b5824fe2b292f04aa871af87fcf61fa35e0e90f042cf`.
- Production access/writes, real-provider calls and actual cost for this
  fast-track preparation: `0/0/0`. Phase 10 remains NO-GO.
- Owner consent was received verbatim and materialized outside the immutable
  package. Consent SHA-256
  `d0d22521aaac7fe91933a8366a78e80c753edd1474a81c30c16350ebbd5d3d59`;
  approval-record SHA-256
  `c93ec2320e90f5a4ae143f632d9fc46fb8da05b7b2ac285551725c5a7a0b47f6`;
  approval evidence-manifest SHA-256
  `c72e8e1c2dae001f461f3f95dbcb76120ff77f6793a2442313a8f7a564a31c62`.
  Static package/authority verification is PASS without `--execute`, SSH,
  claim, stage or production access.
- NEXT_SAFE_ACTION: wait for the approved window, then perform fresh JIT
  validation and execute only if every bound invariant passes and target
  mutation can begin before 20:20 ICT. No automation was created.

## Post-Phase-9 roadmap reconciliation — 2026-09-24

- Task: `AH-POST-P9-ROADMAP-RECONCILIATION`; verdict `PASS` for planning.
  The audit was read-only with respect to production. Production writes,
  provider calls and cost were `0/0/0`.
- Phase 9 remains P0. The only remaining terminal outcomes are the approved but
  unexecuted authentic `lead_created` delivery, authentic SLA result, final
  production UAT and Owner internal-use acceptance. Copy 2, AH-T01B, AH-R01 and
  V1 retirement are not Phase-9 closure dependencies.
- Post-Phase-9 work is split into two independent lanes:
  1. product value: `PHASE_9_PASS` -> choose one Phase-10 channel -> bounded
     implementation/gate/acceptance;
  2. legacy risk: AH-T01B + AH-R01 + portable Copy 2/custody + accepted
     bridge/catalog -> fresh pre-AH03 snapshot -> staged V1 retirement.
- There is no authoritative strict dependency from the legacy lane to Phase-10
  entry. Phase 10 remains `NO-GO` until Phase 9 passes and one channel has an
  exact least-privilege preview/idempotency/rollback/acceptance package.
- AH-01/01B/01C and AH-02 source work are complete. AH-T01B production and its
  14-day observation are not started. AH-R01 M0 is offline PASS; M1–M4 are not
  executed. Copy 2 and portable recovery remain open.
- AH-03 remains required only if V1 retirement proceeds. The standalone AH-04
  label is retired from planning and merged into shutdown Stages B–E; it must
  not generate an invented Owner gate.
- V1 retirement and generalized RCA16–18A custody hardening are moved off the
  Phase-10 product critical path. Minimal Phase-9 pieces are already absorbed;
  the remaining generalized retention/PG/S3/issuer/KMS/Google-sub work is
  trigger-based hardening, not a default prerequisite.
- Evidence-based progress: Phase-9 implementation preparation is complete;
  Phase-9 acceptance is `0/4` remaining outcomes. Across accepted terminal
  product and legacy outcome groups, `10/18 = 55.6%` are complete. This count
  excludes merged AH-04 and optional hardening and does not treat source-ready
  work as production acceptance.
- Authoritative detail, inventory, dependency DAG, fast-track waves, gate count
  and acceptance criteria:
  `docs/AH_POST_P9_ROADMAP_RECONCILIATION_20260924.md`.
- NEXT_SAFE_ACTION remains unchanged for the active Phase-9 lane: do not execute
  roadmap items; use the existing Gate-2 authority only in its exact window and
  only after all JIT invariants pass. After `PHASE_9_PASS`, start Wave 1 static
  preparation and ask Owner to select the first Phase-10 channel.

## Gate 2 terminal pre-claim abort — 2026-09-24

- Task: execute exact Owner-approved Gate 2 operation
  `AH-P9-ONE-DELIVERY-7f30c64e-9d40-483f-ac90-ae1acdb7faed`.
- Static authority/package verification PASS with package manifest
  `63dc77f39b1c0244c38dd0c09f33f5c33a9b93224c85102d328f77d4c653bb3b`
  and the exact approved consent/record/archive hashes.
- The first remote action aborted at `2026-09-24T13:02:39.707497Z`, before
  the remote preflight runner started. Terminal reason:
  `STRICT_KNOWN_HOSTS_PATH_REPRESENTATION_INVALID`.
- Root cause: the immutable Windows launcher passed an unquoted
  `UserKnownHostsFile` value containing the `VANG NGUYEN` path segment.
  Windows OpenSSH split it into two filenames, so it did not read the exact
  pinned known-hosts file and correctly failed strict host-key verification.
- No trust check was weakened and no alias/global-known-hosts workaround was
  installed. A read-only diagnostic proved the same exact file works when the
  option value is quoted; this diagnostic was not used to bypass the sealed
  launcher.
- Strict post-abort readback: claim/attempt/stage/runtime all absent; Agent Hub
  remains running and healthy on rollback image
  `sha256:dce8d804e0b1b5186b2571a617ca9985682d2eb0e2d5b46b5c942fc729232056`,
  restart count 0. Candidate load/deploy, delivery POST, DB1 write, provider
  call and Video Factory action all remain zero. Rollback was not required.
- This operation, package and approval are terminal and not reusable. The
  minimal next step is source-only launcher remediation, real Windows OpenSSH
  parser coverage, fresh reseal and a new Owner gate. Do not retry this gate.
- Evidence:
  `C:/Users/VANG NGUYEN/Documents/Codex/2026-08-28/ho-n-t-t-to-n/outputs/ah-p9-one-delivery-execution-20260924`;
  evidence manifest SHA-256
  `afb61bc7773f4d269038deeb37f8d868b00fe13b7fd8ec20ab9ce5f8a3351413`.

## Gate 2 transport remediation and fresh reseal — 2026-09-24

- Task: `AH-P9-GATE2-TRANSPORT-REMEDIATION-RESEAL`; verdict
  `REVIEW_REQUIRED` because a fresh Owner production gate is now the only
  remaining authority prerequisite. No production execution is authorized by
  this handoff.
- Canonical Windows OpenSSH transport now quotes the `UserKnownHostsFile`
  value for OpenSSH's second-stage option parser and normalizes separators to
  forward slashes. SSH and SCP share the same validated renderer. Source/test
  commit: `0c6329669092d347cb800f8f28dc03b07e939203`.
- Verification: Phase 9 ops 192 PASS / 1 Linux-only skip, Agent Hub 509/509,
  business evaluator 20/20, candidate Gate 2 55/55, delivery/SLA contract
  46/46, syntax 5/5, package integrity 16/16, secret scan zero findings and
  exact-head GitHub Actions run `36004874392` 3/3 PASS, including Windows.
- Fresh operation:
  `AH-P9-ONE-DELIVERY-7d8dcca6-b1df-4e1f-a8ad-7dfa6e89e0e9`.
  Proposed window: 20:00–21:30 ICT on 25/09/2026, latest mutation start before
  20:20 ICT. Owner approval is `NOT_GRANTED`.
- Fresh immutable package manifest SHA-256:
  `63057926338ece41def10cb6abda627251d97dc4d73c062fe4524012a562842b`.
  The application image was not rebuilt; exact verified artifact policy is
  `REUSED_VERIFIED_IMAGE_ARTIFACTS` with archive SHA-256
  `03b03412617fc3320fdefec3310596933c82258a2d0a895ea63b98bf7b08c9df`.
- Final package-bound strict-transport rehearsal used only remote command
  `true`: parser PASS, exit 0, stdout/stderr 0 bytes, no claim, no SCP, no
  stage and no write. Final eligible receipt SHA-256:
  `6b452462a3d2286de13ba32b8e8b5d14f2a8c4f49249c63478bb4e6aa65e53e9`.
  Preliminary receipt `7097fee1...` is superseded and ineligible because the
  package was subsequently resealed.
- Old operation/package/approval remain terminal and non-reusable. This task
  created no `APPROVED` record and performed no claim, staging, deployment,
  business delivery, DB1 write, provider call, customer action or Video
  Factory action.
- Package:
  `C:/Users/VANG NGUYEN/Documents/Codex/2026-08-28/ho-n-t-t-to-n/outputs/ah-p9-one-delivery-gate-r2-20260925`.
  Readiness evidence:
  `C:/Users/VANG NGUYEN/Documents/Codex/2026-08-28/ho-n-t-t-to-n/outputs/ah-p9-one-delivery-gate-r2-20260925-evidence`;
  evidence manifest SHA-256
  `bb5114b7bbb9917243a003e453e7f7da9ab748d4e6ae0906e937a2e813673991`.
- NEXT_SAFE_ACTION: Owner reviews and, only if accepted, repeats the exact line
  in `OWNER_CONSENT_TO_APPROVE.txt`. Do not execute or materialize an approved
  record before that fresh gate.

## Gate 2 retry Owner approval materialized — 2026-09-24

- Task: `AH-P9-GATE2-RETRY-OWNER-APPROVAL-MATERIALIZATION`; verdict `PASS`.
- Owner approved exact operation
  `AH-P9-ONE-DELIVERY-7d8dcca6-b1df-4e1f-a8ad-7dfa6e89e0e9` for the bounded
  window `20:00–21:30 ICT` on 25/09/2026 (`13:00–14:30Z`), with target
  mutation required to start strictly before `20:20 ICT` (`13:20Z`).
- Exact consent SHA-256:
  `8661b7453bf6f39a292c1cd96261f64848cbe3e54667d5a8efd4ee16c34e041e`.
  Exact external `APPROVED` record SHA-256:
  `46f8aacc206cede2ffda457ac500a159d20b61e7ebc875914bd7886586566b4d`.
- The immutable package remains unchanged at manifest SHA-256
  `63057926338ece41def10cb6abda627251d97dc4d73c062fe4524012a562842b`;
  the eligible strict-transport rehearsal receipt remains
  `6b452462a3d2286de13ba32b8e8b5d14f2a8c4f49249c63478bb4e6aa65e53e9`.
- The sealed launcher was run without `--execute` and returned
  `STATIC_PACKAGE_VERIFIED`. That validation made no network SSH call and
  created no runtime evidence, claim, stage, deployment, DB1 write, provider
  call, customer action or Video Factory action.
- Approval evidence:
  `C:/Users/VANG NGUYEN/Documents/Codex/2026-08-28/ho-n-t-t-to-n/outputs/ah-p9-one-delivery-owner-approval-r2-20260924-7d8dcca6`;
  manifest SHA-256
  `a422af65a1e0d6fa9f3ecc51dfd5f7c57b99bc5779d590eb572c1454d8139a58`.
- Current state is `WAITING_FOR_AUTHORIZED_WINDOW`. No automation or scheduler
  was created. This approval must not be used before the window or after its
  expiry and must not be reused after a terminal outcome.
- NEXT_SAFE_ACTION: at or after `20:00 ICT` on 25/09/2026 and still before
  `20:20 ICT`, perform fresh JIT validation of every sealed invariant. Invoke
  the launcher with `--execute` only if all checks pass and the operation is
  still unclaimed; otherwise abort fail-closed. Do not pre-stage.

## Gate 2 retry terminal pre-claim abort — 2026-09-25

- Exact operation
  `AH-P9-ONE-DELIVERY-7d8dcca6-b1df-4e1f-a8ad-7dfa6e89e0e9` started inside
  its approved window. Invocation:
  `56c41df5-806c-4de5-bc23-fab4d394dd53`.
- The sealed launcher aborted fail-closed at remote business preflight, before
  atomic claim creation. Terminal classification:
  `GATE2_RETRY_TERMINAL_ABORTED_PRECLAIM`; launcher reason
  `PREFLIGHT_CLAIM_FAILED`; remote reason `IN_CONTAINER_PREFLIGHT_FAILED`.
- Root cause is proven as `DIGEST_DOMAIN_REPRESENTATION_MISMATCH`, not campaign
  content drift. Gate C bound the raw authenticated HTTP response SHA-256
  `60cb41b0da6384ee8677fff7d7cc5b89d6a759e0355ac6b0c56d8e7ae4c50cd8`,
  while the Gate-2 preflight recomputed the semantic Pydantic model digest
  `8c06ad499c8bffc40ff26fe2361e0ae7a4226ff4d5d738ecd41f73bc938614ec`
  and incorrectly compared the two digest domains.
- A read-only authenticated GET inside the unchanged container proved both
  hashes simultaneously over the same HTTP 200 response and exact campaign
  identity. No raw bearer, response body or secret was exported.
- Post-abort state: claim/attempt/stage/runtime absent; candidate load,
  deployment and delivery POST absent; DB1 writes, provider calls and external
  actions all zero. Agent Hub remains on rollback image
  `sha256:dce8d804e0b1b5186b2571a617ca9985682d2eb0e2d5b46b5c942fc729232056`,
  running, healthy, restart count 0. Rollback was not required.
- This operation/package approval is terminal and non-reusable. Evidence:
  `C:/Users/VANG NGUYEN/Documents/Codex/2026-08-28/ho-n-t-t-to-n/outputs/ah-p9-one-delivery-execution-r2-20260925`;
  manifest SHA-256
  `f45fffa6ab6110aa3aeef07f7b27684c7d123caf50effc1c0e6fcf96b338b9f7`.
- NEXT_SAFE_ACTION: prepare a source/package-only digest-domain fix, bind raw
  transport and semantic model digests as distinct evidence, add a
  production-shape regression, reseal a fresh operation and request a new
  Owner gate. Do not retry this operation.

## Gate 2 digest-domain remediation and fresh R4 reseal — 2026-09-25

- Task: `AH-P9-GATE2-DIGEST-DOMAIN-REMEDIATION-RESEAL`; verdict
  `REVIEW_REQUIRED` because the source/package remediation is complete and a
  fresh Owner production gate is the only remaining authority prerequisite.
- Canonical Gate-2 verification now treats authenticated raw HTTP bytes and
  Agent Hub semantic campaign content as separate named digest domains. It
  rejects missing, swapped, wrong-field, wrong-type and secret-bearing inputs.
  Source/test commit: `c75dc44a1f4913e3c873756d52dcaf1cc767eb7a`.
- Verification: Phase 9 ops 201 PASS / 1 platform skip, Agent Hub 509/509,
  business evaluator 20/20, delivery/SLA 46/46, candidate package 69/69,
  syntax 6/6, package integrity 20/20 and exact-source GitHub Actions run
  `36141806761` 3/3 PASS.
- R3 failed safely during read-only rehearsal because its embedded probe
  reused the HTTP `raw` variable for a decoded Redis string. The failure was
  before claim, staging, mutation or POST. R4 preserves the HTTP bytes and has
  an exact embedded-probe regression covering the production-shaped Redis
  decode path.
- Fresh R4 operation:
  `AH-P9-ONE-DELIVERY-6369ae1d-4b41-4d47-8463-24deacfec75c`.
  Proposed-only window: 20:00–21:30 ICT on 26/09/2026, with target mutation
  required to start strictly before 20:20 ICT. Owner approval is
  `NOT_GRANTED`; no approved record or automation exists.
- Fresh immutable package manifest SHA-256:
  `0f8875f5a653c01825537bb5e62890b50c0c1c54003716b35293bec303d2149a`.
  Runner SHA-256:
  `44cd2d865428c8f6cb95158c05e5c36b07f7d3921c14664d14f416ba68157155`.
  Helper SHA-256:
  `d26bda14f00ab556a229e8c192acdecc5d04c739cf59cc47670202f661edaa86`.
- Final package-bound strict transport rehearsal PASS receipt SHA-256:
  `a02ea4153d6d75cc71d97fcebacac4a1747e008e9322b5dfc2f6f1104fe12aaa`.
  Final exact sealed read-only preflight PASS receipt SHA-256:
  `80a20bd25e50247b167b27a26bd1b7a775b08337a0296641d322d29de45194d7`.
  It proved raw HTTP SHA-256 `60cb41b0da6384ee8677fff7d7cc5b89d6a759e0355ac6b0c56d8e7ae4c50cd8`
  and semantic model SHA-256 `8c06ad499c8bffc40ff26fe2361e0ae7a4226ff4d5d738ecd41f73bc938614ec`
  simultaneously, with claim/stage/delivery state absent and protected state
  unchanged.
- Evidence:
  `C:/Users/VANG NGUYEN/Documents/Codex/2026-08-28/ho-n-t-t-to-n/outputs/ah-p9-one-delivery-gate-r4-readonly-rehearsal-20260925`;
  evidence manifest SHA-256
  `ae005418c467db3724d2e621c360b53fcb6a94c2607080b66b18e3583f56ce95`.
- Production writes, DB1 writes, provider calls, Video Factory actions, claim,
  stage, image load, deployment and delivery POST remain zero/absent.
- NEXT_SAFE_ACTION: Owner reviews and, only if accepted, repeats the exact line
  in the R4 `OWNER_CONSENT_TO_APPROVE.txt`. Do not materialize an approved
  record or execute this operation before that fresh gate.

## Gate 2 R4 owner-consent exact-text hold — 2026-09-25

- Owner approval intent was received for operation
  `AH-P9-ONE-DELIVERY-6369ae1d-4b41-4d47-8463-24deacfec75c`, but the received
  text is not byte-equal to the sealed consent template.
- The only differences are three Unicode EN DASH characters (`U+2013`) in
  `–no-deps`, `–no-build`, and `–pull`; the sealed template requires the ASCII
  double-hyphen flags `--no-deps`, `--no-build`, and `--pull`.
- The launcher explicitly rejects non-exact consent. No normalization was
  applied and no `APPROVED` authority record was materialized.
- R4 package, operation, proposed window, hashes and evidence remain unchanged.
  No production access, claim, staging, deployment, delivery POST, DB1 write,
  provider call or Video Factory action occurred.
- Evidence:
  `C:/Users/VANG NGUYEN/Documents/Codex/2026-08-28/ho-n-t-t-to-n/outputs/ah-p9-one-delivery-owner-approval-r4-20260925`;
  evidence manifest SHA-256
  `0ab216818e0278b8f2de56113300ae0162aefaf7ece7212007d9baef0eac6405`.
- NEXT_SAFE_ACTION: Owner repeats the existing R4 consent with the three ASCII
  double-hyphen flags unchanged. Do not execute or create an approved record
  until exact-text validation passes.

## Gate 2 R4 Owner approval materialized — 2026-09-25

- Owner retransmitted the R4 consent with the required ASCII Compose flags.
  The `lead\_created` and `max\_attempts` sequences in the thread are CommonMark
  presentation escapes and render as the exact sealed tokens `lead_created`
  and `max_attempts`; no substantive binding changed.
- Canonical consent is byte-equal to the sealed expected text. Consent SHA-256:
  `28f85014ceaa1ad7cb4b7a75474d6b40fe3915256648175e01a78841b5875d13`.
- External `APPROVED` record SHA-256:
  `c6bae39b84f554ccc476e54d861519ba644865412f256380e47c76143b202fa7`.
  Approval evidence manifest SHA-256:
  `6e6eda6863895ad131fee937754376cffb4a0b7730a08a5bd36cd376ecaa946e`.
- The sealed launcher was run without `--execute` and returned
  `STATIC_PACKAGE_VERIFIED`. Static validation receipt SHA-256:
  `cc263d06c62a638742d39e8be2860e772645d18d589b2a9c1faead34f42a92e9`.
- Operation
  `AH-P9-ONE-DELIVERY-6369ae1d-4b41-4d47-8463-24deacfec75c` is approved only
  for 20:00–21:30 ICT on 26/09/2026, with target mutation beginning strictly
  before 20:20 ICT. No scheduler or automation was created.
- Production access, claim, staging, image load, deployment, delivery POST,
  DB1 write, provider call and Video Factory action remain zero/absent.
- NEXT_SAFE_ACTION: wait for the approved window. At or after 20:00 ICT and
  still before 20:20 ICT, run fresh fail-closed JIT validation, then invoke the
  exact sealed launcher with `--execute` only if every binding remains valid.
  Do not pre-stage or execute early.
