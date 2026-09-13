# AH-P9-RCA-08: stage identity and claim-only custody

The approved operation `PHASE9-LIMITED-PILOT-RCA06-2da31c5f-b02e-4902-a815-82fa49ee63bc`
passed gate/preflight, wrote claim `542945ca-a1fb-49af-a340-4acd5485ee8f`, and
stopped before SCP with `STAGE_OPERATION_INVALID`. The source baseline is
`dfe5fa8a2cffa1f98e806b483bfed164c2e9a39f`. Its approval is consumed; it must
never be retried. The existing claim/state files and attempt directory are
historical production writes, not writes by RCA-08. This task makes no remote
mutation and prepares no new pilot/JIT gate.

## Proven path and minimum identity correction

The baseline package verifier accepted canonical RCA05/RCA06 identifiers;
`pilot_transport.stage_argv` accepted only an RCA05 regex. The runner called
that staging validator after `invoke_mode(..., 'claim', ...)`, so rejection
occurred after the remote metadata claim but before the SCP invoker. Remote
preflight compared the exact bound operation and legacy v1 schema; it did not
contain the staging family regex. The strings containing `rca05` in dispatch,
claim and confirmation entropy are compatible v1 wire identifiers, not a
family restriction. Browser/UAT evidence schema names remain unchanged.

`operation_identity.py` now owns explicit RCA05/RCA06 allowlists, lowercase
canonical UUID **v4**, and compatible dispatch/claim/confirmation identifiers.
Gate and staging transport use this same validator. Staging also requires the
operation to match the verified runtime profile. The runner checks the verified
operation/profile and validates staging arguments before preflight/claim,
while retaining pinned-trust revalidation immediately before SCP. The rendered
stdin runtime embeds the same canonical source; no independent family regex
or a remote import dependency is introduced. The canonical source is a required
package dependency for future adoption, not an addition to any approved old
package. The known consumed `2da31c5f` operation is permanently denied for
execution, even if someone builds new evidence under that identifier. Parsing
the identifier for custody does not grant execution authority. All approval,
package, snapshot, counter and window comparisons remain mandatory.

## New local terminalization contract, not yet deployed

The previous source has no claim-only abort transition. RCA-08 explicitly
defines `CLAIMED -> ABORTED_BEFORE_STAGE` as a **new locally tested contract**.
The tool is limited to the exact consumed orphan above, with exact attempt,
claim/state byte hashes, timestamps, source/tool/CI bindings, private root
metadata, and an independently bound no-stage/no-SCP/no-deploy certificate.
Current owned attempt inventory must be exactly `state.json`; any candidate,
override, custody/receipt or extra file rejects the first transition.

Production use requires separately issued, verbatim
`OWNER_CLAIM_ONLY_TERMINALIZATION_APPROVAL`. The old pilot approval and
preparation documents cannot authorize it. The local entry checks exact HEAD,
source component hashes, transported tool bytes and the pinned SSH profile.
The server checks root-owned private paths, ownership, hashes and eligible
state; verifies the unchanged live target/protected services/counters read-only;
and rechecks bytes/inventory before closing. The actual old mutation deadline
must match the claim and already be closed. The new closure deadline is
exclusive; no pilot counter freshness or pilot window is extended.

Allowed metadata paths are exactly the owned claim JSON, owned state JSON,
`claim-before-terminalization.json`, `state-before-terminalization.json` and
`claim-only-terminalization.json` inside that same attempt. No directory/new
claim/other operation is created or changed. Original claim/state bytes are
preserved with exclusive private custody files. An intent receipt is written,
then state first, then claim, then the completed receipt after unchanged live
baseline/readback verification. Temporary replacement files remain inside the
owned metadata directory. If interrupted, execution fails closed: terminal
state or custody collisions cannot authorize retry, and the retired identifier
cannot be reused. A partial close requires Owner review, never automatic retry.
Second terminalization is rejected without changing bytes.

The runtime verifier transported with the tool uses only the sealed read-only
baseline functions. It makes no image/service, Redis key/value, Caddy config,
network/mount/volume/port, Video Factory, provider or business writes. The
existing exception permits only the four DB0 `EVAL_RO` counters; the same
aggregate checks can run before/after closure. Legacy Journey/NBA rollback HTTP
absence remains verified using its sealed read-only projection.

## Validation and subsequent gates

Regressions cover the current fresh family through gate/dispatcher/staging,
canonical identity errors, stale/expired/retired identifiers, wrong bindings or
package, approval modification/replay, and pre-claim transport rejection.
Terminalization fixtures cover one close, second rejection, wrong operation or
attempt, stage/extra/override/deploy/mutation flags, hash or live drift, old or
expired approval, no retry, unaffected other operations and interrupted close.
All fixtures and business evals are local/synthetic, not production actions or
CI substitutes. The changed source requires actual CI for its new exact HEAD;
old 3/3 source CI is historical only.

After preparation tests/CI and a fresh read-only claim audit PASS, issue a
separate exact closure approval draft. **Do not execute it in RCA-08.** After
a subsequent separately approved and verified close, candidate adoption must
consume the explicit terminal receipt while preserving retired identities.
The old external counter collector treats any claim/attempt path as active;
it must not simply bypass that check or delete history. Active/terminal custody
classification belongs to the reviewed later adoption, before a new manual
JIT, snapshot, operation/window/package reseal and fresh pilot approval.

Next safe action: **OWNER REVIEW + EXPLICIT CLAIM-ONLY TERMINALIZATION APPROVAL**.
Phase 10, AH-T01B, AH-R01, AH-03/AH-04 and all other workstreams remain closed.
