# AH-P9-RCA-16 — Dedicated internal authentic SLA cohort design

Status: **OWNER COHORT CREATION NOT_GRANTED / HOLD_NOT_PREPARED**. Agent Hub only.
No source, Campaign, event, ledger write, delivery, JIT or pilot is performed.
This is separate from Retention/Custody Policy Adoption.

## Legitimate source and explicit business disposition

Recommend one actual internal Owner/team service inquiry, represented by one
**native EspoCRM Lead**, in a dedicated internal/non-customer business scope.
Repository already recognizes `IdentitySource.ESPOCRM`, `lead_created` and the
`lead:<native Lead ID>` subject contract. It does not presently prove that an
administrative/test Lead is authentic business evidence. Owner must explicitly
adopt the internal service-inquiry business semantics and no-customer obligation
before native creation. A record created only to inject a test event is not
equivalent evidence. If the real inquiry cannot legitimately use Lead semantics,
HOLD; do not relabel synthetic data or bypass source via DB1.

Native creation should be by the separately authorized human/source identity via
normal EspoCRM Lead UI/API. Existing Codex X-Api-Key is GET-only authority: it is
not upgraded or used for POST, and no credential is requested/changed. Read-only
export then verifies exact source/native creation audit, original createdAt,
owner and native Campaign relation. Dedicated Lead export/conversion is still a
future implementation requirement; no automatic existing Lead producer is assumed.

`form_submit`/`form_submit_fallback` is schema/evaluator-supported, but no existing
authenticated internal form was proven. It is **not the recommended source path**.
Paused Meta/customer Lead Intake, CRM ingest workflows, scheduler and customer
messages are not activated by this design.

## Campaign and positive non-customer proof

Proposed ID `CMP-AHINTERNAL-P9SLACOHORT-202609-01` follows the actual Campaign OS
pattern/build rule. It is **not created, reserved or uniqueness-verified**. Future
exact creation must recheck inventory/sequence. Proposed fields:

- purpose: actual internal service-inquiry first-response evidence, no customer
  acquisition, sales pipeline/revenue attribution or contact obligation;
- project code `AHINTERNAL`, name `P9 SLA Cohort`, business scope
  `internal_non_customer`, budget0 and first-response SLA15 minutes;
- owner: exact authenticated existing Owner principal/team plus native assigned
  source owner; identifiers remain **UNBOUND**, not inferred from display names;
- source: EspoCRM, one native Lead and exact native/canonical Campaign relation;
- subject namespace: unchanged `lead:<native ID>`, restricted to **one exact ID**
  in the Owner-adopted cohort registry. Prefix/name alone never grants exemption;
- operational expiry: proposed7-day cohort lifetime after legitimate creation;
  no scheduled cleanup and no expiry of retained evidence/holds;
- no outbound channel plan, provider spend, customer contact or CRM/Sales routing;
- explicitly exclude registered cohort IDs from normal sales/revenue attribution,
  quality gates, business totals and ordinary customer SLA denominator. Verify
  exact future report behavior; a separate Campaign/name alone is insufficient.

Positive proof is a structured Owner-adopted scope registry, binding exact source
record and native creation/audit digests, canonical/native Campaign mapping,
campaign purpose, exact internal Owner/team, affirmative no real customer
relationship/obligation and report exclusion. Prefer registry/known existing native
relations over inventing CRM custom fields. Native relation availability,
notifications/workflows and scope semantics must be inspected before creation.
Metadata booleans supplied by a producer are not their own authenticity proof.

## Provenance flow

Actual internal inquiry -> separately approved native Lead creation -> original
source record ID/createdAt and creation audit -> authenticated GET-only exact
export -> privacy-safe SourceTouchpointEvent -> one operator-authorized delivery
with attempt=max_attempts1 -> existing Agent Hub intake/DB1 immutable touchpoint ->
SLA basis/policy/deadline. **Creation approval does not grant delivery or pilot**.

Required primary evidence before any future ingest approval:

1. exact native record/event ID and authenticated creating identity;
2. original record and creation audit raw bytes, signature where the source really
   supplies one, exact raw SHA256 and independent verification; do not invent a
   native source signature or treat delivery HMAC as source authenticity;
3. original createdAt projected to aware UTC under Espo's native UTC contract,
   original string preserved, no clock backdating or deadline editing;
4. exact source owner, native Campaign relation, canonical Campaign and policy15;
5. positive registry/business exemption and reporting exclusion;
6. exact exported fields/event mapping and single-event payload/subject binding;
7. signed immutable delivery/ingestion receipt and exact DB1 ledger record after
   a separately authorized ingest, plus quality/audit/key/mutation scope;
8. computed SLA basis/deadline and evaluation timestamp/raw report/API/acceptance
   evidence. No event until legitimate creation; no delivery until separate grant.

## SLA lifecycle and safe waiting

At real T0, `lead_created` starts the clock. Campaign's
`sales_handoff.first_response_sla_minutes=15`; deadline=T0+15 minutes, aware UTC.
Before and **at** deadline: absent response -> `pending`. Strictly after deadline,
absent qualifying response and no verified completeness coverage -> exactly
`overdue_missing_evidence`, not `breached`. Qualifying response within deadline ->
`met`; missing clock -> `not_evaluable` + `SLA_CLOCK_UNAVAILABLE`. Preserve the
existing evaluator and shared status/basis/report/API/browser enum contract.

Intentional waiting is allowed only after affirmative internal/no-customer
obligation disposition and exact subject registration/report exclusion. It must
not ignore a customer, create a customer SLA breach or require Sales Hub writes.
The missing-response acceptance case needs no synthetic Sales activity. Static
caseC supplies a clearly synthetic local response solely to test existing `met`
semantics; no response/source-completeness claim is created in production.

The fixture `tests/fixtures/internal_sla_cohort_design.json` is explicitly synthetic
local/static, with both decisions NOT_GRANTED. Tests use actual source/envelope
schemas and the unchanged SLA evaluator/report/API serialization/browser labels.
Passing it does not prove a production natural clock, backend scope enforcement
or authorization to create/ingest/pilot. Current cohort clock remains MISSING.

## Cleanup and custody

After pilot/expiry, a separate native close/archive disposition may close the
internal inquiry and pause/complete the Campaign. No automatic source deletion,
timestamp change, touchpoint removal or Redis restore. Preserve original source
creation audit, scope/policy/mapping, delivery receipt, task/report/audit/NBA review,
all raw/canonical captures, packages/owner grants and terminal recovery evidence.
Retention/hold lifetime follows separately adopted decision1, not7-day activity
expiry. Cleanup mutations require exact separate approval.

## Implementation/adoption prerequisites

Future source changes: typed business-scope registry; exact allowlist and owner/
Campaign/raw audit validation in a dedicated read-only Lead exporter; report and
cohort denominator exclusion; exact one-event delivery/write budget; guarded
retention/archive integration before business writes. Preserve RBAC/server denial,
SLA semantics, dual capture digests, canonical operation IDs, recovery context and
Viewer Analyze gating. These production integrations are **not implemented** by
RCA16's reference/fixtures; no currently deployed behavior changes.

## Owner decision 2 — Dedicated Internal SLA Cohort Creation

Status: **NOT_GRANTED / HOLD_NOT_PREPARED**. Separate from retention policy,
ingest, source credential authority and pilot execution.

- Exact requested disposition: adopt the legitimate internal inquiry/no-customer
  business semantics; choose exact existing Owner/native owner and approve a
  dedicated canonical/native Campaign mapping. Then review a future exact gate
  for **one** native EspoCRM Lead and **one** internal Campaign/registry only.
- Proposed writes: one native Lead plus native creation audit; one Agent Hub
  Campaign and campaign audit/index plus one exact cohort registry/mapping.
  Native Campaign setup/relation, indexes/audit and workflow side effects are
  **not yet quantified**. No mutation-count cap is fabricated. Creation gate must
  bind exact endpoint/fields/system/key/audit scope and prevent notifications,
  routing/automation/sales contamination before an executable approval exists.
- Production mutation needed later: **YES** for legitimate source/Campaign setup.
  Current task/decision preparation writes0. CRM creation by a separately
  authorized identity; GET-only Codex authority cannot do it. Sales Hub writes0.
- Prohibited: customer contact/obligation, Meta test lead, source backdating,
  direct DB1 injection, provider spend, sales/revenue contamination, retry,
  workflow/scheduler/automation, delivery/ingest, JIT/claim/stage/deploy/UAT/pilot.
- Rollback: source/Campaign close or pause by separately bound native actions;
  retain raw creation/audit and registry evidence. No blind deletion/Redis restore
  and no rewrite of historical records. Cleanup itself needs separate approval.
- Evidence: affirmative business exemption, exact Owner IDs, source UI/API and
  native audit behavior, native/canonical Campaign relation, absence of unsafe
  source workflow/contact side effects, report exclusions, retention/all-writer
  readiness, exact planned write set and new candidate CI. No actual source ID
  is fabricated before natural creation.
- Restart/deploy: ordinary native creation may need **NO** restart if existing
  source supports the approved scope; this is unverified. Agent Hub scope/export/
  reporting/retention implementation requires a **separately gated deployment**
  before ingest. This decision grants neither deploy nor an execution window.

NEXT_SAFE_ACTION: Owner review **two separate dispositions** and unresolved backend/
business/source side-effect bindings; then separately authorize implementation and
exact creation-gate preparation. No JIT or ingest in this task.
