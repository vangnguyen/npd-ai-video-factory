# Phase 9A — Next Best Action v1

## Purpose

`phase-9a-nba-v1` converts the read-only Customer Journey projection and explainable Lead Score into one deterministic **internal review recommendation**.

It does not execute the recommendation. Phase 9A has no customer-contact, CRM-write, Ads-mutation, notification, CMS-publish or n8n-executor capability.

## Contract

Each recommendation includes:

- recommended action from a closed enum;
- bounded reason;
- priority;
- internal review SLA in minutes;
- internal review channel label;
- campaign context when present;
- project context when present;
- journey state and explainable score;
- evidence references;
- confidence;
- missing context;
- evaluation timestamp;
- safety flags.

All outputs enforce:

- `sla_scope=internal_review_only`;
- `shadow_mode=true`;
- `execution_enabled=false`;
- `external_writes_enabled=false`;
- `customer_contact_enabled=false`;
- `contains_raw_pii=false`.

## Allowed actions

The v1 policy can only return these review labels:

- `collect_more_evidence`;
- `review_sales_follow_up`;
- `review_appointment_preparation`;
- `review_post_visit_follow_up`;
- `review_negotiation_next_step`;
- `review_customer_handoff`;
- `review_customer_care`;
- `review_lost_reason`;
- `review_reengagement`.

No action name means “send”, “call”, “publish”, “execute”, “update CRM”, or “change Ads”.

## Deterministic policy

- anonymous -> collect more evidence, low, internal review;
- lead/engaged/MQL/SQL -> review sales follow-up; priority/SLA bounded by explainable score;
- appointment -> review appointment preparation, high;
- site visit -> review post-visit follow-up, high;
- negotiation -> review negotiation next step, high;
- won -> review customer handoff, medium;
- customer -> review customer care, low;
- lost -> review lost reason, medium internal review;
- reengagement -> review reengagement, medium/high depending on score.

The SLA is the time target for a human/internal review only. It is not a timer that triggers customer contact.

## Confidence

NBA confidence starts from the explainable Lead Score confidence. Missing project context caps recommendation confidence at `0.70`. Any untrusted journey evidence is already excluded from the score and can cap upstream confidence further.

## Evidence and context

Evidence references are deduplicated from scoring factors plus the latest trusted journey evidence. The latest trusted evidence supplies campaign context.

Project context is not invented. Until a verified campaign/project resolver is wired into Phase 9A, `project=null` and `project_context` is reported in `missing_context`.

## Acceptance

- identical journey + score + `as_of` -> identical recommendation;
- appointment/site-visit/negotiation rules produce high internal review priority;
- lost state produces internal reason review, not customer contact;
- early low-score states stay bounded to low/medium review priority;
- project context is missing rather than fabricated;
- all execution/write/contact flags remain false;
- no protected/sensitive trait input;
- full Agent Hub/business-eval CI before merge.

## Next increment

Expose viewer-only NBA read/preview endpoints and add shadow-review outcome capture separately. Outcome capture must record only reviewer feedback; it must not execute the recommended action.
