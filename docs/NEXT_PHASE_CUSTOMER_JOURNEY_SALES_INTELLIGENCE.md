# Next phase proposal: Customer Journey and Sales Intelligence

## Status

Architecture proposal only. It does not implement scoring, recommendations, CRM writes or
customer contact. Phase 9 cannot start until Phase 8.8 acceptance and the stabilization
merge sequence are complete.

## Customer Journey Engine

The engine projects read-only evidence into a versioned journey state. It references the
canonical CRM lead/opportunity/customer IDs and Campaign OS IDs; it does not create a
parallel CRM or persist duplicate raw PII.

Canonical states:

```text
anonymous -> lead -> engaged -> MQL -> SQL -> appointment -> site_visit
          -> negotiation -> won -> customer -> reengagement
                         \-> lost -> reengagement
```

Every transition carries `subject_ref`, previous/new state, event time, observed time,
source system, campaign/project context, evidence references, confidence, rule/model
version and audit metadata. Out-of-order events are retained and deterministically
replayed. State does not regress silently; corrections require a reason and an audit
record.

Suggested ownership:

- EspoCRM remains authoritative for lead, opportunity, won/lost and customer state;
- Sales Hub supplies appointment, site-visit and salesperson activity evidence;
- Campaign/Attribution OS supplies source and campaign evidence;
- GA4/Social/Email/ZBS may supply engagement only when their read-only data contracts are
  configured and consent permits use;
- Agent Hub stores the derived projection and evidence references in its existing Redis
  namespace/subnamespace with restart recovery.

## Explainable Lead Scoring Engine

The first release is deterministic and versioned. It produces a score plus factor-level
contributions, never a hidden label alone.

Input families:

- source and campaign quality;
- recency and engagement frequency;
- website behavior;
- Email/ZBS interactions when an approved provider supplies data;
- sales activities and SLA adherence;
- project fit and budget fit;
- CRM stage;
- appointment and site visit;
- duplicate, fraud and data-quality signals.

Missing data must be reported as missing, not converted to a negative signal. Duplicate,
fraud and low-quality flags can cap confidence but must not autonomously discard a lead.
Protected/sensitive traits must not be inferred or used. Every score records input
timestamps, rule/model version, freshness, evidence and confidence.

## Next Best Action contract

The output is a recommendation package:

```json
{
  "recommended_action": "schedule_sales_follow_up",
  "reason": "Lead visited the project page and the current sales SLA is overdue.",
  "priority": "high",
  "sla_minutes": 30,
  "channel": "sales_task",
  "campaign_id": "CMP-...",
  "project": "...",
  "evidence_refs": ["..."],
  "confidence": 0.82,
  "execution_enabled": false
}
```

Required fields are recommended action, bounded reason, priority, SLA, channel,
campaign/project context, evidence and confidence. The initial channels are explanatory
labels only. NBA cannot call, message, email, update CRM, change Ads or publish content.

## Proposed read APIs

- `GET /api/v1/journeys/{subject_ref}`
- `GET /api/v1/journeys/{subject_ref}/history`
- `GET /api/v1/lead-scores/{subject_ref}`
- `GET /api/v1/next-best-actions/{subject_ref}`
- `POST /api/v1/next-best-actions/preview` for deterministic, non-persisting evaluation

Any future action-accept endpoint must create an approval/task record only. Execution is a
separate Phase 10 boundary.

## Delivery stages and acceptance

1. Source/evidence contract and data-quality audit.
2. Read-only journey replay with fixtures and fakeredis restart recovery.
3. Deterministic scorecard with factor explanations and backtesting.
4. NBA preview with sales-user review and false-positive tracking.
5. Shadow production evaluation; no UI action button that contacts a customer.

Acceptance requires transition determinism, temporal replay, deduplication, missing-data
behavior, score explainability, no raw PII duplication, API/RBAC parity, Redis recovery,
audit completeness, bias/data-quality review, business evals, full CI and explicit proof
that every recommendation has `execution_enabled=false`.

