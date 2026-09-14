# Phase 9 creation runtime fence

This temporary mode supports the separately approved, Lead-first internal
cohort creation path. It grants no creation or deployment authority itself.

The four explicit settings are:

```text
AGENT_RUNTIME_MODE=phase9_creation
AGENT_PROVIDER_HEALTH_SCHEDULER_ENABLED=false
AGENT_PHASE9_CREATION_CAMPAIGN_ID=CMP-AHINTERNAL-P9SLACOHORT-202609-01
AGENT_PHASE9_CREATION_OWNER_ID=6a658eeb6ab0c81ab
```

Missing or invalid creation bindings fail before startup. Missing mode remains
normal for compatibility, but cannot pass creation-gate fence verification.

Creation mode skips scheduler initialization, lease acquisition and the loop.
It also rejects forced scheduler calls. Existing scheduler history is retained
without rewriting its enabled field. Runtime mode, absence of a scheduler task
and denied entrypoints prove the fence; historical status is not new authority.

The HTTP boundary permits health/readiness, authenticated capabilities and
provider scheduler/status reads, and exact Campaign/audit reads. Its only
business write route is the existing Owner-authorized `POST /api/v1/campaigns`,
with the approved typed internal CID, Owner, zero-VND budget and exact planning
fields. The existing internal classification, native proof/approval digests,
three-slot WATCH/MULTI/EXEC no-trim guard and server RBAC remain mandatory.
Every other route, including Run Now, delivery, heartbeat, provider refresh,
task analysis/execution, UAT and other Campaign writes, is denied before its
handler. Native Espo login is a separate existing application path.

Creation proceeds only after separate gates: restore the integration User read
permission; adopt and verify this exact fenced image; then ordinary native
Owner login and exact server-side identity/ACL verification. Create at most
one native Lead, preserve its source-generated creation evidence, bind the
positive non-customer receipt, then create at most one Hub Campaign. Stop.
No ingest, new pilot, retry or automatic cleanup is authorized by these flags.

Normal mode retains existing scheduler and API behavior. Before business
creation, separately approved rollback restores the exact recovered image and
the four-setting pre-image; it restores no Redis or business records. Any
partial creation requires custody and Owner review, rather than retry/delete.
