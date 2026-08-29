# AH-T01 production overlay

This Compose override mounts one protected telemetry salt into only the V1 API and renderer. It
does not declare ports, routes, networks, Redis, Caddy, write blocking or traffic switching.

The overlay is inert until an operator supplies `AH_T01_TELEMETRY_SALT_HOST_FILE` and explicitly
runs the separately owner-gated deployment script. The salt file must be absolute, outside Git,
owned by the production custodian, mode `0600` or stricter, and contain at least 32 bytes. The salt
is not copied into an environment variable or deployment receipt.

Merging this file does not deploy or recreate a service and does not start the 14-day clock.
