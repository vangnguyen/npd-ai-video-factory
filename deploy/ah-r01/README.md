# AH-R01 Agent Hub-owned Redis candidate

Status: **offline deployment candidate only; production provisioning and migration are not
authorized or executed**

This Compose override adds one Agent Hub-owned Redis 7 service with AOF persistence, a dedicated
volume, an internal-only data network, no host-published port, and a password supplied from an
external protected file. The password is written only to a mode-`0600` configuration file on
container tmpfs; it is not embedded in the Compose file, URL, image, process arguments or receipt.

The Agent Hub override changes only its Redis endpoint from the V1-owned `redis:6379/1` to the
dedicated `agent-redis:6379/0`, mounts the password file, and joins the internal data network. It
retains the existing V1 and n8n networks from the Phase 5 base file, so Redis separation is not
coupled to a video traffic switch.

The password file must be absolute, outside Git, mode `0600` or stricter, and contain 43–128
base64url characters (`A-Z`, `a-z`, `0-9`, `_`, `-`). The production image tag must be resolved to
and recorded as an immutable digest at the action-time owner gate.

Merging this package does not start `agent-redis`, alter `AGENT_REDIS_URL`, stop a writer, export or
restore DB1, recreate Agent Hub, touch V1 Redis, or authorize AH-03.
