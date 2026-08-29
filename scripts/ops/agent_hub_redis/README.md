# Agent Hub Redis readiness tooling

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

## AH-R01 independence candidate

`run_independence_candidate_drill.py` exercises the dedicated authenticated Redis topology and the
Agent Hub password-file connection with uniquely named/labeled disposable Docker resources. It
checks that Redis has no host port, uses only its internal network, rejects unauthenticated access,
runs non-root and retains an application-written synthetic key after AOF restart. Cleanup refuses
unowned resources and reports zero production access.

`validate_independence_candidate.py` checks the inert Compose/package boundary. The M1 preflight and
provisioner require exact commit/image IDs plus literal owner confirmation and may create only an
empty Agent Hub-owned Redis target. The M2 exporter requires a separate literal confirmation and
streams a namespace-only production read directly to age without plaintext on disk; it cannot
restore, stop a writer or cut over Agent Hub.

No AH-R01 production command is approved merely because it is present in Git. See
`docs/video-factory-v1-decommission/AH_R01_REDIS_INDEPENDENCE_GATE.md` for the separate M1, export,
off-production recovery-custody and M3 owner gates.
