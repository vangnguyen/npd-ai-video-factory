# AH-T01 production overlay

This Compose override mounts one protected telemetry salt into only the V1 API and renderer. It
does not declare ports, routes, networks, Redis, Caddy, write blocking or traffic switching.

AH-T01B keeps the deployment and rollback target set at exactly `api` + `renderer`, gives API INFO
telemetry a verified Uvicorn output path, and applies a bounded readiness/image check after
rollback. Worker, Agent Hub and Redis container/image identities are immutable, while queue/processing,
`AGENT_REDIS_URL`, network/port bindings and the Caddy identity/configuration are checked
before/after without recording secrets or changing Caddy.

The overlay is inert until an operator supplies `AH_T01_TELEMETRY_SALT_HOST_FILE` and explicitly
runs the separately owner-gated deployment script. The salt file must be absolute, outside Git,
owned by the production custodian, mode `0600` or stricter, and contain at least 32 bytes. The salt
is not copied into an environment variable or deployment receipt.

Merging this source-only candidate does not deploy or recreate a service and does not start the
14-day clock. A production retry requires a fresh owner action gate.
