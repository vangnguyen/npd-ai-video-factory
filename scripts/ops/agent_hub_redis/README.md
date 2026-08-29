# Agent Hub Redis M0 readiness tooling

These tools are limited to AH-01C offline proof. They do not connect to production, migrate DB1,
change `AGENT_REDIS_URL`, stop a writer, stop Video Factory V1, or authorize AH-03.

`run_synthetic_restore_drill.py` creates two disposable Redis 7 containers whose ports bind only
to host loopback. It exercises the version 2 Agent Hub namespace contract with a string, list,
sorted set and expiring lease. The drill proves:

- namespace-only export and a stable source fingerprint;
- absolute TTL preservation;
- fail-closed behavior for unsupported types, checksum corruption, namespace mismatch and a
  non-empty target;
- value/type/key/TTL parity after restore;
- explicit replace as a synthetic rollback rehearsal; and
- target persistence after restart.

The target uses a uniquely named temporary volume and AOF. Cleanup removes only resources created
by the current run after verifying the `npd.ah01c.synthetic=true` label. No Redis values are emitted
in the report.

Run from the repository root with the Agent Hub development dependencies already installed:

```text
python scripts/ops/agent_hub_redis/run_synthetic_restore_drill.py
```

A PASS is M0 tooling evidence only. A protected production DB1 export, outside-production restore,
read-model parity, target provisioning, cutover and rollback window each remain separately
owner-gated.
