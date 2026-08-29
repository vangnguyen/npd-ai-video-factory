# AH-01 — Video Factory V1 decommission audit

Status: **audit complete; shutdown NO-GO**

Evidence window: `2026-08-29T09:49:35+07:00` to `2026-08-29T10:04:30+07:00`

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
- [Agent Hub Redis ownership migration plan](AGENT_HUB_REDIS_OWNERSHIP_MIGRATION_PLAN.md)
- [V1 backup/restore plan](V1_BACKUP_RESTORE_PLAN.md)
- [Publication/reference audit](V1_PUBLICATION_REFERENCE_AUDIT.md)
- [Legacy PR decisions](LEGACY_PR_DECISIONS.md)

## Decision

No V1 service, route, worker, queue, data, Caddy configuration, provider setting, or production
traffic was changed during AH-01. Destructive work is prohibited while the inventory contains any
`UNKNOWN` decision. AH-01B attributed the observed `2026-08-29` local-time renderer request,
classified the complete mixed-storage manifest, proved source provenance and recorded PR retention
directions. Backup/restore and external publication-reference coverage remain `UNKNOWN`; Redis
rehome and telemetry are accepted-plan prerequisites, so shutdown remains NO-GO.

The next eligible initiative is AH-02 contract work using mocks only. AH-03 deprecation, AH-04
drain/disable, production deployment, merge, traffic switching, and deletion each remain explicit
owner gates.
