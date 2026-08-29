# Agent Hub to Video Factory boundary v1 (AH-02)

## Status and source

AH-02 is an offline/mock-only integration boundary. It does not enable production traffic or
change the independent Video Factory V2/V3 repository or runtime.

The contract is pinned to the public interface documented in `npd-video-factory-v2` commit
[`8fa96409b0db6ec6d4dc3c04f6e3aaab2f3201ee`](https://github.com/vangnguyen/npd-video-factory-v2/commit/8fa96409b0db6ec6d4dc3c04f6e3aaab2f3201ee):

- `docs/AGENT_HUB_BRIDGE.md`;
- `docs/API.md`;
- `docs/SECURITY.md`.

Agent Hub copies no V2/V3 Python package or runtime implementation. The two systems share no
database, Redis namespace, object storage, process memory or secret. All test interaction crosses
a serialized request/response or signed-webhook boundary.

## Deliberately narrow live surface

| Surface | AH-02 state | Behavior |
|---|---|---|
| `project.create_draft` | Mock-supported | Signed `POST /api/v1/bridge/project-requests`; always draft-only |
| Project request status | Mock-supported | Signed bridge request read |
| Project summary | Mock-supported | Signed read-only bridge summary |
| `video.project.created` | Mock-supported | Only event accepted by the signed receiver |
| Analysis, generation, preview | Reserved/unsupported | Typed DTOs exist; the client raises before transport |
| Approval and render | Reserved/unsupported | Typed DTOs exist; the client raises before transport |
| Publication and analytics | Reserved/unsupported | Typed DTOs exist; the client raises before transport |
| Any non-bridge V2 API | Prohibited | No client route and no fallback shortcut |
| Real HTTP transport | Not implemented | Mock transport only; no socket or provider call |

The V2-11 contract advertises a reserved event vocabulary. AH-02 does not treat that vocabulary as
proof of a live emitter. Only `video.project.created` is in `live_outbound_events`; a correctly
signed reserved-but-not-live event returns `VIDEO_FACTORY_EVENT_NOT_LIVE` before persistence.

## Safe default

The FastAPI application registers the boundary in `disabled` mode. Status is readable at
`GET /api/v1/integrations/video-factory/status`, while event/audit reads and the webhook receiver
return `503 VIDEO_FACTORY_INTEGRATION_DISABLED` until an explicit future assembly supplies a
client, receiver and Agent Hub-owned store.

There is no environment switch to enable live traffic in AH-02, no production HTTP transport and
no raw secret setting. Test keys are injected as bytes into mock constructors. Any future live
assembly must load a dedicated external key file; raw key material must never be placed in an
environment example, API model, log, receipt or persisted event.

## Service request authentication

Bridge requests carry exactly:

- `X-NPD-Service-Id`;
- `X-NPD-Key-Id`;
- `X-NPD-Timestamp`;
- `X-NPD-Nonce`;
- `X-NPD-Content-SHA256`;
- `X-NPD-Signature`;
- `X-NPD-Contract-Version: agent-hub-bridge.v1`.

The HMAC-SHA256 canonical text is:

```text
UPPERCASE_METHOD
/exact/path
exact_encoded_query_string
unix_timestamp
nonce
lowercase_body_sha256
```

The mock server verifies the exact raw body and encoded query, applies a 300-second timestamp
window, stores a hashed single-use nonce with a 600-second TTL and uses constant-time comparisons.
An unknown key, changed path/query/body, expired timestamp or repeated nonce fails closed.

Only these bridge routes are allowlisted by `VideoFactoryClient`:

- `GET /api/v1/bridge/contract`;
- `POST /api/v1/bridge/project-requests`;
- `GET /api/v1/bridge/project-requests/{request_id}`;
- `GET /api/v1/bridge/projects/{project_id}/summary`.

## Signed webhook receiver

The receiver path is exactly `POST /agent-hub/events/v1`. Headers are:

- `X-NPD-Key-Id`;
- `X-NPD-Timestamp`;
- `X-NPD-Content-SHA256`;
- `X-NPD-Signature`;
- `X-NPD-Contract-Version`;
- `X-NPD-Event-Id`.

Canonical webhook text is:

```text
POST
/agent-hub/events/v1
unix_timestamp
event_id
lowercase_body_sha256
```

Verification precedes parsing or persistence. The header event ID must equal the body event ID.
The body is capped, strict models reject unknown fields and nested secret-like fields, and
timestamps must be timezone-aware. Event semantics are:

- same event ID and same body hash: idempotent `202`, with no duplicate event record;
- same event ID and changed signed body: `409 VIDEO_FACTORY_EVENT_IDEMPOTENCY_CONFLICT`;
- bad/expired signature, bad body hash or unknown key: `401`, before persistence;
- reserved event without an accepted emitter: `409`, before persistence.

Persistence stores the parsed event, key ID, signed timestamp, body hash and verification truth.
It never stores the raw signature or key. The Redis implementation uses only an Agent Hub-owned
namespace and repairs a missing sorted-set index on an exact retry after an interrupted write.
Using production Redis remains blocked by AH-01B until Agent Hub Redis ownership is migrated and
accepted; AH-02 does not change the current runtime.

## DTO boundary

Strict, versioned Agent Hub DTOs cover project, request status, generation, analysis, preview,
approval, render, publication and analytics. They use `extra=forbid`, bounded identifiers and
references, timezone-aware UTC datetimes, VND-only analytics currency and literal no-external-
action flags. DTO presence is not capability enablement: unsupported client methods always raise
before the transport call counter changes.

The independent Agent Hub-facing event schema is
[`packages/contracts/agent-hub-video-factory-boundary.v1.schema.json`](../packages/contracts/agent-hub-video-factory-boundary.v1.schema.json).
Its metadata records the pinned V2 commit, current live action/event and disabled/no-network
default so the reserved vocabulary cannot be misreported as implemented behavior.

## Owner gates retained

AH-02 authorizes no deployment, production configuration, V1 disable/drain, Redis migration,
storage move, Caddy change, port change, V2/V3 modification, provider call, render, publication or
traffic switch. Those remain separate owner-gated work. Video Factory V1 decommission remains
`NO-GO` while the AH-01 inventory contains unknown dependencies.
