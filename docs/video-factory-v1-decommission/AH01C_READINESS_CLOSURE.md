# AH-01C decommission readiness closure

Status: **technical slice complete; AH-03 remains NO-GO**

AH-01C resolves the final inventory `UNKNOWN` through conservative retention, implements offline
Redis migration tooling and identity-safe telemetry source, and makes the remaining owner gates
explicit. No production deployment or mutation was performed.

| Workstream | Result | Remaining gate |
|---|---|---|
| Publication/reference catalog | 12 V1 jobs and four route/integration records classified; `UNKNOWN=0`. One V3 lineage is `ACTIVE_REFERENCE`; all other jobs are `ARCHIVE_REQUIRED`; live read families are `REDIRECT_REQUIRED`. | Owner accepts the catalog. Absence never authorizes deletion. |
| Backup custody | Primary encrypted bundle and technical restore remain PASS; checksums and current DPAPI boundary recorded. | Owner selects independent copy 2, custodians, portable recovery escrow and retention. |
| Agent Hub Redis M0 | Version 2 export preserves absolute TTL, checksums and stable-source proof. Synthetic Redis 7 restore, parity, explicit-replace rollback and restart persistence PASS. | Production DB1 export/restore, target provisioning and migration require separate AH-R01 approval. |
| Legacy telemetry | API/renderer source emits route counters and HMAC identities without payload/raw identity; known Agent Hub and worker callers self-label. Local tests PASS. | Separate production deploy approval, protected salt, then 14 complete accepted days. |
| Fresh pre-AH-03 snapshot | Fail-closed runbook prepared. | Not captured until every prior gate passes; owner approves the then-current snapshot. |

The inventory may report zero `UNKNOWN` while `destructive_change_allowed=false`. Those are not
contradictory: each component now has a safe disposition, but the custody, production migration,
telemetry observation and owner approvals are incomplete.

## Explicitly not authorized

- deploy/restart/stop V1 or Agent Hub;
- migrate Redis DB1 or change `AGENT_REDIS_URL`;
- block V1 writes, switch traffic, change Caddy or close ports;
- move/delete storage or V1 code/data;
- change n8n production state; or
- start AH-03.

Current decision: **V1 DECOMMISSION = NO-GO**.
