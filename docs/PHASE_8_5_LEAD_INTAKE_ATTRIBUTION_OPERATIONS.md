# Phase 8.5 — Lead Intake Attribution Operations

## Goal

Phase 8.5 operationalizes the Phase 8.4 identity quality gate for real Lead Intake
events. Unknown and conflicting events are retained in a durable, privacy-safe queue
instead of disappearing after one data-quality snapshot. Once the owner verifies a
source identity mapping, an operator can preview and replay the event into the internal
immutable attribution ledger.

This phase never creates Ads, reads lead contact details into Agent Hub, mutates source
systems, writes CRM, sends messages or enables the n8n write executor.

## Architecture

```text
n8n Lead Intake pseudonymous event
              |
              v
 Phase 8.4 deterministic resolver
       |                  |
       | exactly one      | zero / multiple
       v                  v
 immutable ledger     durable exception queue
                              |
                  owner verifies ID mapping
                              |
                       preview resolution
                              |
                    operator shadow replay
                              |
                       immutable ledger
```

The queue uses the existing Agent Hub store abstraction. Redis keys remain under the
existing namespace and the `attribution-os:intake-issue:*` subnamespace. No Redis,
n8n, Caddy, CRM or CMS instance is added.

## Privacy and immutability contract

Each exception stores the validated `SourceTouchpointEvent` from Phase 8.4:

- pseudonymous `lead_id` or `opportunity_id` only;
- Meta/GA4/UTM/EspoCRM external IDs and tracking fields;
- no name, email, phone, address, credential or secret;
- no enabled write/publish/send/execute/mutation flag.

The issue ID is deterministic from `source_system + source_event_id`. Repeated events
increase the occurrence count. The ledger event ID remains deterministic and the
existing immutable-payload comparison blocks changed event content.

## Lifecycle

```text
pending unknown/conflict
        |
        | owner-verified mapping or canonical UTM contract
        v
preview: ready_to_replay / duplicate / conflict / unknown
        |
        | operator replay, only when ready or idempotent duplicate
        v
resolved + replay snapshot/audit
```

There is no automatic guessing from Campaign/ad names and no automatic replay after a
mapping change. Preview must resolve exactly one canonical Campaign.

## API and RBAC

| Endpoint | Role | Behavior |
|---|---|---|
| `GET /api/v1/attribution/intake/issues` | viewer | List pending/resolved privacy-safe exceptions |
| `GET /api/v1/attribution/intake/issues/{id}/preview` | viewer | Re-run deterministic resolution without ledger/source writes |
| `POST /api/v1/attribution/intake/issues/{id}/replay` | operator | Append/confirm one idempotent internal shadow touchpoint |

Identity mapping registration remains owner-only through the existing
`POST /api/v1/attribution/identity-mappings` boundary. Replay cannot create mappings.

## Command Center

Attribution & Revenue OS now shows the pending intake count and an exception queue with
source event/campaign/ad identifiers, occurrence count, preview result and a guarded
`Replay shadow` action. Raw lead identity is intentionally not rendered.

## Production Lead Intake compatibility

The accepted production n8n flow propagates `campaign_id`, source campaign/ad set/ad/form
IDs, UTMs and landing-page metadata to Agent Hub in `read_only_shadow` mode. Phase 8.5
does not replace that workflow; it makes its unknown/conflict outcome recoverable and
auditable after a verified mapping becomes available.

The Page `Bất Động Sản Vinhomes` ownership/Lead Access gate remains paused by owner
instruction. Phase 8.5 neither changes Page permissions nor creates another test lead.

## Acceptance coverage

Tests prove:

- unknown Lead Intake events survive in memory and Redis stores;
- owner-verified mapping changes preview to `ready_to_replay`;
- replay is idempotent and closes the queue item;
- multi-Campaign evidence and changed immutable payloads stay blocked;
- viewer can inspect but cannot replay; operator cannot replay unresolved evidence;
- queue data contains no external-write capability and video Redis keys are untouched;
- Command Center and tool registry expose planning/read-only behavior only.

## Rollout gates

1. Agent Hub CI and business evals pass on the final commit.
2. Phase 5 deployment bundle CI passes if the bundle is touched.
3. Sprint 1 API/worker/renderer and Docker Compose E2E remain green.
4. Back up the Agent Hub Redis namespace before replacing only Agent Hub.
5. Run localhost and public authenticated smoke.
6. Start with existing unknown records only; do not fabricate Campaign IDs.
7. Do not resume the paused Meta Page claim without a new owner instruction.

## Intentional limits and next step

Phase 8.5 does not poll providers, perform full identity stitching, expose raw PII,
create Ads, allocate traffic, mutate budgets, publish content or automate winner
application. The next safe increment is a provider-health and ingestion-observability
layer: signed delivery receipts, bounded retry/dead-letter metrics and freshness SLOs
for configured read-only sources. Ads creation remains deferred.
