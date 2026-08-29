# Video Factory V1 decommission risk register

## Status

All risks below are open unless explicitly marked otherwise. AH-01 recorded evidence only; no
production mitigation was executed.

Priority meanings:

- `P0`: blocks shutdown or represents an exposed path capable of material data/cost/availability
  impact; requires an owner decision before the next production change.
- `P1`: must be resolved before deprecation/disable acceptance.
- `P2`: governance or cleanup risk that should be resolved in the staged program.

## Register

| ID | Priority | Risk and evidence | Impact | Required mitigation | Gate/owner |
|---|---|---|---|---|---|
| R-001 | P0 | V1 `POST /api/v1/video-jobs` is unauthenticated, port 8000 is public, idempotency is optional, and the worker has paid TTS configured. | Untrusted callers can enqueue compute/provider work and create cost or abusive load. | Owner-gated containment, authentication/deprecation telemetry and rate policy; never test with a real write during audit. | Production network/API owner before any deploy; tracked by `v1-public-port-exposure`. |
| R-002 | P0 | Renderer port 3001 is public; `POST /render` and static `/media` have no authentication. `/media` spans the entire mixed storage root. | Compute exhaustion, artifact exposure, overwrite within allowed storage paths, or leakage of owner-review material. | Identify callers, add identity/telemetry, restrict exposure, migrate caller, then disable direct route/media path. | Network and renderer owner; separate approval from AH-01. |
| R-003 | P0 | Renderer processed `vid_1787989200000_a1b2c3d4e5` on 29/08 local time. AH-01B attributed this exact request to a one-off Codex V3 owner-review render, while renderer logs still omit caller identity. | The observed call is explained, but existing telemetry cannot independently prove zero other consumers. | Add identity-safe telemetry and observe zero unexplained calls for 14 days before any disable/stop. | Decisions are `DEPRECATE`/`DISABLE`; production action remains owner-gated. |
| R-004 | P0 | Agent Hub DB1 is hosted by the Redis container owned by the V1 Compose project; 6,352 Agent Hub namespace keys were observed. | V1 Compose/Redis stop or volume removal can take down Agent Hub and lose business/audit state. | Rehome or formally split Redis ownership with separate DB1 backup/restore evidence. Never use project-wide down/volume removal. | Agent Hub data owner; separate migration before Stage C/E. |
| R-005 | P0 | V1 storage contains V1 jobs/assets plus four `owner-review-v3-*` directories updated on 28/08. AH-01B classified all 194 files by path/size/mtime/SHA-256. | V1 cleanup can destroy V2/V3 owner-review evidence or unrelated owner data. | Enforce the manifest: migrate only explicit `jobs/`/owner-approved assets; `KEEP` every V3 path; prohibit whole-root actions. | `mixed-storage-root` is `MIGRATE`; every storage mutation still requires data-owner approval. |
| R-006 | P0 | Redis AOF and one env backup exist, but no independent restore-tested DB0 + storage + exact-image bundle was found. | Shutdown or data change may be irreversible. | Create checksummed backups, isolate secrets, restore-test outside production, and retain forward-recovery snapshot. | `v1-backup-restore-coverage` remains `UNKNOWN`; blocks Stage A/C. |
| R-007 | P0 | Agent Hub `video.jobs.create` is an enabled write capability, `requires_approval=false`, and execute-action can dispatch it directly. | An operator action can create a V1 paid job without the intended owner approval boundary. | AH-02/AH-03: signed client, explicit policy/approval, idempotency and deprecation behavior; mocks before production. | Agent Hub owner approval before behavior/deploy change. |
| R-008 | P1 | AH-01B matched all copied runtime inputs to source commits and recorded exact image IDs, but the local images still have no registry digest/git label or independent export. | Source is attributable; rollback portability can still disappear through image loss. | Keep the provenance manifest and exact image IDs; export/checksum/restore-test them in the owner-approved backup bundle. | Source provenance is `KEEP`; portability remains blocked by `v1-backup-restore-coverage`. |
| R-009 | P1 | V2-11 bridge supports draft project creation only and currently emits only `video.project.created`. | V1 create/render/status/approval/publish cannot be replaced through the authorized boundary yet. | Extend only through accepted versioned bridge contracts under V2 ownership; implement Agent Hub mocks/contract tests first. | V2/V3 owner and acceptance gates; no non-bridge shortcut. |
| R-010 | P1 | Root `.env` gives `OPENAI_API_KEY` to API, worker and renderer; only worker needs TTS. | Larger secret exposure surface and accidental disclosure/call risk. | Narrow secret injection; remove V1 secret after worker retirement/rollback expiry; never copy to Agent Hub/V2. | Owner-approved secret/config change and container recreation. |
| R-011 | P1 | V1 has no publication/analytics schema and no n8n execution, but external CMS/social/internal artifact references were not enumerated. | Read-route/storage removal can break links or delete referenced media. | Authorized reference audit and redirect/archive policy. | `v1-publication-reference-catalog` remains `UNKNOWN`. |
| R-012 | P1 | API/worker logs are partial; renderer logs progress but not caller identity; no deprecation counters exist. | Lack of observed calls cannot prove lack of consumers; observation period is unreliable. | Add identity-safe legacy-call audit/counters and alerts before write blocking; reset observation on unexplained use. | AH-03 reviewed instrumentation and owner deploy approval. |
| R-013 | P1 | Retention/rights policies are not defined for 7 awaiting-review jobs, 5 failed jobs, local assets, pilot copies and protected logs. | Over-retention, premature deletion, rights violations or inability to satisfy rollback/audit. | Owner-approved dataset-by-dataset retention, rights/provenance and secure archive policy. | Data owner before Stage B exit or any archive expiry. |
| R-014 | P2 | The n8n Sprint 1 workflow is inactive, has zero executions and currently cannot resolve V1 API by network name. | Misleading operational surface; future activation could fail or reintroduce V1 writes. | Export/version, keep inactive, then deprecate/delete under owner gate; do not duplicate media logic in n8n. | n8n owner before workflow state change. |
| R-015 | P2 | Root README and several docs still describe V1 as the primary NPD architecture. | Operators may treat V1 as strategic, deploy the wrong Compose topology, or merge legacy work. | Mark legacy after AH-01 acceptance; publish Agent Hub-first boundary while retaining rollback docs. | Reviewed documentation PR. |
| R-016 | P2 | Draft PR #34 expands V1 QC and #35 expands V1 TTS; both remain open while decommission becomes the strategy. | Merging grows the legacy engine; closing without retention can discard rollback/test evidence. | Keep #34 frozen as evidence and deprecate #35; DO NOT MERGE either; retain until rollback/archive exit criteria pass. | Classifications are `KEEP`/`DEPRECATE`; close/retarget/delete remain owner gates. |
| R-017 | P1 | API/status/artifact records include business request content and retained media, but routes use knowledge of job ID as the only access boundary. | Confidential business/media data can be read if IDs/paths leak. | Authenticated read-only legacy archive, access audit and retention; restrict direct public ports. | API/network/data owner before Stage A/C. |
| R-018 | P1 | V1 worker startup automatically requeues every processing-list item. | Restoring stale processing state can duplicate work or paid/external side effects. | Reconcile job state/artifacts/V2 mappings before starting one worker; restore namespace/order with reviewed tool. | Rollback owner and per-job approval. |

## Shutdown blockers

Stage A and all destructive work remain blocked until:

- all remaining `UNKNOWN` inventory decisions are resolved;
- R-001 through R-009 have accepted mitigations/evidence;
- R-010 through R-013 have owners and completion criteria;
- a fresh production snapshot confirms no new risk or dependency;
- the owner explicitly approves the next stage.

Closing a risk in documentation requires evidence. A plan, green CI, empty queue, HTTP 200, or
mergeable PR is not evidence that the production risk is resolved.
