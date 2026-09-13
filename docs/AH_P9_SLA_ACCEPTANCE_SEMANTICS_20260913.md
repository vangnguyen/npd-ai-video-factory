# AH-P9-RCA-12A — SLA Acceptance Semantics

The recovered pilot's SLA result was correct. Its acceptance case was not eligible
for the asserted overdue result: the selected opportunity had only one
`opportunity_stage_changed` event, without `lead_created` or `form_submit` evidence.
Campaign OS supplied the 15-minute policy, but there was no first-response clock
start or computable deadline. `not_evaluable` and `overdue_missing_evidence` are
different business results and remain different.

## Exact provenance and reproduction

- Source baseline: `75cc44e45a41a09b0a82e383a5d6ae51e9186ce2`.
- Recovered operation: `PHASE9-LIMITED-PILOT-RCA06-75f186d4-7f51-4e12-8d28-e26c1ee7d7d9`.
- Retained task: `agt_a1222f1de3bb41fe`; retained review: `nbar_efc380ff75d7427898e9fb6e`.
- Case: `opportunity:6a881aa4bb9606e32`, `as_of=2026-09-13T13:16:00Z`,
  `observations=[]`, `completeness_proof=null`.
- Sole touchpoint: `tpt_a7dcf7ca2f52df45ee25bf2b6d77d2e1`,
  `opportunity_stage_changed`, `2026-08-21T10:46:27Z`, authoritative EspoCRM source.
- Campaign: `CMP-VGP-VINHTIEN-202609-01`; first-response policy 15 minutes,
  visit-booking policy 24 hours.
- Recovery handoff SHA-256: `896bba21043e39d74a4e00073ae95e465e5393d8d964294b03f4b0c2bbb368a7`.
- Recovery receipt SHA-256: `ffff88417237fd1507a56651693a9e8c63f457ef593312e417dec8c799a6fbd8`.
- Post-recovery read evidence SHA-256: `423556e8341c9eddf97b9311f733cb510822b893a67cdea711cf0fb356eb1495`.
- Production-shaped fixture SHA-256: `e3fd8e010b5ec4b8951ece83a1dfe39ad2b147f9d0ee4d54ef75e1f54957dc3c`.

The fixture preserves the exact stored case and SLA-relevant touchpoint/policy
fields. Campaign display/budget fields are synthetic; unrelated touchpoint metadata
is omitted. The new read is a read-only observation of the retained records, not a
new UAT run. All six record DUMP hashes match the original recovery custody.

## Decision path and business rule

`task.context.phase9_review` → validated case → subject touchpoints → earliest
`lead_created` (or explicit `form_submit` fallback) → Campaign OS handoff policy →
`SalesIntelligenceService._window` → `SalesSLAStatus` → report `.status.value` →
API JSON → remote allowlisted UAT detail → sealed acceptance assertion.

Task creation, answer generation, audit timestamps, negotiation state and NBA
`internal_review_minutes` are not first-response clock evidence. An old opportunity
stage timestamp cannot silently become a lead-created timestamp.

With a qualifying clock and policy:

- Qualifying activity within the target: `met`; after the target: `late`.
- No qualifying activity and `as_of <= deadline`: `pending` (equality is not overdue).
- No qualifying activity and `as_of > deadline`, without verified signed source
  completeness covering that deadline: `overdue_missing_evidence`.
- Only verified signed completeness covering the missing activity deadline permits
  `breached`; absent, stale, mismatched or tampered completeness does not.
- Missing clock or policy: `not_evaluable`, with no invented deadline.

The original sealed `pilot_uat.py` demanded `overdue_missing_evidence` without
checking clock eligibility. Its browser truthfulness check simultaneously demanded
`NOT_AVAILABLE_NOT_EVALUABLE`. The report dropped the clock/deadline basis, so the
consumer could not distinguish the valid missing-clock result from an evaluator bug.

## Minimum responsible-layer fix

The evaluator's clock selection, deadline ordering and completeness rules are
unchanged. The existing enum is exported from one dependency-free shared contract;
its values and existing model import path are compatible.

The internal report carries additive, PII-free clock, policy, target, deadline,
observation, evaluation time, coverage and reason fields. The UAT sanitizer retains
exactly those fields. The acceptance consumer loads that same contract (the final
package must copy the service module byte-for-byte and bind it in all manifests),
checks the report's status against its inputs, and aligns browser/API labels.

Truthfulness and business acceptance coverage are checked independently.
`SLA_CLOCK_UNAVAILABLE` is a truthful `not_evaluable` result and **does not pass**
the required overdue case. `sla_acceptance_overdue_missing_evidence` remains a
mandatory check. A missing-clock cohort therefore still fails business acceptance,
now with its exact reason. Status remaps, missing deadlines, wrong policy/clock
basis, changed evaluation time and unsupported/stale schema are rejected.

## Limits and next review

No historical UAT result, source/package bytes or approval is rewritten. Old receipts
without the new explicit basis remain rejected by the new consumer; operation,
approval, TTL, raw/canonical digest, package and recovery guards remain mandatory.
All local valid/invalid cases run without external tools or providers.

Static candidate preparation does not adopt or authorize execution. No DB0 read,
operation, execution window, approval, claim, stage, deploy or production mutation
is performed. The current cohort lacks authentic SLA-start evidence; full Phase 9
business acceptance remains incomplete. The separate Viewer shared Analyze issue
is retained for a separate scoped task and is not changed here.

NEXT_SAFE_ACTION: OWNER REVIEW + STATIC CANDIDATE ADOPTION.
