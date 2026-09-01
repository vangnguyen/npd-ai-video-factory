# Phase 9A — Aggregate Shadow Evaluation Report

## Purpose

This increment closes the Phase 9A source-readiness loop by evaluating a bounded set of pseudonymous subjects through:

1. Customer Journey projection;
2. Explainable Lead Score v1;
3. recommendation-only Next Best Action v1;
4. existing NBA shadow-review telemetry.

The result is aggregate-only. It is intended for shadow validation and business review before any Phase 10 execution capability exists.

## API

`POST /api/v1/phase9/shadow-evaluation/preview`

Request:

- 1–200 pseudonymous `lead:<id>` / `opportunity:<id>` references;
- required timezone-aware `as_of` for deterministic recency/scoring.

The endpoint is operator/owner only because it can evaluate a bounded batch of internal subjects. It performs no provider call and no external write.

## Response privacy boundary

The response intentionally contains **no subject IDs**.

It returns only aggregate counts/statistics:

- requested, unique, duplicate, evaluated and failed counts;
- failures grouped by bounded category (`not_found`, `no_trusted_evidence`, `evaluation_error`);
- journey-state distribution;
- score-band distribution;
- average Lead Score;
- average NBA confidence;
- recommendation action/priority distributions;
- missing-input coverage counts;
- count of evaluated subjects containing untrusted journey evidence;
- aggregate review dispositions and false-positive rate.

No per-subject row, failure ID, recommendation or score is returned.

## Score bands

The report uses descriptive aggregate bands only:

- `low_0_49`
- `medium_50_69`
- `high_70_100`

These are buckets of the deterministic journey-momentum score. They are not conversion-probability labels and must not be used to autonomously discard leads.

## Review metric

For selected subjects, existing shadow reviews are aggregated as:

- relevant;
- not relevant;
- needs more context;
- false-positive rate = `not_relevant / (relevant + not_relevant)`.

`needs_more_context` remains visible but is excluded from the denominator.

## Determinism

Given the same immutable evidence, same review records, same Phase 9 model versions and same timezone-aware `as_of`, the aggregate output is deterministic.

Duplicate subject references are de-duplicated before evaluation. The response reports how many duplicate request entries were removed.

## Failure handling

Failures never echo the subject reference or underlying exception text. They are grouped into a small closed reason taxonomy so the report cannot leak subject identifiers through an error list.

## Safety flags

Every report requires:

- `aggregate_only=true`
- `contains_subject_ids=false`
- `persisted=false`
- `shadow_mode=true`
- `execution_enabled=false`
- `external_writes_enabled=false`
- `customer_contact_enabled=false`
- `contains_raw_pii=false`

## Non-mutation guarantee

The preview does not:

- add or modify touchpoints;
- add or modify NBA reviews;
- create Agent Hub tasks/approvals/executions;
- write CRM or Sales Hub;
- message/call/email customers;
- mutate Ads;
- publish CMS content;
- trigger n8n execution;
- persist the report.

## Acceptance

- raw contact subject refs fail closed;
- timezone-naive evaluation time fails closed;
- duplicate request subjects are evaluated once;
- missing subjects produce aggregate failure counts only;
- response serialization contains no supplied subject IDs;
- report totals reconcile exactly with distributions;
- untrusted evidence is counted but retains the underlying score/NBA trust boundary;
- review false-positive aggregation is deterministic;
- touchpoint/review/task stores remain unchanged;
- operator-only API and preview-only OpenAPI surface;
- all Agent Hub/business-eval/Phase 5 gates pass before merge.

## Phase 9A status after this increment

Source implementation now covers:

- deterministic Customer Journey replay;
- authoritative Sales Hub/EspoCRM evidence contract;
- viewer Journey APIs;
- explainable Lead Scoring and viewer API;
- recommendation-only NBA and non-persisting preview API;
- PII-free reviewer relevance/false-positive telemetry;
- explicit-map EspoCRM journey evidence preview;
- aggregate shadow evaluation report.

Production activation, live stage mapping, Sales Hub connector configuration and any external action remain separate owner-gated work.
