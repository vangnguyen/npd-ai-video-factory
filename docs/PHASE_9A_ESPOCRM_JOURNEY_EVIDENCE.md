# Phase 9A — EspoCRM Journey Evidence Preview

## Purpose

This increment connects the Phase 9A journey evidence contract to the existing PII-free EspoCRM Opportunity reader **without automatically ingesting anything**.

The adapter returns candidate `SourceTouchpointEvent` records for human/operator review. It never inserts those candidates into Attribution OS, changes CRM, creates a task, contacts a customer, or executes a recommendation.

## Explicit stage mapping only

Production stage names are not inferred.

`ESPOCRM_JOURNEY_STAGE_MAP_JSON` must contain an exact JSON object whose keys are verified EspoCRM Opportunity stage labels and whose values are one of the Phase 9A stage-evidence states:

- `mql`
- `appointment`
- `site_visit`
- `lost`
- `customer`
- `reengagement`

Example shape for testing/documentation only:

```json
{
  "<verified CRM stage label>": "appointment"
}
```

Do not copy an example label into production. The production map must be derived from the actual CRM stage schema/business definition and separately reviewed.

If the map is empty, the adapter returns `not_configured` and **does not call EspoCRM**.

Mapping to base states such as `won`, `lead`, `sql` or `negotiation` is rejected because those are already covered by the established Attribution OS/base journey contracts. This avoids overlapping semantics.

## Read projection

The adapter reuses `EspoOpportunityReader`, whose projection is limited to PII-free Opportunity fields such as:

- id
- stage
- amount/currency
- close date
- lead source
- campaign identity
- created/modified timestamps

No contact name, email, phone or address is requested.

## Campaign identity gate

A mapped Opportunity can become a candidate only when at least one campaign identity exists:

- canonical Agent Hub `CMP-*` campaign ID from the configured Opportunity campaign field; or
- an external EspoCRM campaign ID that the existing Attribution identity-resolution layer can resolve later.

Mapped records with no campaign identity are omitted rather than assigned to a campaign by name or guess.

## Candidate contract

Each accepted candidate is a PII-free `SourceTouchpointEvent` with:

- deterministic `source_event_id` derived from Opportunity ID, stage, observation time, target state and preview version;
- `source_system=espocrm`;
- `event_type=opportunity_stage_changed`;
- Opportunity ID only, no raw customer identity;
- explicit campaign identity;
- nested `journey_evidence` using `phase-9a-sales-v1`;
- `external_writes_enabled=false`.

The adapter uses the Opportunity `modifiedAt`/`createdAt` observation timestamp. It explicitly does **not** claim this is the exact historical stage-change timestamp.

## API

`GET /api/v1/journeys/sources/espocrm/preview`

- operator/owner only;
- bounded `limit` 1–500;
- read-only provider request;
- `Cache-Control: no-store` from the existing API middleware;
- no POST/ingest/execute route.

## Preview status

- `not_configured` — stage map or EspoCRM read credentials missing;
- `no_data` — no usable mapped candidate;
- `available` — all observed records relevant to the configured map produced candidates without omissions;
- `partial` — candidates exist, but some records were unmapped or lacked campaign identity.

The response exposes counts for unmapped and missing-campaign records so data gaps are visible.

## Safety boundary

Every preview requires:

- `ingest_enabled=false`
- `execution_enabled=false`
- `external_writes_enabled=false`

This increment performs no:

- Attribution OS insertion;
- CRM write;
- customer contact;
- Sales Hub write;
- Ads mutation;
- notification delivery;
- CMS publish;
- n8n executor activation;
- production deployment.

## Acceptance

- no stage map => no network call;
- malformed/unsupported mapping fails before network;
- only explicit mapped stages produce candidates;
- stage matching may normalize case/whitespace but cannot invent a mapping;
- PII fields are absent from the EspoCRM select projection;
- candidate requires canonical or external campaign identity;
- preview does not mutate the touchpoint ledger or task store;
- viewer cannot invoke the provider read; operator/owner can;
- API remains GET-only;
- all Agent Hub/business-eval/Phase 5 gates pass before merge.

## Next source connector

Sales Hub appointment/site-visit evidence should use the same `phase-9a-sales-v1` contract, but its connector must be based on a verified SaleHub read API/data contract. No endpoint or schema is assumed in this increment.
