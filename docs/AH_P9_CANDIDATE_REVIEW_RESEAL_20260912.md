# AH-P9-RCA-03 — Candidate Review & Reseal Preparation

Workstream: Agent Hub only. Disposition: `REVIEW_REQUIRED`.
Authority: source review, local tests, scoped GitHub CI, passive runtime capture
and review-package sealing only. Pilot execution gate: `HOLD_NOT_PREPARED`.

## Reviewed source and root cause

The initial checkout was clean on
`fix/agent-hub-p9-preflight-capture-20260912`, at
`9eed9fb69d547726a18d13b517d4230272e9d0eb`. Its canonical handoff SHA-256 was
`3b665aa7470a93713b8ee9d924f3fec72b6213d99a0ef6fc7034093ac36f8b31`.
Remote main remained `43a1cca354d12893ee33b6e43cd9117794f78e04`.

The complete exact-main-to-initial-candidate diff contains six additions:
`HANDOFF.md`, `handoff.json`, the consolidated Agent Hub roadmap, the RCA-02
report, the capture library, and its regression suite. All six were reviewed.
The Agent Hub application, API/worker/renderer, Compose, Caddy, Redis, network,
volume and port configuration trees are unchanged. The subsequent hardening
adds one Agent Hub-only CI workflow and changes the capture library/tests and
Agent Hub documentation. Video Factory handoff sections remain unchanged.

The terminal pilot's underlying blocker is `PROTECTED_SERVICE_DRIFT`. Its
visible `e3b0c44298fc1c14` label is the SHA-256 prefix of empty stderr. The
sealed remote runtime emits sanitized failure JSON to stdout and exits 2;
the old local launcher discarded child stdout, return code and invocation UUID.
The original historical child streams/return code/UUID remain unrecoverable.
Fresh reproductions do not replace this missing primary historical evidence.
Owner disposition of this bounded evidence gap remains required.

The initial capture candidate correctly published an exclusive, fsynced receipt
before classifying failure, preserved exact safe failure stdout as base64, and
kept separate stream byte lengths/hashes, child exit and UUID. Unknown output
is redacted. Nonzero child exit, timeout, wrapped transport failure, malformed
output and unavailable evidence abort. There is no approval, claim, staging,
deployment or scheduler entrypoint.

Review identified incomplete success validation: sanitization was not required,
and a caller's full binding verifier was not mandatory. Hardening commit
`4a3ab94ca72398afd11aa10e1509741f5866da91` now requires explicit sanitization,
an integer exit code, empty stderr for PASS, and a caller verifier returning
exactly `True`. Missing, rejecting or throwing verification stops after receipt
publication. This library remains transport/capture infrastructure; a future
dispatcher must preserve every remote authority, window, topology, role,
counter and protected-set check. No pilot dispatcher was adopted or generated.

## Tests and actual CI

| Evidence | Result |
| --- | --- |
| Capture regressions, Windows Python 3.13 | 29/29 PASS |
| Full Agent Hub local suite | 299/299 PASS |
| Business-answer fixture eval | 20/20 PASS |
| Historical RCA evidence | 12/12 PASS |
| Historical gate fixture suite | 31/31 PASS |
| Strict SSH path/transport fixture suite | 24/24 PASS |
| Exact extracted old launcher and baseline verifier | 2/2 PASS |
| Fresh independent remote sentinel | stdout failure JSON, child exit 2, empty stderr; PASS |

Coverage includes both streams and their lengths/hashes, exit 0/2/255, empty
output, malformed/duplicate/multiple JSON documents, bindings, safety flags,
redaction, timeout/start failures and their wrapped causes, exclusive publication,
fsync/link failure, verifier ordering/rejection/error, and an actual subprocess
with a quoted/spaced path, shell metacharacters and binary stdin through a pipe.
Transport tests cover client-native paths, strict host checks, hash/fingerprint
drift and `shell=False`. Historical gate PASS output is fixture-only and proves
no real claim, pilot or UAT.

Scoped GitHub CI ran against exact hardening HEAD `4a3ab94...`, with 3/3 PASS:
capture tests on Linux and Windows Python 3.12, plus the full Agent Hub suite
and 20-case eval. Actual run:
https://github.com/vangnguyen/npd-ai-video-factory/actions/runs/34671833149.
Exact-main CI was independently reverified 7/7 PASS. Initial `9eed9fb...` had no
CI; the review hardening supersedes it. Shared Video Factory CI jobs were not
started by the scoped workflow. Final receipt-head CI and checkout/job evidence
are recorded in the output bundle's `CI_EVIDENCE.json`; CI is never simulated.

The local and CI Agent Hub suites report two existing dependency deprecation
warnings. They do not affect test results.

## Fresh passive snapshot

Accepted diagnostic snapshot ID:
`AH-P9-RCA-03-SNAPSHOT-247cd494-a466-426a-956a-983f01c009af`.
This is a diagnostic identity, not an execution operation.

The strict-SSH invocation uses the existing verified client-native known-hosts
file, approved identity, `StrictHostKeyChecking=yes`, `BatchMode=yes`,
`IdentitiesOnly=yes`, fixed `python3 -B -` remote arguments and `shell=False`.
Transport inputs were freshly hashed and the host fingerprint checked.
No known-hosts or remote file was written. Only passive container projections,
Agent Hub health/readiness and config file hashes were collected. Container
environment contents, logs, Redis data, customer/CRM/SaleHub/Video Factory
application endpoints and credential values were not captured.

Accepted snapshot shows 18 protected services; Agent Hub is healthy/ready with
restart count zero. Target signature, protected set and config hashes are
unchanged from RCA-02. Historical claim/attempt/state/stage paths are absent.
Current protected-set digest is
`6e0167343174e4cb719b3799015dc5d438b8cdcc545774dc72d53f61cf2c648e`,
which still differs from the old pilot's `dafe99c1...` binding. The old operation
therefore remains terminal and unusable. Exact current target signature is
`10231d87a7d1a7a50b4b8826e9fc542013ae3a5dc629538f0e684371244c9d2c`.
The exact accepted primary stdout bytes and their transport receipt are retained.

Two diagnostic attempts were rejected because snapshot metadata was accidentally
inserted into the collector's signature dictionary. These were collector defects,
not runtime drift. Their payloads and receipts are retained separately. The first
attempt retained stream hashes/lengths but not raw stdout; the second retained
its exact stdout. The correction targets only the top-level snapshot document
and asserts AST equality of all signature helpers before a fresh invocation.
Only the third snapshot is accepted for the review seal.

This passive snapshot is not a complete execution-gate snapshot. Fresh backup,
restore, role identity, safety-counter, coordination and execution-window
bindings were not collected or materialized. Their absence cannot be treated
as PASS. All 43 historical package/approval files were rehashed unchanged.

## Review reseal and exact blockers

The output package has a new review UUID and a manifest binding its source,
tests, workflows, accepted snapshot/primary transport, independent sentinel,
diagnostic history, local read-only collector, local integrity verifier,
handoffs and real CI evidence. Hashes are calculated from current bytes.
Equal hashes for unchanged inputs mean verified byte equality; they are never
reused as execution authority. An externally anchored manifest and archive
hash are provided in `HASH_SUMMARY.json`. Integrity PASS grants no pilot authority.

No pilot OCI archive, execution payload/runner/verifier, operation ID, window,
approval, confirmation token, claim or executable gate was created. Their
required fresh hashes are explicitly `NOT_RESEALED` in `RESEAL_PLAN.json`.
Review-package hashes must never substitute for those execution dependencies.
`FRESH_GATE_READINESS.json` stays `HOLD_NOT_PREPARED`.

Blockers are Owner RCA/capture review and historical-gap disposition, protected
workstream coordination, a complete fresh execution snapshot/backup/restore,
fresh dispatcher adoption with full verifier and new bindings, and uncompleted
Phase 9 UAT/business acceptance. Production writes, real provider calls and
actual provider cost are all zero.

## Runbook for the next assigned preparation task

1. Owner reviews this package, original diff and hardening, and records a bounded
   disposition of the historical capture gap. Never relabel a reconstruction as
   primary historical evidence or retry the terminal operation.
2. Obtain protected-workstream change coordination. Any service/config/topology
   change invalidates the next snapshot and its dependent package hashes.
3. Recheck exact main/CI and take a complete fresh read-only execution snapshot,
   including approved role/counter bindings and fresh backup/restore proof.
   Passive health/status and this review seal alone are insufficient.
4. Adopt capture into a separate fresh dispatcher/payload. Keep preflight before
   claim/stage and retain all authority, expiry, scope, fingerprint, topology,
   role/counter and protected-set checks. Supply a verifier for exact fresh
   response bindings; its result must be `True` before any successful return.
5. Generate fresh candidate artifact and separately bind every package, payload,
   runner, verifier, backup, rollback/finalizer and snapshot dependency. Populate
   the missing entries in the reseal plan; no old operation or authority is valid.
6. Prepare a fresh limited-pilot gate for Owner review only after those checks
   pass. A separately approved execution task must bind new operation, window
   and protected confirmation-token custody. Preparation does not claim, stage,
   deploy or execute a pilot.

Phase 9 UAT/business acceptance is still incomplete. Phase 10, AH-T01B, AH-R01,
AH-03/AH-04, scheduler/automation and all adjacent production work remain outside
this task. `NEXT_SAFE_ACTION`: Owner review/disposition and protected-workstream
coordination, followed by a separately assigned source-only dispatcher adoption
and complete fresh-gate evidence task. Stop here; no execution follows.
