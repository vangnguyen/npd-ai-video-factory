# Phase 9B — Aggregate SLA-aware Shadow Evaluation

## Purpose

Phase 9B now has a complete source-side chain for shadow decision support:

`Journey -> signed Sales SLA -> Lead Score v2 -> recommendation-only NBA v2`

This increment adds the final aggregate evaluation layer required before any production-shadow activation is considered.

It does not create per-lead reports, persist evaluation output, execute recommendations, or change the existing Phase 9A shadow-evaluation contract.

## Existing Phase 9A endpoint remains unchanged

`POST /api/v1/phase9/shadow-evaluation/preview`

continues to evaluate Journey + Lead Score v1 + NBA v1 and remains versioned as `phase-9a-shadow-eval-v1`.

Phase 9A review telemetry is not mixed into Phase 9B recommendation metrics because no Phase 9B NBA review contract exists yet.

## Phase 9B aggregate endpoint

`POST /api/v1/phase9/sales-shadow-evaluation/preview`

- operator/owner only;
- accepts 1–200 `SalesIntelligencePreviewRequest` cases;
- every case must use the same timezone-aware `as_of` instant;
- repeated cases for the same subject are allowed only when byte-identical;
- conflicting duplicate subject cases fail closed;
- output is aggregate-only and intentionally contains no subject IDs.

The server computes, per case and only internally:

1. Customer Journey projection;
2. signed Sales Intelligence/SLA verification;
3. Lead Score `phase-9b-score-v2`;
4. recommendation `phase-9b-nba-v2`.

No per-subject result is returned.

## Aggregate metrics

The report contains only bounded aggregate statistics:

- requested/unique/duplicate/evaluated/failed counts;
- failures grouped by bounded category;
- Journey state distribution;
- first-response SLA status distribution;
- visit-booking SLA status distribution;
- completeness-verified count;
- source-complete count;
- verified-breach subject count;
- verified-late subject count;
- Lead Score v2 band distribution and average;
- NBA v2 action/priority distribution and average confidence;
- missing-input counts;
- subjects with untrusted Journey evidence;
- cases with duplicate/untrusted Sales activity evidence.

Failure categories do not emit underlying subject IDs or exception strings.

## Duplicate semantics

Identical duplicate cases are de-duplicated for evaluation and counted separately.

If the same subject appears with different observations, completeness proof, or evaluation content, the request is rejected rather than selecting one version implicitly. This avoids hiding conflicting Sales evidence inside an aggregate result.

## Review telemetry boundary

Existing NBA review telemetry is tied to Phase 9A recommendation behavior. Phase 9B NBA v2 does not yet have its own review/outcome contract.

Therefore this report deliberately does **not** reuse Phase 9A false-positive rates as if they represented NBA v2 quality. The absence is reported as a caveat.

A future shadow-observation increment may add version-bound NBA v2 review telemetry without adding execution capability.

## Safety boundary

Every report requires:

- `aggregate_only=true`;
- `contains_subject_ids=false`;
- `persisted=false`;
- `shadow_mode=true`;
- `execution_enabled=false`;
- `external_writes_enabled=false`;
- `customer_contact_enabled=false`;
- `contains_raw_pii=false`.

The evaluation performs no CRM/Sales Hub write, customer contact, Ads mutation, notification, CMS publication, n8n execution, or production deployment.

This closes the Phase 9B **source-readiness** loop. Production shadow activation remains a separate owner-gated operational step and requires a real Sales Hub producer/adapter, signed completeness publishing, production configuration, and an observation/quality acceptance plan.
