# Phase 9B — Signed Sales Hub Completeness Attestation

## Purpose

Phase 9B-1 can calculate Sales SLA from supplied activity evidence, but intentionally cannot call missing activity a confirmed breach because Sales Hub source completeness is unknown.

This increment adds the integrity gate required to distinguish:

- `overdue_missing_evidence`: deadline passed, but absence is not proven;
- `breached`: deadline passed and a verified Sales Hub completeness proof covers that SLA deadline while the bound activity batch contains no qualifying event.

It still does not implement a live Sales Hub reader or any external write.

## Completeness claim

A `phase-9b-sales-completeness-v1` claim is scoped to one pseudonymous subject and Campaign. It contains:

- `producer=sales_hub`;
- subject reference;
- Campaign ID;
- completeness window start;
- `complete_through` watermark;
- covered activity types;
- SHA-256 digest of the exact supplied activity batch;
- exact batch record count;
- `external_writes_enabled=false`.

The supported activity types remain:

- `first_response`;
- `appointment_booked`;
- `site_visit_completed`.

## Heartbeat binding

A completeness claim alone is not trusted.

The claim's canonical SHA-256 digest must be present in an `AttributionProducerHeartbeat.metadata` entry named:

`sales_activity_completeness_digest`

The heartbeat must use `producer=sales_hub` and must have already produced an immutable Agent Hub `AttributionHeartbeatReceipt`.

Verification checks all of the following:

1. receipt HMAC signature is valid against the Agent Hub verification keyring;
2. receipt payload digest equals the canonical digest of the supplied heartbeat;
3. heartbeat ID, producer, sequence and emitted time match the receipt;
4. heartbeat producer matches the completeness claim;
5. heartbeat metadata is bound to the exact claim digest;
6. completeness watermark is not later than heartbeat emission time;
7. claim subject and Campaign match the evaluated subject/Campaign;
8. claim record count equals the supplied activity batch size;
9. claim batch digest equals the deterministic canonical digest of the supplied activity observations;
10. the evaluated batch contains no duplicate/untrusted rows;
11. completeness window starts no later than the authoritative lead clock when that clock exists.

Any failed check leaves completeness unverified and cannot create a confirmed breach.

## Full versus partial completeness

`completeness_verified=true` means the cryptographic and semantic proof is valid.

`source_complete=true` is stronger. It additionally requires:

- all three Sales activity types are covered; and
- `complete_through >= as_of`.

A valid partial proof can still confirm one SLA breach if it covers that specific activity type through that SLA deadline. For example, a proof covering only `first_response` through 30 minutes can confirm a missed 15-minute first-response SLA, but cannot confirm a missed 24-hour appointment-booking SLA.

## SLA behavior

Observed activity remains authoritative for `met` or `late` and does not require completeness proof.

For missing activity after deadline:

- if signed completeness covers the relevant activity type through the deadline -> `breached`;
- otherwise -> `overdue_missing_evidence`.

This prevents a heartbeat that merely says a producer is online from being mistaken for proof that all Sales activity data is present.

## API

No new action endpoint is added. The existing endpoint remains:

`POST /api/v1/sales-intelligence/preview`

The request may include an optional completeness proof containing:

- claim;
- original PII-free heartbeat;
- signed heartbeat receipt.

The response reports verification status, receipt ID, watermark, detail and whether the source is complete through `as_of`.

## Safety boundary

The preview remains:

- non-persisting;
- shadow-only;
- PII-free;
- no CRM/Sales Hub write;
- no customer contact;
- no Ads mutation;
- no notification or CMS publish;
- no n8n executor activation;
- no production deployment.

Lead Score and Next Best Action remain unchanged in this increment. A later increment may use **observed** SLA outcomes and verified `breached` outcomes as explainable factors; `overdue_missing_evidence` must continue to behave as missing data, not a negative signal.
