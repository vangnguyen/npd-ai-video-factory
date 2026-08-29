# AH-01 — Video Factory V1 decommission audit

Status: **audit complete; shutdown NO-GO**

Evidence window: `2026-08-29T09:49:35+07:00` to `2026-08-29T10:04:30+07:00`

Source revision: `02c31be4729bf19f150791ee623dfb25d957ada7` (`origin/main`)

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

## Decision

No V1 service, route, worker, queue, data, Caddy configuration, provider setting, or production
traffic was changed during AH-01. Destructive work is prohibited while the inventory contains any
`UNKNOWN` decision. The current inventory does contain `UNKNOWN` dependencies, including an
unattributed direct renderer caller observed on `2026-08-29` local time.

The next eligible initiative is AH-02 contract work using mocks only. AH-03 deprecation, AH-04
drain/disable, production deployment, merge, traffic switching, and deletion each remain explicit
owner gates.
