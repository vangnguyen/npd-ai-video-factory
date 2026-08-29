# AH-01/AH-01C — Video Factory V1 decommission readiness

Status: **audit complete; shutdown NO-GO**

Evidence window: `2026-08-29T09:49:35+07:00` to `2026-08-29T10:04:30+07:00`

AH-01C reference refresh: `2026-08-29T13:29:11+07:00` to `2026-08-29T13:35:22+07:00`

AH-01C base revision: `d42c8bf9e878af39f0e14f6b63d046bb48b9aae3`

AH-01B source revision: `7c4442b3c42da09626838b7d195d6eed08cc034b` (`origin/main` after PR #37)

AH-01 audit source revision: `02c31be4729bf19f150791ee623dfb25d957ada7`

Production checkout observed: `ca535a6a4cea67beeb0cae97b8fb5ea3c6c1743c`

V2/V3 documentation boundary observed: `8fa96409b0db6ec6d4dc3c04f6e3aaab2f3201ee`

This directory is the AH-01 audit package. It records evidence and future owner-gated procedures;
it does not change Agent Hub or Video Factory runtime behavior.

## Deliverables

- [V1 dependency audit](V1_DEPENDENCY_AUDIT.md)
- [V1 runtime usage audit](V1_RUNTIME_USAGE_AUDIT.md)
- [Machine-readable component inventory](v1-components.json)
- [V1 to V2/V3 capability map](V1_TO_V2_CAPABILITY_MAP.md)
- [Staged shutdown plan](SHUTDOWN_PLAN.md)
- [Rollback plan](ROLLBACK.md)
- [Risk register](RISK_REGISTER.md)
- [AH-01B UNKNOWN resolution evidence](AH01B_EVIDENCE.md)
- [Storage ownership manifest](v1-storage-ownership-manifest.json)
- [Runtime image provenance manifest](v1-runtime-image-provenance.json)
- [Backup/restore evidence manifest](v1-backup-restore-evidence.json)
- [Agent Hub Redis ownership migration plan](AGENT_HUB_REDIS_OWNERSHIP_MIGRATION_PLAN.md)
- [V1 backup/restore plan](V1_BACKUP_RESTORE_PLAN.md)
- [Publication/reference audit](V1_PUBLICATION_REFERENCE_AUDIT.md)
- [Legacy PR decisions](LEGACY_PR_DECISIONS.md)
- [AH-01C readiness closure](AH01C_READINESS_CLOSURE.md)
- [Resolved publication/reference catalog](v1-publication-reference-catalog.json)
- [Publication/reference evidence](v1-publication-reference-evidence.json)
- [Backup custody plan](BACKUP_CUSTODY_PLAN.md)
- [Backup custody record](v1-backup-custody.json)
- [Redis M0 evidence](agent-hub-redis-m0-evidence.json)
- [Legacy telemetry plan](LEGACY_TELEMETRY_PLAN.md)
- [Fresh pre-AH-03 snapshot runbook](PRE_AH03_SNAPSHOT_RUNBOOK.md)

## Decision

No V1 service, route, worker, queue, data, Caddy configuration, provider setting, or production
traffic was changed during AH-01C. The final publication `UNKNOWN` is now resolved by a conservative
catalog: no job is deletable by absence, all 12 are retained, live read families require a future
compatibility redirect, and the known V3 source remains active. Inventory `UNKNOWN=0` while
`destructive_change_allowed=false`.

The encrypted off-production V1 bundle and Redis M0 tooling passed isolated restore/restart drills.
Identity-safe telemetry source is implemented but not deployed. Owner selection of copy 2,
custodians/retention/key escrow, the separately approved Agent Hub Redis production migration, a
telemetry-only deployment plus 14 accepted days, and the fresh final snapshot all remain hard
gates. AH-03, traffic switching, port changes, V1 stop and deletion remain **NO-GO**.
