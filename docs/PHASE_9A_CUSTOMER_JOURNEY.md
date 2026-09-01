# Phase 9A — Customer Journey read-only foundation

## Scope

This increment implements the first two delivery stages of the approved Phase 9 architecture:

1. a privacy-safe source/evidence contract over the existing immutable Attribution OS touchpoint ledger;
2. deterministic read-only journey replay.

It does **not** implement Lead Scoring, Next Best Action, CRM writes, customer contact, Ads mutation, notification delivery, CMS publishing, or any autonomous execution.

## Canonical states

The shared Phase 9 state vocabulary remains:

`anonymous -> lead -> engaged -> MQL -> SQL -> appointment -> site_visit -> negotiation -> won -> customer`

`lost` and `reengagement` remain reserved states for later authoritative evidence contracts.

The first replay rule set only advances states when existing touchpoint types provide direct evidence:

- `form_submit` / `lead_created` -> `lead`;
- `ad_click` / `landing_view` -> `engaged` only after lead evidence already exists;
- `opportunity_created` -> `sql`;
- `opportunity_stage_changed` -> `negotiation`;
- `sale_closed` -> `won`.

The engine never invents MQL, appointment, site visit, customer, lost or reengagement evidence. Direct later-stage evidence may skip intermediate states; skipped states are explicitly reported on the transition rather than inferred.

## Subject identity and privacy

Journey lookup accepts only pseudonymous references in one of these forms:

- `lead:<id>`
- `opportunity:<id>`

Raw email addresses and phone-like identifiers fail closed. Projection output contains evidence references and campaign/source metadata but no raw contact PII.

## Deterministic replay

- replay order is `(occurred_at, event_id)`, independent of ingestion order;
- lower/equal state evidence cannot regress the current state;
- pre-lead engagement remains evidence but does not invent a lead transition;
- repeated/late evidence can be suppressed as a transition while remaining visible as evidence;
- every transition records source event, observed time, reason, confidence, skipped states and rule version;
- projection output reports missing state signals rather than silently inferring them.

## Safety boundary

Every `JourneyProjection` is permanently emitted with:

- `shadow_mode=true`;
- `execution_enabled=false`;
- `external_writes_enabled=false`;
- `contains_raw_pii=false`.

This increment adds no execution endpoint and no write path.

## Acceptance for this increment

- deterministic replay from out-of-order touchpoint insertion;
- monotonic state transitions;
- explicit skipped-state reporting;
- pre-lead engagement retained without invented conversion;
- pseudonymous subject validation and raw-contact rejection;
- no production writes or customer contact;
- existing Agent Hub/business evaluation/CI gates remain required before merge.

## Next Phase 9A increments

After this service-level foundation is accepted:

1. add viewer-only Journey read/history APIs with RBAC and OpenAPI parity coverage;
2. add authoritative Sales Hub / EspoCRM evidence contracts for appointment, site visit, won/lost/customer states;
3. add Redis-backed derived projection snapshots only if needed for performance, without duplicating raw PII;
4. start deterministic explainable Lead Scoring as a separate owner-reviewed increment;
5. keep Next Best Action recommendation-only and `execution_enabled=false` until Phase 10.
