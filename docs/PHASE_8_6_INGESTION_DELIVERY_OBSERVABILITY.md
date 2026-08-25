# Phase 8.6 — Ingestion Delivery Observability

## Goal

Phase 8.6 makes read-only attribution delivery observable and tamper-evident. A producer
such as n8n Lead Intake sends a pseudonymous envelope, receives an immutable HMAC-signed
receipt, and can report bounded delivery failures. Agent Hub exposes retry, dead-letter
and freshness SLO metrics without becoming a job scheduler or mutating any source.

Ads creation remains deferred. The n8n write executor, CRM writes, customer messaging,
content publishing and budget mutation remain disabled.

## Architecture

```text
read-only producer
  |  delivery_id + attempt + pseudonymous events
  v
delivery integrity / retry-budget boundary
  |                         |
  | accepted/partial        | reported failure / changed payload
  v                         v
Phase 8.4/8.5 ingest     retry receipt / dead letter
  |
  v
HMAC-signed immutable receipt
  |
  +--> receipt metrics + freshness SLO + audit
```

All receipt and dead-letter records use the existing Agent Hub store abstraction and
Redis namespace:

```text
{AGENT_REDIS_NAMESPACE}:attribution-os:delivery-receipt:*
{AGENT_REDIS_NAMESPACE}:attribution-os:delivery-receipts
{AGENT_REDIS_NAMESPACE}:attribution-os:dead-letter:*
{AGENT_REDIS_NAMESPACE}:attribution-os:dead-letters
```

No second Redis, n8n or Caddy instance is created.

## Delivery contract

`AttributionDeliveryEnvelope` contains:

- pseudonymous `delivery_id` and a constrained producer name;
- source system, sent timestamp, attempt number and maximum attempts;
- one to 500 validated Phase 8.4 source events;
- optional metadata subject to the same secret, raw-PII and write-flag rejection.

All events must match the envelope source system. Attempts may not exceed either the
envelope budget or `AGENT_ATTRIBUTION_DELIVERY_MAX_ATTEMPTS`.

The receipt ID is deterministic from `delivery_id + attempt_number`. Repeating the
same payload returns the same receipt. Reusing the same identity with changed content
raises an integrity conflict and creates a dead-letter record; it never changes the
existing receipt or touchpoint ledger.

## Signed receipts

Receipts include source/producer, attempt budget, payload SHA-256, Phase 8.4 snapshot
counts, outcome, retry state, timestamp and a public key identifier. The signature is:

```text
hmac-sha256(HMAC-SHA256(dedicated signing key, canonical receipt JSON))
```

The dedicated signing key is injected only through the protected VPS environment as
`AGENT_ATTRIBUTION_RECEIPT_SIGNING_KEY`. It must differ from browser session, bearer,
Google, Meta, GA4 and CRM credentials. Neither the key nor any secret is returned,
stored in Redis, committed or logged.

Receipt outcomes:

- `accepted`: every event resolved without identity exceptions;
- `partial`: delivery was accepted but unknown/conflicting events entered the Phase 8.5 queue;
- `retry_pending`: producer reported a transient failure below its retry ceiling;
- `dead_lettered`: the retry ceiling was exhausted.

Identity `partial` does not trigger transport retries because Phase 8.5 already retains
those events safely for verified mapping and shadow replay.

## Retry and dead-letter boundary

Agent Hub records, but does not schedule, retries. For a reported transient failure it
returns a bounded advisory retry time using 30-second exponential backoff capped at
15 minutes. Once `attempt_number == max_attempts`, retry is disabled and an immutable
dead letter is stored. The producer remains responsible for delivery timing.

Failure reports use a constrained error code and safe metadata only. Raw provider
responses, access tokens and contact data are forbidden.

## Freshness SLO

`AGENT_ATTRIBUTION_FRESHNESS_SLOS_JSON` maps producer names to target minutes. Defaults:

| Producer | Target |
|---|---:|
| `n8n_lead_intake` | 15 minutes |
| `meta_ads` | 1,440 minutes |
| `ga4` | 1,440 minutes |
| `espocrm` | 1,440 minutes |
| `utm` | 60 minutes |

Only accepted/partial receipts count as successful delivery. Each producer reports
`no_data`, `fresh` or `stale`, plus last receipt and age. A stale state is an alerting
signal only and cannot trigger source mutations.

## API and RBAC

| Endpoint | Role | Behavior |
|---|---|---|
| `POST /api/v1/attribution/deliveries` | operator | Ingest pseudonymous events and return a signed receipt |
| `POST /api/v1/attribution/deliveries/failures` | operator | Record bounded retry/dead-letter evidence |
| `GET /api/v1/attribution/deliveries/status` | viewer | Aggregate receipt and freshness SLO state |
| `GET /api/v1/attribution/deliveries/receipts` | viewer | Filter recent immutable receipts |
| `GET /api/v1/attribution/deliveries/dead-letters` | viewer | Review safe dead-letter evidence |
| `POST /api/v1/attribution/deliveries/receipts/verify` | viewer | Verify a receipt using the server-held key |

## Command Center

The Attribution workspace shows signing configuration, accepted/partial counts, retry
pending, dead-letter count, stale/no-data SLO count and recent receipt/dead-letter rows.
It intentionally does not render HMAC signatures or pseudonymous lead identifiers.

## Acceptance coverage

Tests cover:

- valid signed receipt generation and tamper detection;
- delivery/attempt idempotency and changed-payload dead-letter behavior;
- partial identity delivery without transport retry;
- bounded retry and terminal dead-letter state;
- `no_data -> fresh -> stale` SLO transitions;
- raw PII, write flags and excessive retry-budget rejection;
- viewer/operator RBAC and not-configured behavior;
- Redis restart recovery and namespace separation;
- dashboard/tool-policy exposure with external writes disabled;
- existing Phase 1–8.5 regression.

## Rollout gates

Before deployment, initialize the dedicated receipt-signing key with a recoverable env-file backup. The helper never prints the generated secret and requires an explicit apply flag:

```bash
sudo bash scripts/phase5/configure-attribution-delivery.sh --apply
```

Use `--rotate` only during an intentional key rotation. Prior receipts remain tagged with their original `key_id` and should be retained for audit.

1. Keep Phase 8.6 stacked on draft PR #16 until the owner independently decides merges.
2. Pass Agent Hub CI, Phase 5 Deployment Bundle CI and Sprint 1 Docker E2E.
3. Back up `/etc/npd-ai/agent-hub.env`, then add a new dedicated signing key without printing it.
4. Back up the Agent Hub Redis namespace and preserve the rollback image.
5. Deploy only Agent Hub, then run localhost/public authenticated smoke.
6. Activate one bounded n8n Lead Intake envelope and verify its signed receipt/freshness.
7. Do not resume the paused Meta Page ownership gate without new owner instruction.

## Intentional limits and next step

Phase 8.6 does not poll providers, schedule retries, perform full identity stitching,
expose raw PII, create Ads, allocate traffic, mutate budgets, publish content or apply
experiment winners. A later increment may add alert routing and provider-specific
read adapters after SLO evidence is accepted; it must preserve the same no-write and
approval boundaries.
