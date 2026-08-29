# AH-T01 legacy telemetry deployment gate

Status: **deployment candidate ready; production deploy not authorized or executed**

AH-T01 is a telemetry-only production change candidate. It does not block writes, alter routes,
change ports, change proxy configuration, migrate Redis, switch traffic, stop V1 as a stack, or
authorize AH-03. The candidate recreates only API, worker, renderer and Agent Hub after a new
action-time owner approval.

## Candidate controls

- API and renderer can load the HMAC salt from a read-only secret file. A missing, unreadable,
  relative, empty or shorter-than-32-byte configured file fails startup. Direct salt plus file is
  rejected. When neither is configured, development keeps identity disabled and never logs raw
  identity.
- Events include UTC observation time and a random process-instance UUID. Route and deprecated
  counters remain process-local, while the UUID makes a restart or reset visible.
- The Compose override mounts the secret only into API and renderer and contains no port, network,
  route, Redis or command changes.
- Preflight requires the exact approved commit, a clean tracked tree, protected secret permissions,
  the current four service containers, the same V1 Redis and empty queue/processing lists.
- The deploy runner requires the literal `DEPLOY_AH_T01_TELEMETRY`, records protected config and
  prior image identities, rebuilds/recreates only the four approved services with `--no-deps`, and
  rolls their images back on failure.
- Acceptance uses only 404 read probes with caller `ah-t01-smoke`; it creates no video job and
  performs no external/provider/publish action. Verification rejects raw probe-marker leakage,
  missing fingerprints, disabled identity or unsafe telemetry flags.

The scripts are intentionally inert in Git. Merging this file does not deploy or recreate a service
and does not start the 14-day clock.

## Separate action-time deployment gate

Before execution, the owner must approve all of the following together:

1. exact 40-character deployment commit and exact four service images;
2. change window, operator and rollback operator;
3. absolute protected salt-file location and its custodian, without disclosing the salt;
4. protected receipt/config-backup directory;
5. confirmation that V1 queue and processing remain zero and no render is in flight; and
6. rollback on any health, identity, logging or Redis-container invariant failure.

Only then may the operator run:

```text
AH_T01_EXPECTED_COMMIT=<approved-sha>
AH_T01_TELEMETRY_SALT_HOST_FILE=<protected-absolute-path>
bash scripts/ops/ah_t01/preflight.sh

bash scripts/ops/ah_t01/deploy.sh \
  --expected-commit <approved-sha> \
  --confirm DEPLOY_AH_T01_TELEMETRY
```

No command above is approved by this readiness PR.

## Fourteen complete days

Collect API and renderer logs with timestamps into protected daily inputs. Generate each
identity-safe summary by piping only the selected 24-hour interval to:

```text
python scripts/ops/ah_t01/telemetry_observation.py summarize \
  --window-start <UTC-start> --window-end <UTC-end>
```

The summary fails closed on disabled identity, raw/payload flags, malformed fingerprints, an event
outside the declared interval or a counter gap/reset within one process UUID. It retains only
route/action/status/caller labels, HMAC fingerprints, process UUIDs and counts.

After at least 14 consecutive 24-hour summaries, create an owner-reviewed caller map and restart
ledger from the supplied templates, then evaluate them. Every non-health aggregate requires an
exact accepted service/source/client/caller/action mapping. Every process UUID after the first for
that service requires an accepted restart reason.

Any unexplained caller, unaccepted restart, telemetry gap, missing day, short day, disabled salt or
unsafe field returns `status=FAIL` and `reset_required=true`. The next window starts only after the
cause is resolved and a new owner-accepted start timestamp is recorded.

Even `status=PASS` always emits `ah03_authorized=false`; AH-R01, backup custody, fresh snapshot and a
new owner gate remain mandatory.
