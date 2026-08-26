# HMAC receipt key rotation

## Purpose and safety boundary

Agent Hub signs each new attribution delivery or heartbeat receipt with one active key.
Verification uses the receipt's `key_id` to select either that active key or a retained
historical verify-only key. Historical keys can never be selected for signing.

This operation changes only Agent Hub receipt cryptography. It does not enable external
notifications, Ads mutation, CRM write, customer messaging, Email/ZBS delivery, CMS
publishing, experiment execution or the n8n executor.

## Configuration contract

The active generation is held in the protected Agent Hub env file:

```text
AGENT_ATTRIBUTION_ACTIVE_KEY_ID=npd-attribution-v2
AGENT_ATTRIBUTION_ACTIVE_SIGNING_KEY=<secret>
```

Historical verification keys are a protected JSON object on the host, mounted read-only
inside Agent Hub:

```json
{
  "npd-attribution-v1": "<verify-only-secret>"
}
```

The paths are configured separately so a host path is never confused with a container
path:

```text
AGENT_ATTRIBUTION_VERIFICATION_KEYS_HOST_FILE=/etc/npd-ai/agent-attribution-verification-keys.json
AGENT_ATTRIBUTION_VERIFICATION_KEYS_FILE=/run/secrets/agent-attribution-verification-keys.json
```

The legacy `AGENT_ATTRIBUTION_RECEIPT_KEY_ID` and
`AGENT_ATTRIBUTION_RECEIPT_SIGNING_KEY` variables remain accepted. The guarded helper
synchronizes them to the active generation only for rollback compatibility. No secret is
stored in Redis, a receipt, an audit event, deployment receipt, log, API response or Git.

## Guarded rotation runbook

1. Confirm no receipt signing incident is open and record the current active `key_id`.
   Never print either key value.
2. Back up the namespace with the existing Phase 5 backup command. Confirm its path and
   retain the current rollback image/deployment receipt.
3. Run preflight against the unchanged configuration.
4. Rotate with a new, unused key ID. The helper backs up the env file and any existing
   verification file, moves the old active generation into the historical file, creates
   a random new active key, writes files atomically with restrictive permissions and does
   not print secret material:

   ```bash
   export AGENT_HUB_ENV_FILE=/etc/npd-ai/agent-hub.env
   bash scripts/phase5/configure-attribution-delivery.sh \
     --apply \
     --rotate \
     --new-key-id npd-attribution-v2
   ```

5. Run Phase 5 preflight again. It validates file presence, permissions, JSON shape,
   minimum key length and confirms the active ID is not in the historical map.
6. Use the existing guarded deploy. Only Agent Hub may be recreated. Do not recreate the
   existing n8n, Caddy, Redis, Postgres, API, worker or renderer containers.
7. Submit one bounded read-only delivery or heartbeat and confirm its receipt has the new
   active `key_id` and verifies successfully.
8. Verify one retained receipt from the prior generation and one new receipt through the
   existing verification APIs. Both must be valid; neither operation may append an audit
   write or call an external system.
9. Run local and public smoke, confirm `N8N_AGENT_EXECUTOR_WEBHOOK_URL` remains blank and
   retain the new deploy receipt, backup path and rollback image.

## Rollback

If deploy or dual-generation verification fails:

1. Stop further receipt production for this bounded change; do not remove historical
   evidence.
2. Restore the backed-up env file and verification-key file as one configuration set.
3. Run preflight, then the existing guarded Agent Hub rollback command.
4. Verify a receipt from the restored active generation and the prior historical
   generation.
5. Document the failure. If receipt semantics or scheduler behavior changed, restart the
   relevant acceptance window.

Redis restore is never automatic. Rotating or rolling back a key does not mutate existing
receipts.

## Accepted production drill — 2026-08-26

The owner-gated production drill completed without changing the AgentHub application
version or enabling a side effect:

- old active generation: `npd-attribution-v1`;
- new active generation: `npd-attribution-v2`;
- v1 retained in the historical verify-only file;
- pre-rotation namespace backup:
  `/var/backups/npd-agent-hub/hmac-rotation-20260826T100000Z/agent-hub-before-rotation.json`;
- configuration backup:
  `/var/backups/npd-agent-hub/hmac-rotation-20260826T100000Z/config/agent-hub.env-20260826T095854Z`;
- deployment receipt:
  `/var/lib/npd-ai/agent-hub-deployments/deploy-20260826T095855Z.json`;
- rollback image: `npd-agent-hub:rollback-20260826T095855Z`;
- retained v1 delivery and heartbeat receipts verified valid;
- new v2 heartbeat receipt `ahr_e7a10db514c10c02bc7e908b` verified valid;
- only the AgentHub container was recreated; it returned healthy with restart count `0`;
- public readiness returned 200, OpenAPI remained `0.13.0`, and the Command Center kept
  its authentication redirect;
- external notifications and production writes remained false, and the n8n Agent
  executor URL remained blank.

No key value is included in this evidence. The drill proves configuration and historical
verification behavior; it is not permission to retire v1.

## Historical key retirement

Removing a historical key intentionally makes receipts carrying that `key_id` invalid
after the next Agent Hub restart. Retire a key only after its receipt-retention period has
expired, evidence has been archived under the approved retention policy, and the owner has
approved the loss of online verification. Back up the key file before removal and verify
that unknown IDs fail closed without disclosing key material.
