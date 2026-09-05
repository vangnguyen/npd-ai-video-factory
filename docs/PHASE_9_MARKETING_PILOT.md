# Phase 9 — Marketing/Sales internal review pilot

## Purpose and scope

Complete the existing Customer Journey and Sales Intelligence roadmap by making its
services usable through the existing Commander task/report flow. Do not replace the
Agent Hub architecture, add another agent platform, or turn V1 deployment scheduling
into a prerequisite for this source-only product slice.

Source baseline inspected: `82fd18a3e524b13b479bb73d66c962620c6e8d9b` (PR #61).
This document describes a source candidate and proposed business pilot, not a live
production release or proof that production data is ready.

## Implemented slice

An explicit `context.phase9_review` task routes through existing role identities:

1. **CRM Manager** reads Journey and identifies missing/untrusted local evidence.
2. **Sales** uses the existing SalesIntelligenceService, LeadScoringService and
   SalesAwareNextBestActionService. It does not replace their score/SLA/NBA policies.
3. **Marketing Leader** consumes those results and orders internal review suggestions
   by the existing NBA priority; it does not fetch providers or re-score subjects.
4. **Commander** persists and returns the existing CommandCenterReport/BusinessAnswer.

This is deterministic, service-backed role coordination. It is not a claim that new
LLM agents, autonomous handoffs, or production provider calls have been introduced.
Other task modes retain their existing routing and behavior.

## Input and output

Use the existing operator/owner endpoint `POST /api/v1/agent-tasks`.
`context.phase9_review` contains the existing `Phase9SalesShadowEvaluationRequest`
contract with at most 20 cases for the pilot. No other tool/provider context is accepted
in this mode. All cases share the same timezone-aware `as_of`; identical duplicates are
counted once and conflicting duplicates are rejected.

Example shape only (replace refs/time with approved data; this does not seed evidence):

```json
{
  "objective": "Rà soát hồ sơ cần Marketing và Sales xem xét",
  "context": {
    "phase9_review": {
      "cases": [
        {
          "subject_ref": "lead:approved-reference",
          "observations": [],
          "as_of": "2026-09-06T12:00:00+00:00"
        }
      ]
    }
  }
}
```

The existing signed Sales Hub `completeness_proof` may be supplied when genuinely
available. Do not manufacture a proof, source stage or review vote for a live pilot.
A missing/unverified proof remains missing/unverified; it cannot establish a confirmed
SLA breach. A missing Journey produces a bounded missing-evidence item with no invented
score. Results may remain `partial` because the existing policies report missing fit,
source-quality or engagement context.

The response includes the three role reports, a Vietnamese business summary, pseudonymous
subject refs, Journey state, Score, NBA v2 reason/priority, first-response/visit-booking
SLA, completeness state, missing inputs and evidence refs. Score is not a purchase
probability. `generated_at` is report creation time; `as_of` is evaluation time under
existing Phase 9 semantics, not an immutable historical snapshot.

Existing `GET /api/v1/agent-tasks/{task_id}`, re-analyze and Command Center report rendering
remain the read surfaces. The first slice is API-led; it does not yet add a dedicated
Phase 9 task-input preset to the browser composer. Do not claim click-only onboarding
until that input flow has been implemented and browser-tested.

## Persistence and execution boundaries

The existing internal task/report/audit records are written. Evidence inputs in this mode
are normalized through the existing model before task persistence. Never place customer
names, phones, emails or credentials in task free text/context.

The review services do not ingest touchpoints, issue heartbeat receipts, record reviewer
votes, call providers or dispatch ToolExecutor actions. They propose no executable
contact/Ads/CMS actions. `execution_enabled`, `external_writes_enabled` and
`customer_contact_enabled` remain false in this pilot result.

No source-system CRM write, message, advertising change, CMS publication, render job,
production deployment or scheduler/clock modification is part of this change. This
pilot does not use the AH-T01 PRE_TRIGGER/E+A package or its production approval.

## Reproducible non-production check

From the repository checkout with its existing development dependencies:

```sh
cd services/agent_hub
python -m pytest tests/test_phase9_marketing_review.py -q
python -m pytest tests -q
agent-hub-eval
```

The focused tests use the existing signed-sales fixture and real Phase 9 services,
MemoryHubStore/fakeredis, and the real FastAPI task routes. The external executor raises
on any dispatch. Tests cover signed breach, missing/unverified completeness, missing
Journey, duplicate/conflicting inputs, input privacy, bounded batch size, role routing,
RBAC, re-analysis, internal persistence and Redis recovery. No real customer data or
provider credentials are required.

CI results must be reported from the actual run, separately from business UAT and live
production acceptance. A fixture PASS is not production-quality acceptance.

## Next steps within Phase 9

- Review this source change and its protected CI; do not merge unrelated refactor or
  Video Factory draft PRs as a side effect.
- Add a small browser input preset for the same validated task contract, rather than a
  second dashboard/service. Test operator input, viewer read-only access, missing-data
  display and an end-to-end report view.
- For an owner-approved pilot environment, verify real EspoCRM stage mapping and Sales
  Hub evidence availability. Start with an approved pseudonymous cohort of up to 20
  cases. Keep source access and deployment permissions separate from this code change.
- Have Marketing/Sales review the results using the existing NBA v2 review endpoints.
  Measure decided/relevant/not_relevant/needs_more_context, evidence coverage and actual
  time to review versus the previous process. No fabricated conversion/revenue uplift.
- Accept Phase 9 for internal use only after source accuracy, usable output, role access,
  internal persistence and no external side effects have been verified in that pilot.

Issue #28 is closed as completed in GitHub; its historical description must not be
reported as an open issue. Live source readiness still needs a fresh check when the
pilot is deployed. Historical PR #30–#36 remain outside this change; no dispositions or
merge approvals are implied here.

## Product roadmap, unchanged

- **Phase 9:** finish the internal Journey/Score/NBA workflow and evidence-backed UAT.
- **Phase 10:** choose and accept one controlled channel capability at a time (Meta Ads,
  Google Ads, Email provider, Zalo/ZBS provider, WordPress publisher).
- **Phase 11:** controlled creative experiments, landing CRO and reviewed rollout/rollback.
- **Phase 12:** revenue cockpit, executive brief, AI/API cost governance and evidence-based
  portfolio decisions.

AH-T01B telemetry, AH-R01 Redis independence, backup custody, V2/V3 bridge and V1 retirement
remain a separate infrastructure/migration track. Their real dependencies and approvals
are not waived. Scheduler/Windows-clock work is not expanded by this pilot. No percentage
completion is inferred from the number of technical checks or PRs.
