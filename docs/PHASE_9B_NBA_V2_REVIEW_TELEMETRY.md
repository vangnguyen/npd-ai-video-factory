# Phase 9B NBA v2 review telemetry

## Status

Source-readiness increment only. No production deployment or execution activation is part of this change.

This increment closes the reviewer-feedback gap introduced when Phase 9B added SLA-aware `phase-9b-nba-v2`. Phase 9A review telemetry remains version-bound to `phase-9a-nba-v1`; Phase 9B telemetry is collected and summarized separately.

## Review APIs

Phase 9A remains unchanged:

- `POST /api/v1/next-best-actions/reviews`
- `GET /api/v1/next-best-actions/reviews`
- `GET /api/v1/next-best-actions/reviews/summary`

These surfaces expose only `phase-9a-nba-v1` review records.

Phase 9B adds:

- `POST /api/v1/next-best-actions/reviews/sales`
- `GET /api/v1/next-best-actions/reviews/sales`
- `GET /api/v1/next-best-actions/reviews/sales/summary`

These surfaces expose only `phase-9b-nba-v2` review records.

## Server-side recomputation

A Phase 9B review request contains the same `SalesIntelligencePreviewRequest` used by the SLA-aware preview chain plus reviewer disposition/note. The server recomputes:

1. signed Sales Hub completeness and SLA outcome;
2. Lead Score `phase-9b-score-v2`;
3. recommendation-only NBA `phase-9b-nba-v2`;
4. the immutable review record.

The reviewer cannot provide or override a precomputed recommendation, priority, score, completeness flag, or recommendation version.

## Persistence and compatibility

The existing `NBAReviewRecord` already stores `recommendation_version`. Therefore Phase 9B uses the existing bounded Memory/Redis repository without a Redis schema migration or a second review store.

Version filtering is performed on the bounded retained review set. Redis subject indexes remain hashed; raw subject references are not added to index keys.

## Aggregate evaluation

`POST /api/v1/phase9/sales-shadow-evaluation/preview` advances to `phase-9b-sales-shadow-eval-v2` and adds only aggregate NBA v2 review metrics:

- reviewed subject count;
- total reviews;
- relevant;
- not relevant;
- needs more context;
- false-positive rate (`not_relevant / (relevant + not_relevant)`).

Only `phase-9b-nba-v2` reviews are counted. Phase 9A reviews are explicitly excluded. The response remains aggregate-only and contains no subject IDs or per-subject outcomes.

## Safety boundary

Review telemetry records judgement only. It does not accept, execute, send, call, contact, publish, mutate Ads, create a Sales task, update CRM/Sales Hub, or activate n8n execution.

All review records retain:

- `recommendation_executed=false`;
- `execution_enabled=false`;
- `external_writes_enabled=false`;
- `customer_contact_enabled=false`;
- `contains_raw_pii=false`.

Reviewer notes reject raw email/phone contact data.

## Acceptance

Acceptance requires:

- NBA v2 review creation recomputes the recommendation server-side;
- viewer cannot create a review;
- operator/owner can record a bounded disposition;
- v1 and v2 lists/summaries remain isolated by recommendation version;
- Phase 9B aggregate false-positive metrics use v2 reviews only;
- Phase 9A aggregate review metrics remain v1-only;
- no touchpoint, heartbeat, task, CRM/Sales Hub or customer-contact side effect;
- no `/accept`, `/execute`, `/send`, or `/contact` review route;
- full protected CI and Docker E2E pass.

## Operational boundary after merge

After source merge and exact-main CI, Phase 9 can be considered source-ready for a separately owner-gated production-shadow plan. Production-shadow activation still requires real Sales Hub completeness generation, credentials/secrets configuration, operational monitoring/rollback gates, a bounded evaluation window and explicit owner approval. Phase 10 execution remains out of scope.
