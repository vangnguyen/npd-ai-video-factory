# Agent Hub Analyze capability contract

`agent_tasks.analyze` is a projection of authenticated RBAC. The minimum role is
Operator; Owner is the existing highest administrative role. Viewer has no grant.
The literal role `admin` is not part of this repository's role schema.

Both task creation with initial analysis and existing-task reanalysis use the same
server dependency. Authentication, current email allowlist, signed-session expiry,
and same-origin requirements remain mandatory. Client headers, JSON, button state,
or a copied capability payload cannot grant server authority. The existing tool
capability registry describes tools, not an authenticated user's permission.

Authenticated WHOAMI returns role, subject, authentication method, capability
version 1, a list of grants, and integer UTC issue/expiry times. The response is
`Cache-Control: no-store`. The UI snapshot lasts at most 300 seconds and never
outlives a signed session. It controls presentation only; each server action
authenticates again. Missing, malformed, old-version, expired, future-issued, or
unknown-role snapshots disable Analyze. Delayed bootstrap from a prior connection
cannot replace a newer connection. Loading, refresh error, HTTP 401/403, token
switch, and expiry clear the prior state. A refresh may obtain a new snapshot.

Shared Analyze, Phase 9 Create with analysis, and reanalysis controls all consume
the same capability state, including action entrypoint checks. NBA feedback retains
its existing separate RBAC and duplicate-submission protection.

Historical Viewer UI evidence is preserved: the shared button was enabled while
the old handler and backend already denied Viewer. The fix corrects presentation
and publishes a shared capability projection; it does not grant new roles.

This contract grants no Phase 9 execution approval. Static packages remain
non-executable until a separate permitted preparation and exact Owner approval.
`PHASE9_SLA_COHORT_CLOCK = MISSING` remains a business-acceptance blocker. Authentic
policy/clock/deadline and response evidence must be supplied by a future approved
cohort; production data must never be edited to manufacture overdue acceptance.
