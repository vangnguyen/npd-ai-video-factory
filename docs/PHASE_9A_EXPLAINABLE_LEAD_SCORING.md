# Phase 9A — Explainable Lead Scoring v1

## Purpose

`phase-9a-score-v1` is a deterministic **journey-momentum index** for prioritization research. It is not a conversion probability, credit score, or autonomous sales decision.

The scorer consumes only the read-only Customer Journey projection and emits factor-level explanations. It does not write CRM, contact customers, launch Ads, publish content or trigger n8n execution.

## Inputs used in v1

Three factors are implemented:

1. **Journey state** — maximum 70 points, from the fixed versioned state table.
2. **Recency** — maximum 20 points, based on the latest trusted journey evidence as of an explicit evaluation time.
3. **Engagement frequency** — maximum 10 points, using trusted `ad_click` / `landing_view` evidence only.

The raw points are normalized to 0–100 using only factors with observed data.

## Missing-data rule

Missing information is not silently converted into a negative signal.

For example, when there are no explicit engagement events, `engagement_frequency` is emitted with:

- `status=missing`;
- `contribution=null`;
- its 10-point capacity excluded from `available_points`.

This means the score expresses momentum using observed evidence rather than pretending that absent integration coverage means zero customer interest.

V1 explicitly reports these still-missing input families:

- source quality;
- project fit;
- budget fit;
- sales SLA evidence;
- engagement frequency when unavailable.

## State contribution table

The state factor is bounded to 70 points:

- anonymous: 0
- lead: 10
- engaged: 20
- MQL: 30
- SQL: 40
- appointment: 50
- site_visit: 58
- negotiation: 65
- won: 70
- customer: 70
- lost: 5
- reengagement: 25

These are deterministic policy weights, not learned probabilities.

## Recency contribution

Latest **trusted** evidence age:

- <= 24h: 20
- <= 72h: 16
- <= 7d: 12
- <= 30d: 6
- older: 0

Untrusted/rejected evidence cannot make a lead appear more recent.

## Engagement contribution

Trusted explicit engagement count:

- 1 event: 4
- 2 events: 7
- 3+ events: 10

If the event family is absent, the factor is `missing`, not zero.

## Confidence

Confidence is separate from the score. It is based on trusted evidence count, source diversity and engagement coverage, capped at `0.80` in v1 because important business inputs are not yet integrated.

Any rejected or invalid journey evidence caps confidence at `0.65`. Such evidence is retained for audit but is excluded from state/recency/engagement scoring inputs.

## Privacy and fairness boundary

- raw contact PII is prohibited;
- protected or sensitive traits are neither inferred nor used;
- missing data cannot autonomously discard a lead;
- untrusted evidence lowers confidence rather than becoming a hidden negative factor;
- every numeric contribution has a bounded reason and evidence references;
- `shadow_mode=true`;
- `execution_enabled=false`;
- `external_writes_enabled=false`.

## Determinism

Given the same immutable journey evidence, scoring version and timezone-aware `as_of`, the output is identical.

The evaluation timestamp is part of the output so recency calculations are auditable.

## Acceptance

- identical input + `as_of` produces identical output;
- score recomputes exactly from observed factor contributions;
- missing factor capacity is excluded from the denominator;
- rejected evidence cannot raise state, recency or engagement score;
- confidence is capped when untrusted evidence exists;
- no raw PII or sensitive-trait inputs;
- no execution/write/contact capability;
- full Agent Hub/business-eval CI before merge.

## Next increment

Expose a viewer-only `GET /api/v1/lead-scores/{subject_ref}` endpoint with optional timezone-aware `as_of`, then add sales-user review/backtesting before any Next Best Action work.
