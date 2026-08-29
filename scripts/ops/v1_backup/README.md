# V1 backup tooling boundary

These tools support an owner-approved, stream-only V1 Redis DB0 capture and an isolated local
restore drill. They do not stop services, change Redis persistence, create a VPS-side temporary
file, call `SAVE`/`BGSAVE`, copy Agent Hub DB1, inspect secret backups, or restore production.

## Files

- `export-db0-readonly.sh` runs inside the existing Redis container and emits a lossless JSON
  export to stdout. It fails closed on a non-DB0 target, unexpected key/type, source drift or an
  expired key. Its stdout contains sensitive serialized job records and must be piped directly to
  an approved encrypted off-production destination; never display, log or commit it.
- `verify_redis_export.py validate` checks the export boundary and per-key serialized checksums
  without printing values. Pass `-` as the export path to read the sensitive JSON from stdin without
  creating a plaintext temporary file.
- `verify_redis_export.py restore-isolated` restores only to a running Redis 7 container that has
  label `npd.ah01b.restore-test=true`, uses `--network none`, publishes no port and has an empty
  DB0. It verifies types, serialized checksums, TTL semantics and queue lengths.
- `verify_redis_export.py verify-isolated-existing` repeats the same checks without issuing
  `RESTORE`. Use `--phase post-restart` after independently recording a container restart. The
  phase is an operator assertion in the report; the tool verifies the resulting data, not the
  lifecycle event itself.

The restore report intentionally sets `complete_v1_bundle_restore=false`. A PASS from this tool
covers only Redis DB0. The overall V1 gate remains NOT RUN until storage, exact image exports,
contracts/configuration and restart checks pass in the same encrypted bundle drill described in
`docs/video-factory-v1-decommission/V1_BACKUP_RESTORE_PLAN.md`.

Production capture and any off-production bundle path/encryption recipient remain explicit owner
inputs. Do not place captured data under the repository.
