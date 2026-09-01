# Phase 9B — Sales SLA and Funnel Evidence

## Scope

This increment closes the remaining Phase 9 Sales Intelligence evidence gap without enabling external execution.

It adds a deterministic, non-persisting preview that combines:

1. the existing immutable journey/touchpoint ledger for the lead start and Campaign ID;
2. Campaign OS `sales_handoff` policy (`first_response_sla_minutes`, `visit_booking_sla_hours`);
3. explicit PII-free Sales Hub activity observations supplied under `phase-9b-sales-activity-v1`.

No production Sales Hub connector is assumed by this increment.

## Sales activity contract

Supported observations are:

- `first_response`
- `appointment_booked`
- `site_visit_completed`

Each observation must contain a pseudonymous activity/source reference, timezone-aware event time, Campaign ID and lead or opportunity ID. `external_writes_enabled` is permanently false.

Only normalized Sales Hub sources (`Sales Hub`, `SaleHub`, `NPD Sales Hub`) are authoritative in v1. Source, subject or Campaign mismatches are excluded and counted as untrusted evidence.

## SLA clocks

The lead clock starts from the earliest `lead_created` touchpoint. `form_submit` is used only as an explicit fallback when no `lead_created` evidence exists.

Campaign OS remains the policy authority:

- first response target: `campaign.sales_handoff.first_response_sla_minutes` (currently default 15 minutes);
- visit-booking target: `campaign.sales_handoff.visit_booking_sla_hours` (currently default 24 hours).

Observed activity can produce `met` or `late`.

When activity is missing:

- before deadline -> `pending`;
- after deadline -> `overdue_missing_evidence`.

`overdue_missing_evidence` is deliberately **not** called a confirmed breach because this preview does not prove Sales Hub source completeness. Missing source data is reported as missing, not converted into a negative signal.

## Funnel evidence

The snapshot reports the earliest accepted evidence for:

- first response;
- appointment booked;
- site visit completed.

The snapshot is deterministic, duplicate-aware, PII-free and carries only evidence references.

## API

`POST /api/v1/sales-intelligence/preview`

- operator/owner only;
- 0–500 activity observations;
- timezone-aware `as_of` required;
- response has `Cache-Control: no-store` through the existing API security middleware;
- no persistence or external call is performed.

## Safety boundary

Every snapshot requires:

- `source_complete=false`;
- `persisted=false`;
- `shadow_mode=true`;
- `execution_enabled=false`;
- `external_writes_enabled=false`;
- `customer_contact_enabled=false`;
- `contains_raw_pii=false`.

There is no `/execute`, `/contact`, `/send` or `/accept` route.

## Deferred work

A later increment may add a real read-only Sales Hub adapter and completeness/heartbeat evidence. Only after completeness is proven should missing activity be eligible to become a confirmed SLA breach or a score/NBA negative signal.

Lead Score and NBA are intentionally unchanged in this increment; `sales_sla` remains a missing score input until the source-completeness gate exists.
