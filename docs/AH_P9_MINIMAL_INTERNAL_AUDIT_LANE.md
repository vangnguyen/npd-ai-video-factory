# Phase 9 minimal internal audit lane

Product parent: `e5d3510d0b7e38a18990cdd27a56cc2491e0b295`.
Preparation parent receipt: `ce6f157a5c31284ef19b89f9b79dd7ad280b28b69181f56e97c3b3e8fac6c687`.

This source candidate moves the two mandatory successful ingest audits to the
existing per-Campaign audit list for one explicitly approved internal cohort.
The global attribution list, its 5,000 cap and commercial/default behavior are
unchanged. No historical evidence is trimmed, archived or migrated by this lane.
No production activation, campaign/Lead creation or pilot approval is included.

## Authority and classification

`Campaign.internal_cohort` is a strict, immutable typed contract. It binds exact
canonical Campaign, `lead:<native-id>`, existing internal owner identifier,
Owner approval digest, positive non-customer proof digest, one-task/report/audit
and one-NBA-review scope. Contact, commercial attribution and automation are
false. The five reporting exclusions are true. Campaign budget is zero, SLA is
15 minutes and no channel/notification plans are permitted.

The existing authenticated Owner dependency controls creation of this typed
classification; Operator/Viewer and caller-supplied role strings cannot assign it.
The classification cannot be updated through the draft endpoint. Names,
project codes, missing contact details and inactivity provide no authority.

In addition, `AGENT_PHASE9_INTERNAL_COHORT_BINDING_FILE` must identify an
Owner-approved, protected, read-only one-delivery server binding. Its default
is empty, so internal ingest is denied until a separate gate binds and activates
it. It contains the exact typed cohort, one delivery ID, one native source event
ID, authentic timezone-aware occurred_at, source record/audit digests and exact
delivery payload digest. Public API payloads cannot install this binding.
Actual owner/team, native Lead, positive source provenance, file path/permissions
and binding publication remain separate creation-gate requirements. Test files
and fixture approval digests are synthetic and never production authority.

The accepted source remains native authenticated EspoCRM `lead_created` export
with direct canonical Campaign binding. No native CRM Campaign or registry is
required by this path. Alternative UTM/registry resolution into an internal
Campaign is denied. Wrong subject/Campaign, missing/forged classification,
nonzero budget, changed proof/payload or retry never falls back to global audit.
Direct raw ingest/backfill and generic failure routing cannot bypass the lane.

## Evidence preservation and reporting

Existing attribution and receipt producers prepare the touchpoint, quality
snapshot, signed receipt and two original `AttributionAuditEvent` objects in
isolated memory. The event types remain `source_touchpoints_ingested` then
`signed_delivery_received`. No successful-ingest audit is suppressed.

Each Campaign audit entry preserves the exact producer JSON string and its
`raw_attribution_audit_sha256`, original ID, actor, detail, timestamp and semantics.
Additional context binds exact subject/Campaign, original source occurred_at,
delivery/receipt/snapshot IDs, payload digest, approved scope, source evidence and
Owner/non-customer proof. `internal_delivery_binding_sha256` is explicitly a
semantic model digest. It does not substitute for raw audit integrity or the
unchanged Phase 9 raw stdout/canonical payload dual-digest contract.

Entries are appended without overwrite. Existing Campaign history gives stable
newest-first readback; the two ingest entries reverse to producer order.
`verify_audit` independently verifies original raw bytes and the entire binding.
Whitespace reserialization, digest or context changes are rejected.

Aggregate attribution touchpoint counts/lists and commercial reconciliation
exclude the typed internal cohort. Internal observations are excluded before
quality/revenue calculation; no credit is reallocated to commercial Campaigns.
Internal-only commercial reconciliation is denied before writes. Exact-subject
journey/SLA reads remain available for Phase 9 acceptance, outside commercial
customer SLA metrics. Campaign API exposes the explicit exclusion contract.
No general reporting platform is introduced. Provider/customer actions are not
part of this ingest path; internal Campaign channel plans are blocked.

## Atomic no-eviction commit

Store: existing `<namespace>:campaign-os:audit:<canonical_campaign_id>`.
Cap: **2,000**, unchanged. Required successful-ingest budget: **2 audit entries**.

Redis uses one explicit WATCH/MULTI/EXEC attempt. Before the first business
mutation it watches and validates Campaign content, audit list/capacity, source
and subject ownership, receipt/snapshot create-only keys, every affected index
and the identity registry read set. Key types are validated before EXEC to avoid
Redis transaction runtime errors causing partial command execution. The subject
must have no existing ledger event; receipt/source reuse is denied.

The commit queues exactly 9 commands across 9 business/audit keys: three SET NX,
five ZADD and one RPUSH carrying two distinct audit records. No LTRIM/DEL,
cap increase, eviction, archive or automatic retry exists in this path.
Campaign/ledger/index/registry change after observation causes WATCH failure
before any queued business mutation. Capacity 1,998 accepts two; 1,999/2,000
denies. Other Campaign audit helpers also use no-trim capacity enforcement for
typed internal Campaigns, preserving this custody after ingest.

Memory tests use one shared writer lock and the same pre-write assertions.
Redis and memory behavior are checked with deterministic local fixtures, real
fakeredis WATCH conflicts and concurrent threads. Backend/EXEC communication
ambiguity must be reviewed/read back; it never authorizes automatic retry.

## Static acceptance and compatibility

Tests cover complete audit/raw/context readback, unchanged 5,000 global entries,
strict classification and Owner API denial, default commercial routing,
SLA pending/deadline/overdue semantics, commercial revenue exclusions, cap
boundaries, concurrency/replay, registry/Campaign changes, wrong Redis types,
forged markers and alternative resolution. A local Phase 9 task/report consumes
the internal exact subject with an executor that forbids all external calls.
Existing Viewer capability/UI/API and all ops/capture/recovery tests are retained.

All test source records are clearly synthetic/local, not authentic production
evidence. Source simulation does not close final Phase 9 business acceptance.
Production Owner/team/native Lead and source side-effect bindings are unresolved.
The creation gate and pilot/JIT gate remain NOT_PREPARED.

## Migration and rollback

No production migration or schema rewrite is needed for existing Campaigns:
missing `internal_cohort` means the legacy/default path. Legacy envelope/receipt
digest serialization is unchanged. No production binding file is shipped.
Existing global/customer writers and caps are preserved. Retention/IAM/journal/
S3/KMS infrastructure remains deferred after Phase 9.

Before any future activation, separately review exact Owner/team/native record,
positive internal proof, reporting/source side effects, protected binding file,
current per-Campaign capacity and exact creation/ingest write budget.
After internal records exist, an old binary must not resume ingest for that
Campaign: it lacks this typed routing and could use the global lane. Freeze
ingest, preserve raw Campaign/audit/receipt custody and select a compatible
rollback candidate under a separate approval. Removing/changing the binding
denies internal ingest; it does not reactivate/retry a consumed delivery. Never
delete source or Phase 9 evidence automatically.
