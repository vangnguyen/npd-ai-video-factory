# Phase 9B — SLA-aware Lead Scoring Preview

## Purpose

Phase 9A Lead Scoring v1 is a deterministic journey-momentum score using journey state, trusted evidence recency and engagement frequency. It intentionally reports `sales_sla` as missing.

Phase 9B now has a signed Sales Hub completeness gate that can distinguish observed SLA outcomes and cryptographically supported `breached` outcomes from ordinary missing data.

This increment adds SLA-aware scoring **only through a separate preview**. The existing viewer GET Lead Score v1 remains unchanged for backward compatibility and for the existing Next Best Action v1 service.

## Existing v1 remains unchanged

`GET /api/v1/lead-scores/{subject_ref}` continues to return:

- methodology: `journey_momentum_v1`;
- score version: `phase-9a-score-v1`;
- factors: `journey_state`, `recency`, `engagement_frequency`;
- `sales_sla` as a missing input.

No SLA evidence can alter this existing GET response.

## SLA-aware preview

`POST /api/v1/lead-scores/sales-preview`

- operator/owner only;
- request body is the existing `SalesIntelligencePreviewRequest`;
- the server computes Sales Intelligence itself through the existing signed completeness verifier;
- callers cannot directly submit a trusted `SalesIntelligenceSnapshot` or set `completeness_verified=true`;
- output combines the computed Sales Intelligence snapshot and Lead Score v2;
- non-persisting and `Cache-Control: no-store`.

The SLA-aware score uses:

- methodology: `journey_momentum_with_sales_sla_v2`;
- score version: `phase-9b-score-v2`.

## Factor capacity

The existing factors keep their original capacities:

- journey state: 70;
- recency: 20;
- engagement frequency: 10.

Two bounded SLA factors may be added:

- first-response SLA: 6;
- visit-booking SLA: 9.

The score remains normalized only across **observed** factors.

## SLA contribution policy

An SLA factor can be numeric only when the Sales activity batch is bound to a verified signed Sales Hub completeness proof.

For a verified batch:

| SLA status | First response | Visit booking |
|---|---:|---:|
| `met` | 6/6 | 9/9 |
| `late` | 2/6 | 3/9 |
| `breached` | 0/6 | 0/9 |
| `pending` | missing | missing |
| `overdue_missing_evidence` | missing | missing |
| `not_evaluable` | missing | missing |

`breached` is an observed zero-point factor because the signed completeness proof confirms that the relevant deadline was covered and no qualifying activity exists.

`overdue_missing_evidence` remains missing data because the absence is not proven. It does not enter the denominator and cannot reduce the score.

If completeness verification is absent or invalid, both SLA factors remain missing even if the supplied activity rows appear to show `met` or `late`. This prevents unsigned activity input from changing Lead Score.

## Evidence and explainability

Observed SLA factors cite:

- activity evidence references when present; and
- the verified heartbeat receipt ID that binds the activity batch/completeness claim.

The preview reports factor status, contribution, capacity, bounded reason, missing inputs and caveats.

The existing fairness boundary remains:

- no protected/sensitive traits are inferred or used;
- missing data is excluded rather than treated as negative behavior;
- score is a deterministic prioritization index, not a conversion probability.

## Safety boundary

The SLA-aware preview requires:

- `persisted=false`;
- `shadow_mode=true`;
- `execution_enabled=false`;
- `external_writes_enabled=false`;
- `customer_contact_enabled=false`;
- `contains_raw_pii=false`.

It performs no CRM/Sales Hub write, customer contact, Ads mutation, notification, CMS publication, n8n execution or production deployment.

## Deferred work

Next Best Action remains on Lead Score v1 in this increment. A later, separate recommendation preview may consume SLA-aware score and verified SLA status to adjust **internal review priority only**; it must not execute, send, call, contact or update CRM.
