# Fresh pre-AH-03 snapshot runbook

Status: **prepared; not due and not executed**

This snapshot must be captured immediately before an AH-03 proposal, not during AH-01C while
prerequisites remain open. It is read-only and does not authorize a deployment, write block,
traffic change, port change, Redis move, storage mutation or V1 stop.

## Entry conditions

- publication catalog owner acceptance recorded;
- two protected V1 backup copies, named custodians, accepted retention and portable recovery PASS;
- Agent Hub Redis migration completed under separate AH-R01 approval with restore/rollback evidence;
- identity-safe V1 telemetry deployed under a separate approval and 14 complete days accepted;
- renderer caller and every other observed caller mapped or migrated;
- exact-main regression green and no unreviewed production drift.

If any entry condition is false, produce no AH-03 proposal and keep `V1 DECOMMISSION = NO-GO`.

## Snapshot contents

Capture one timestamped evidence set containing:

1. repository `main` SHA, production checkout SHA, exact container image/config IDs, restart counts
   and service health;
2. V1 DB0 key/type/TTL counts, 12 retained job metadata records, queue/processing lengths and a
   read-only source fingerprint;
3. Agent Hub target Redis ownership, namespace/type/TTL counts, persistence health and accepted
   AH-R01 evidence reference;
4. storage ownership manifest, file counts/bytes/checksums and zero files outside known ownership
   classes;
5. refreshed WordPress, primary Facebook Page, n8n, publisher state, Agent Hub and repository
   reference searches plus the accepted archive/redirect catalog;
6. the complete 14-day telemetry interval, counter continuity, caller mapping and zero-unexplained
   assertion;
7. both protected backup locations by storage class, manifest/checksum parity, custodian roles,
   retention and last recovery-test status; and
8. public route exposure, Caddy state and an explicit statement that no configuration was changed.

Do not include secrets, raw business payloads, raw IP addresses, raw user agents or private media in
the evidence set.

## Fail-closed rules

Abort the proposal on any new component, ownership gap, checksum drift, positive TTL without an
accepted rule, DB1 ownership regression, queue/processing activity, unexplained caller, telemetry
gap, route/catalog mismatch, missing protected copy, failed recovery check or production/repository
provenance mismatch.

The resulting snapshot expires on any production change. Owner approval of that exact fresh
snapshot is the final gate to begin AH-03 compatibility/deprecation work; it is still not deletion
approval.
