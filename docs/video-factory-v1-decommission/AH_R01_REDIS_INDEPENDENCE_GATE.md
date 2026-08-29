# AH-R01 Agent Hub Redis independence gate

Status: **offline candidate PASS; production provisioning, export, rehearsal and cutover are not
authorized or executed**

AH-R01 separates Agent Hub data ownership from the Redis instance owned by Video Factory V1. This
candidate does not stop/restart V1, stop Agent Hub, export DB1, create a production volume/network,
change `AGENT_REDIS_URL`, restore data, recreate Agent Hub, switch traffic, delete the old DB1 copy,
or authorize AH-03.

## Candidate boundary

- `agent-redis` is a dedicated Redis 7 service with AOF, its own persistent volume, an internal
  Agent Hub data network and no host-published port.
- Authentication comes from an external base64url password file. The password is absent from Git,
  the Redis URL, Compose rendering, image, process arguments and receipts. Redis reads a mode-0600
  config on tmpfs and runs as uid 999.
- Agent Hub can read the same password file and passes it separately to the Redis client. A
  relative, unreadable, weak/malformed file or a URL that also embeds a password fails closed.
- The application namespace remains `npd:agent-hub:v1`; the dedicated instance uses DB0. V1 DB0
  is never copied.
- The Agent Hub service retains its existing V1 and n8n networks. Only the Redis data endpoint and
  password-file binding change at the later cutover; video routes and traffic do not.

The disposable candidate drill proved Compose topology, no host port, authentication rejection,
Agent Hub password-file connectivity, non-root Redis execution and AOF persistence across restart.
It used uniquely named/labeled local resources, removed them after the test and reported
`production_connection_performed=false` and `production_write_performed=false`.

## M1 — separate target provisioning owner gate

M1 creates only the empty target Redis/network/volume. It does not recreate Agent Hub or touch the
source. Before execution the owner must approve together:

1. exact 40-character Git commit;
2. exact locally present Redis image ID/digest;
3. production change window and rollback operator;
4. protected password-file path/custodian, without revealing its value;
5. protected receipt root and target network/volume names; and
6. automatic cleanup limited to a newly created, still-empty, AH-R01-labelled target on failure.

The action-time commands are:

```text
AH_R01_EXPECTED_COMMIT=<approved-sha>
AH_R01_EXPECTED_REDIS_IMAGE_ID=<approved-sha256-image-id>
AH_R01_REDIS_PASSWORD_HOST_FILE=<protected-absolute-path>
bash scripts/ops/agent_hub_redis/ah_r01_preflight.sh

bash scripts/ops/agent_hub_redis/ah_r01_provision.sh \
  --expected-commit <approved-sha> \
  --confirm PROVISION_AH_R01_REDIS
```

No command above is approved by this readiness PR. M1 acceptance requires the receipt to show an
empty authenticated target, AOF healthy, no host port, and unchanged Agent Hub and V1 Redis
container identities.

## M2 — encrypted export and off-production rehearsal owner gates

The initial DB1 export is a separate **production read** gate. The owner must approve the exact
commit/maintenance image, age public-recipient file, independent encrypted destination and output
name. The private recovery identity must not be present on the production host. The runner streams
the namespace-only logical export directly into age; plaintext is never written to disk. It never
restores or quiesces a writer. Identity-safe before/after source snapshots also require zero keys
outside the Agent Hub namespace and retain only counts, type histograms and aggregate hashes:

```text
bash scripts/ops/agent_hub_redis/ah_r01_export_encrypted.sh \
  --expected-commit <approved-sha> \
  --recipient-file <portable-public-age-recipient-file> \
  --output <independent-storage/agent-hub-db1-YYYYMMDDTHHMMSSZ.age> \
  --confirm EXPORT_AH_R01_DB1_ENCRYPTED
```

Off-production rehearsal is a third gate on an isolated host. The owner temporarily supplies the
portable age identity under the agreed custody procedure; Codex must not retain it. Decrypt only
through a pipe into a fresh isolated Redis 7 target, then require all of the following evidence:

- ciphertext checksum and age decryption PASS, with no plaintext backup file;
- namespace, key count, type histogram, TTL count, canonical namespace hash and content hash parity;
- no key outside `npd:agent-hub:v1:*`;
- `python -m npd_agent_hub.redis_read_model_probe` PASS without values or identifiers in output;
- target AOF persistence and the same verification/read-model result after target restart; and
- a rollback rehearsal into another fresh disposable target.

The recovery identity and target password remain outside Git, docs, issues, chat, receipts and the
encrypted payload. A production export is not accepted merely because age encryption exits zero;
the isolated restore, parity and restart evidence must also pass.

## M3 — quiesced cutover remains a future owner gate

This PR intentionally provides no automatic production cutover. M3 must be assembled from a fresh
snapshot and approved at action time. The required sequence is fixed:

1. verify M1 and M2 receipts plus a fresh source snapshot;
2. record the current Agent Hub image/config and rollback endpoint;
3. quiesce Agent Hub writers only; do not stop V1 Redis;
4. wait for/release the Agent Hub scheduler lease under the accepted procedure;
5. create a new final encrypted export and require a stable source fingerprint;
6. restore into the empty Agent Hub-owned target and require checksum/read-model parity;
7. change only the Agent Hub Redis endpoint and its password-file binding;
8. recreate Agent Hub only and verify health plus read models before any controlled mock write;
9. preserve old DB1 and the final export throughout the accepted 7–14 day rollback window; and
10. roll back to the old endpoint on any health, parity, persistence or read-model regression.

Do not merge divergent writes automatically. Do not stop/delete V1 Redis after a successful Agent
Hub cutover. AH-T01, 14 accepted telemetry days, protected backup copy 2, portable V1 recovery
custody, publication actions, a fresh pre-AH-03 snapshot and a new owner gate remain independent.

Every AH-R01 report must keep `ah03_authorized=false`.
