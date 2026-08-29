# V1 legacy telemetry plan

Status: **source implemented and locally tested; not deployed; observation not started**

AH-01C adds identity-safe structured telemetry to the V1 API and renderer source. It does not add
authentication, change Caddy or ports, restart a service, deploy an image, block a request, or
switch traffic.

## Implemented event contract

Each recognized legacy request emits one `legacy_route_access` JSON event with:

- service, fixed route template, method, status and action class;
- per-route count and total deprecated-attempt count since process start;
- a sanitized claimed caller ID from `X-NPD-Caller-ID`;
- HMAC source and client fingerprints when `LEGACY_TELEMETRY_SALT` is configured; and
- explicit flags that payloads and raw network identities were not logged.

Job IDs, artifact names, request/response bodies, query strings, raw IP addresses, raw user agents,
authorization headers, cookies and the HMAC salt are never logged. Unknown paths are not logged.
When the salt is absent, identity fields stay null and `identity_ready=false`; the system never
falls back to raw identity.

The known Agent Hub V1 tool and V1 worker now send non-secret claimed IDs. Claimed IDs remain
spoofable on unauthenticated public ports, so attribution must pair them with the source/client
fingerprints. The renderer uses its direct peer address and deliberately ignores untrusted
forwarded headers.

## Separate deployment gate

Before a production telemetry-only deploy, the owner must approve the exact V1 API, worker,
renderer and Agent Hub image changes. The change window must:

1. generate a dedicated high-entropy `LEGACY_TELEMETRY_SALT` in protected production secret
   storage;
2. back up the current Compose/config and record exact image IDs;
3. deploy only the approved services without stopping Redis or V1 as a stack;
4. prove health/read routes and one mock-only caller attribution path;
5. verify logs contain no raw IP, user agent, payload, token or salt; and
6. roll back the affected image/config on any regression.

No real video create/render request is authorized merely to test telemetry.

## Fourteen-day acceptance window

The clock starts only after deployment evidence shows `identity_ready=true` for both API and
renderer. Preserve daily aggregates for every fixed route, status, claimed caller and fingerprint.
Classify monitoring probes separately from status/artifact/media access and write/render attempts.

Exit requires 14 complete consecutive days with:

- every non-health fingerprint mapped to an accepted owner/caller or explicitly investigated;
- zero unexplained create, render or media activity;
- known worker render calls carrying `video-factory-v1-worker`;
- known Agent Hub legacy calls carrying `agent-hub-v1-tool` until the bridge replaces them;
- no counter reset without a documented service restart; and
- owner acceptance of the signed observation summary.

Any unexplained caller, telemetry gap, missing salt, restart gap or raw-identity leak resets the
window. Even a PASS observation does not itself authorize port closure, traffic switch or V1 stop.
