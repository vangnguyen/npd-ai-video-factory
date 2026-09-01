# Phase 9A — NBA Shadow Review Evaluation

## Purpose

This increment adds reviewer telemetry for Next Best Action recommendations so Phase 9A can measure relevance and false positives before any execution capability exists.

A shadow review is **not** an approval, acceptance, execution request, CRM update, task dispatch or customer-contact instruction. It records only a human judgement about whether a recommendation was useful given the available evidence.

## Dispositions

Reviewers can record exactly one of:

- `relevant`;
- `not_relevant`;
- `needs_more_context`.

`not_relevant` is counted as a recommendation false positive for the bounded shadow-evaluation metric. `needs_more_context` is excluded from the false-positive denominator rather than treated as either success or failure.

## Stored record

Each review stores only:

- pseudonymous `subject_ref`;
- recommendation version/action;
- recommendation evaluation timestamp;
- journey state;
- lead score and recommendation confidence;
- evidence references;
- review disposition;
- optional PII-free note;
- reviewer role (`operator` or `owner`), not reviewer identity;
- review timestamp;
- immutable safety flags.

The record explicitly requires:

- `recommendation_executed=false`;
- `execution_enabled=false`;
- `external_writes_enabled=false`;
- `customer_contact_enabled=false`;
- `contains_raw_pii=false`.

## Privacy boundary

- raw email addresses and phone-like values are rejected from review notes;
- the reviewer account/email is not persisted, only the role;
- subject references remain pseudonymous;
- Redis subject indexes use a SHA-256-derived bounded hash, so raw subject IDs are not placed in index key names;
- no customer content or message body is stored.

## Persistence

The repository is intentionally separate from the existing `HubStore` protocol to keep Phase 9 review telemetry bounded and avoid a broad storage migration.

- memory backend: process-local repository for tests/dev;
- Redis backend: Agent Hub's existing Redis client and namespace under `phase9-os:nba-review`;
- retention: maximum 5,000 review records;
- review records are immutable;
- no new Redis service, database, host port or external infrastructure.

## API

- `POST /api/v1/next-best-actions/reviews` — operator/owner only;
- `GET /api/v1/next-best-actions/reviews` — viewer+;
- `GET /api/v1/next-best-actions/reviews/summary` — viewer+.

There is no `/accept`, `/execute`, `/send` or `/contact` route.

## Summary metric

For the bounded review window:

`false_positive_rate = not_relevant / (relevant + not_relevant)`

If there are no decided reviews, the rate is `null`. `needs_more_context` remains visible but does not distort the denominator.

## Acceptance

- operator/owner can record a review; viewer cannot;
- raw contact data in note fails closed;
- review does not create Agent Hub task or execution;
- memory repository persists across service instances sharing the same store;
- fakeredis restart-style repository reconstruction recovers records;
- Redis subject index keys do not contain raw subject IDs;
- false-positive summary is deterministic;
- no execution/contact/write safety flag can become true;
- all Agent Hub/business-eval CI gates pass before merge.

## Still outside Phase 9A

- executing a recommendation;
- auto-creating Sales Hub/CRM tasks;
- messaging/calling/emailing a customer;
- modifying Ads or budgets;
- autonomous prioritization that hides or discards leads;
- production rollout without a separate owner gate.
