# Phase 9B — SLA-aware Next Best Action Preview

## Purpose

Phase 9A Next Best Action v1 remains a deterministic recommendation-only policy over Customer Journey and Lead Score v1.

Phase 9B adds signed Sales Hub completeness and SLA-aware Lead Score v2. This increment allows that verified SLA context to influence **internal review priority and internal review timing only**.

It does not add any customer-facing execution capability.

## Existing NBA v1 remains unchanged

The following existing surfaces continue to use `phase-9a-nba-v1` and Lead Score v1:

- `GET /api/v1/next-best-actions/{subject_ref}`
- `POST /api/v1/next-best-actions/preview`

They do not consume Sales SLA preview state.

## SLA-aware NBA v2 preview

`POST /api/v1/next-best-actions/sales-preview`

- operator/owner only;
- accepts the existing `SalesIntelligencePreviewRequest`;
- server computes Sales Intelligence through the signed completeness verifier;
- server computes Lead Score `phase-9b-score-v2`;
- server computes recommendation `phase-9b-nba-v2`;
- non-persisting and `Cache-Control: no-store`.

The request cannot directly submit a trusted Sales Intelligence snapshot or a precomputed Lead Score.

## Closed action set

NBA v2 reuses the existing recommendation-only action enum. It does **not** add send/call/contact/execute/update actions.

The primary early-stage action remains:

`review_sales_follow_up`

Other journey-specific review actions remain unchanged for appointment, site visit, negotiation, won, customer, lost and reengagement states.

## SLA escalation policy

Direct SLA escalation applies only while the Journey is in an early Sales state:

- `lead`
- `engaged`
- `mql`
- `sql`

and only when Sales completeness is verified.

### Verified breach

If either first-response or visit-booking SLA is `breached`:

- recommendation: `review_sales_follow_up`;
- priority: `high`;
- internal-review SLA: at most 15 minutes;
- channel: `sales_task_review`.

This is an internal management escalation. It does not schedule or perform customer contact.

### Verified late activity

If no breach exists but at least one SLA is `late`:

- recommendation: `review_sales_follow_up`;
- priority: at least `medium`;
- internal-review SLA: at most 60 minutes.

### No verified negative SLA signal

`met`, `pending`, `overdue_missing_evidence`, `not_evaluable`, absent proof or invalid proof do not trigger direct SLA escalation.

SLA-aware Lead Score v2 may still influence the normal score thresholds, but unverified/missing SLA factors remain outside the score denominator.

## Later journey states

Appointment, site visit, negotiation, won, customer, lost and reengagement keep their existing journey-specific review action semantics. Historical Sales SLA data does not replace the current journey-specific action with an early-stage follow-up action.

## Evidence and context

NBA v2 cites evidence references from Lead Score v2, including signed heartbeat receipt IDs when an SLA factor is observed.

Campaign and project context come from the server-computed Sales Intelligence snapshot rather than being inferred from free text.

## Safety boundary

Every SLA-aware NBA preview remains:

- recommendation-only;
- `sla_scope=internal_review_only`;
- `persisted=false` at the preview envelope;
- `shadow_mode=true`;
- `execution_enabled=false`;
- `external_writes_enabled=false`;
- `customer_contact_enabled=false`;
- `contains_raw_pii=false`.

There is no `/execute`, `/accept`, `/send` or `/contact` route.

The preview performs no CRM/Sales Hub write, customer message/call/email, Ads mutation, notification, CMS publication, n8n execution or production deployment.
