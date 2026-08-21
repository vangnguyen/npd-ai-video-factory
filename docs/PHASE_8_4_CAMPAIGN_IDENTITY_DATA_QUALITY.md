# Phase 8.4 — Campaign Identity & Attribution Data Quality

## Goal

Phase 8.4 closes the largest remaining Phase 7 attribution gap: source events must
resolve to the correct Campaign before they enter the immutable touchpoint ledger.
It adds an owner-verified identity registry, pseudonymous read-only ingestion and a
data-quality surface for coverage, freshness, unknown identities and conflicts.

The phase does not create Ads, infer projects from campaign names, mutate CRM/Ads,
contact customers or enable the n8n write executor.

## Architecture

```text
Meta / GA4 / UTM / EspoCRM read-only event
                    |
                    v
        PII and write-flag validation
                    |
                    v
  owner-verified identity registry + UTM contract
                    |
       +------------+-------------+
       |                          |
       v                          v
resolved to one Campaign     unknown / conflict
       |                          |
       v                          v
immutable touchpoint       quality snapshot + audit
ledger (shadow mode)       no ledger insertion
```

All records stay inside the existing Agent Hub Redis namespace under the
`attribution-os` subnamespace. Video jobs remain in their existing Redis DB 0
namespace and no new Redis instance is created.

## Verified identity registry

`CampaignIdentityMapping` binds an external identity to exactly one Campaign OS ID
and its existing `project` value. Supported source systems are `meta_ads`, `ga4`,
`espocrm` and `utm`.

The mapping may contain account, campaign, ad set, ad group, ad and/or canonical
`utm_campaign` identifiers. The model intentionally has no source campaign-name
field. A Meta mapping requires `source_campaign_id`.

Only an owner may register a mapping. Mappings are immutable and idempotent:

- an identical identity-to-Campaign registration returns the existing mapping;
- the same identity cannot be reassigned to a different Campaign;
- a broad mapping cannot overlap a more-specific mapping for another Campaign;
- distinct ad IDs within one source campaign may map to different Campaigns when
  the owner explicitly verifies that separation.

This allows Vịnh Tiên and Vịnh Ngọc/Vinhomes Cần Giờ to remain separate even when
historic Meta naming is inconsistent.

## Pseudonymous source-event contract

`SourceTouchpointEvent` accepts only the attribution fields needed to resolve and
deduplicate an event: source event ID, source system, timestamp, event type, channel,
canonical/external Campaign identity, UTM fields, landing-page reference and a
pseudonymous lead and/or opportunity ID.

Email addresses, phone numbers, contact names, addresses and secrets are rejected.
Metadata that attempts to enable write, publish, send, execute or mutation behavior
is also rejected.

The immutable ledger event ID is deterministic:

```text
tpt_<sha256(source_system + source_event_id)[0:32]>
```

Re-ingesting the same payload is a duplicate. Reusing the same source event ID with
a changed payload is a conflict and does not alter the ledger.

## Resolution rules

A source event may resolve through one or more deterministic evidence paths:

1. explicit canonical Campaign ID that exists in Campaign OS;
2. exact case-insensitive match to the Campaign tracking contract's
   `utm_campaign`;
3. an owner-verified registry mapping whose non-null identifiers all match.

Exactly one distinct Campaign must result. Zero results are `unknown`; multiple
Campaigns are `conflict`. Campaign names, ad names and project-name fragments are
never used as fallbacks.

## Data-quality snapshot

Every ingest request persists an `AttributionDataQualitySnapshot` containing:

- events received and identity-resolved;
- ledger insertions and duplicates;
- unknown and conflicting records;
- identity coverage and mismatch rates;
- latest source-event timestamp;
- source freshness age and `fresh` / `stale` / `no_data` state;
- bounded issue details and candidate Campaign IDs;
- actor, timestamp, shadow/write-disabled flags.

Unknown/conflicting records are visible for correction but never counted as valid
Campaign touchpoints.

## REST API and RBAC

| Endpoint | Role | Behavior |
|---|---|---|
| `GET /api/v1/attribution/identity/status` | viewer | Mapping count, touchpoints and latest quality snapshot |
| `GET /api/v1/attribution/identity-mappings` | viewer | List/filter verified mappings |
| `POST /api/v1/attribution/identity-mappings` | owner | Register a verified mapping; no source mutation |
| `POST /api/v1/attribution/touchpoints/ingest` | operator | Resolve pseudonymous source events and append only valid touchpoints |
| `GET /api/v1/attribution/data-quality` | viewer | Read recent coverage/freshness/mismatch snapshots |

Existing reconciliation and revenue acceptance endpoints are unchanged. A mapping
registration is owner-gated because it can change future attribution meaning, even
though it has no external side effect.

## Command Center

The Attribution workspace shows verified mapping count, identity coverage, unknown
and conflict counts, freshness, source IDs, Campaign/project relationships and the
latest mismatch warnings. It does not attempt automatic repair or name-based mapping.

## Acceptance coverage

Tests cover Vịnh Tiên/Vịnh Ngọc separation, idempotent registration, overlap
rejection, UTM-contract resolution, deduplication, immutable-payload conflicts,
unknown/multi-Campaign mapping, PII/write-flag rejection, RBAC, Redis recovery,
dashboard/API exposure and absence of external writes.

## Rollout gates

1. Merge only after Agent Hub CI, Phase 5 Deployment Bundle CI and Sprint 1 Docker
   E2E pass on the final head.
2. Back up the Agent Hub Redis namespace before deploying.
3. Deploy only Agent Hub through the guarded Phase 5 helper.
4. Run local and public smoke.
5. Register production mappings only from IDs verified in source APIs/Ads Manager.
6. Start with a bounded read-only event sample and review unknown/conflict details.
7. Do not report CAC/ROAS until paid spend and revenue cover the same accepted
   Campaign and period.

## Intentional limits

Phase 8.4 does not implement live provider polling, full identity stitching,
cross-device tracking, accounting-grade attribution, Ads creation, traffic allocation,
budget changes, automated winner application or source-system writes. Provider-specific
read adapters can submit this contract later after privacy and freshness acceptance.
