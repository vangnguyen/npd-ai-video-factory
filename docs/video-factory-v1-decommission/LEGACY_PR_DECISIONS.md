# Legacy PR #34 and #35 retention decisions

Status: **classification only; GitHub state unchanged**

AH-01B inspected both draft PRs read-only. It did not merge, close, retarget, mark ready, push to,
or otherwise change either PR.

## PR #34 — retain frozen evidence

- Title: `Clean-port Sprint 1 video QC from PR #8`.
- State: open draft, mergeable, behind current `main`.
- Scope: 36 files, +7,697/−277, including API/worker/renderer/QC/E2E contracts and evidence.
- Last recorded checks: 7 successful checks on its dated head.
- Runtime relationship: the production worker/renderer source lineage overlaps this legacy stack.

Decision: `KEEP` as frozen source/QC/rollback evidence, with **DO NOT MERGE** status. Do not update it
to current `main`; that would turn an evidence branch into new legacy development. Retain its head
commit and check links until the V1 rollback/observation window expires and an immutable archive is
accepted. Closing or deleting the branch remains an owner gate.

## PR #35 — deprecate the stacked TTS proposal

- Title: `Clean-port production pilot TTS from PR #6`.
- State: open draft, mergeable, stacked on PR #34.
- Scope: 17 files, +1,350/−52, adding legacy production TTS/pilot tooling.
- Last recorded checks: 3 successful checks on its dated head.
- Boundary: its TTS/voice work does not control the independent V2/V3 repository or human voice
  acceptance gate.

Decision: `DEPRECATE` with **DO NOT MERGE** status. Preserve the branch/PR as historical provider and
pilot evidence until exact-image backup, V1 rollback retention and the separate owner-review record
are all accepted. Closing, retargeting or deleting it remains an owner gate.

These classifications resolve the inventory's direction without granting any GitHub mutation or
production authority.
