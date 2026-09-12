# AH-P9-RCA-06: final freshness and execution-window binding

Agent Hub ONLY. Preparation only; owner execution approval NOT_GRANTED.
RCA-05's counter receipt is expired and cannot authorize initial dispatch.
Its package and previous operations remain immutable provenance.

The new window is sealed in EXECUTION_WINDOW.json, with UTC/ICT start/end,
dispatcher-start, initial-counter/claim, target-mutation, forward/UAT and
recovery deadlines. The established allocation is at least 20 minutes before
the mutation cutoff, 55 additional minutes for the forward/UAT decision,
and 45 additional minutes reserved for recovery. Dispatcher start reserves
240 seconds of the counter's exact 600-second freshness interval for preflight.
The runtime checks counter expiry again before creating its first owned claim.

Approval must match the package's exact window/hash; an arbitrary ordered
window is rejected. All initial dispatch paths retain live 600-second counter
verification before and after the read-only child. Package, payload, scope,
operation and protected confirmation bind the same window and current HEAD.

UAT/rollback followups require a proved already dispatched transaction:
unchanged package, snapshot, counter, operation, dependencies, approval and
confirmation; captured initial streams/exit/UUID/input/timestamps; matching
local dispatch and remote owned claim; fresh counter at that initial claim.
They independently enforce their current decision/recovery deadlines and
remote owned claim. This cannot start another pilot or bypass initial TTL.

Only the existing four DB0 counters are collected with the accepted EVAL_RO
query. No additional Video Factory data or execution path is authorized.
The immutable backup/restore/image/query/exception evidence has no additional
TTL in the current contract and is reused with its actual hashes. Agent Hub
protected/role receipts are refreshed only if matching the new candidate HEAD
requires it; their observations are never relabeled as fresh without a read.

The externally sealed final receipt must match the committed current HEAD,
real exact-HEAD CI, snapshot, counter and package. It defines the final window
and copyable draft approval text after CI. Missing, mismatched or expired final
material means HOLD_NOT_PREPARED; this document is not execution authority.

Limitations retained: historical primary capture is unavailable; fresh
substitution/new protected baseline was accepted for preparation. Backup and
confirmation custody is CurrentUser DPAPI only; portable copy2 is unavailable.
Actual desktop/mobile UAT, the one-task/one-review evidence and full Phase 9
business acceptance are pending. No customer/provider/Video Factory execution,
configuration/network/volume/port mutation, scheduler/automation/Run Now,
Phase 10, AH-T01B, AH-R01 or AH-03/AH-04 is authorized.

Stop after gate preparation. CLAIM/STAGE/DEPLOY/OPERATION_EXECUTION NONE.
Production/Video Factory writes, provider calls and actual cost all zero.
NEXT_SAFE_ACTION: OWNER REVIEW + EXPLICIT EXECUTION APPROVAL.
