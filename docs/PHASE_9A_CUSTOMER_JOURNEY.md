# Phase 9A — Customer Journey read-only foundation

## Scope

Phase 9A builds a privacy-safe, read-only Customer Journey projection over the existing immutable Attribution OS touchpoint ledger.

The current stacked implementation contains:

1. a deterministic replay engine and evidence model;
2. viewer-only Journey projection/history APIs;
3. a versioned Sales Hub/EspoCRM stage-evidence contract with source authority checks.

It does **not** implement Lead Scoring, Next Best Action, CRM writes, customer contact, Ads mutation, notification delivery, CMS publishing, or autonomous execution.

## Canonical states

The shared Phase 9 state vocabulary is:

`anonymous -> lead -> engaged -> MQL -> SQL -> appointment -> site_visit -> negotiation -> won -> customer`

with the explicit branch:

`... -> lost -> reengagement`

Existing immutable touchpoint evidence advances these states directly where the semantics are already authoritative:

- `form_submit` / `lead_created` -> `lead`;
- `ad_click` / `landing_view` -> `engaged` only after lead evidence already exists;
- `opportunity_created` -> `sql`;
- plain `opportunity_stage_changed` -> `negotiation`;
- plain `sale_closed` -> `won`.

Direct later-stage evidence may skip intermediate states; skipped states are reported on the transition and in `missing_signals` rather than inferred.

## Versioned sales-stage evidence

Operational evidence can carry a nested metadata object:

```json
{
  "journey_evidence": {
    "contract_version": "phase-9a-sales-v1",
    "state": "appointment",
    "source_record_ref": "appt-123",
    "external_writes_enabled": false
  }
}
```

The contract accepts only:

- `mql`;
- `appointment`;
- `site_visit`;
- `lost`;
- `customer`;
- `reengagement`.

It is permitted only on existing opportunity-stage or sale-close touchpoints. `source_record_ref` must remain pseudonymous; raw contact data and any enabled external-write flag fail closed.

### Source authority policy

- `mql`, `appointment`, `site_visit`, `reengagement`: Sales Hub or EspoCRM;
- `lost`, `customer`: EspoCRM only.

Source names are normalized for bounded aliases such as `Sales Hub`, `SaleHub`, `NPD Sales Hub`, `EspoCRM` and `Espo CRM`.

Evidence carrying a valid stage declaration from an unapproved source remains visible in the projection but receives `authority_status=rejected_source` and cannot change journey state. Malformed/version-mismatched declarations receive `authority_status=invalid_contract` and also cannot fall back to an ordinary stage transition.

## Branch and regression rules

- `lost` cannot replace `won`, `customer`, `reengagement` or an existing `lost` state;
- `reengagement` requires an existing `lost` or `customer` state;
- ordinary linear events cannot silently move a subject out of `lost` or `reengagement`;
- `customer` may follow authoritative `won` evidence;
- lower/equal state evidence is retained but cannot regress the projection.

## Subject identity and privacy

Journey lookup accepts only pseudonymous references:

- `lead:<id>`
- `opportunity:<id>`

Raw email addresses and phone-like identifiers fail closed. Projection output contains evidence references, source/campaign context and authority status, but no raw contact PII.

## Deterministic replay

- replay order is `(occurred_at, event_id)`, independent of ingestion order;
- pre-lead engagement remains evidence but does not invent a lead transition;
- repeated, lower-state or authority-rejected evidence can be suppressed as transitions while remaining visible;
- every accepted transition records source event, observed time, reason, confidence, skipped states and rule version;
- `untrusted_evidence_count` exposes rejected/invalid stage evidence;
- data quality becomes `observed_with_untrusted_evidence` whenever such evidence is present.

## API surface

Viewer-only API work is isolated in the stacked Journey API increment:

- `GET /api/v1/journeys/{subject_ref}`
- `GET /api/v1/journeys/{subject_ref}/history`

There is no Journey create/update/delete/execute/contact route.

## Safety boundary

Every `JourneyProjection` is emitted with:

- `shadow_mode=true`;
- `execution_enabled=false`;
- `external_writes_enabled=false`;
- `contains_raw_pii=false`.

No Phase 9A component sends a message, writes CRM, changes Ads, publishes content, or activates the n8n executor.

## Acceptance gates

- deterministic replay from out-of-order insertion;
- monotonic transitions and branch guards;
- explicit skipped-state reporting;
- pre-lead engagement retained without invented conversion;
- pseudonymous identity validation and raw-contact rejection;
- Sales Hub/EspoCRM source-authority enforcement;
- untrusted source cannot fake appointment/site visit/customer;
- viewer-only API/OpenAPI parity;
- business evals and all applicable protected CI green;
- no production deployment or external execution as part of source acceptance.

## Next Phase 9A increments

1. add concrete read-only Sales Hub/EspoCRM source adapters/snapshots for the versioned evidence contract;
2. add Redis-backed derived projection snapshots only if performance evidence requires them, without duplicating raw PII;
3. implement deterministic explainable Lead Scoring as a separate owner-reviewed increment;
4. implement Next Best Action as recommendation-only with `execution_enabled=false`;
5. keep all customer/contact execution in the later Phase 10 boundary.
