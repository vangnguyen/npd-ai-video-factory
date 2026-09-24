# Agent Hub post-Phase-9 roadmap reconciliation

Task: `AH-POST-P9-ROADMAP-RECONCILIATION`  
Mode: read-only roadmap audit and dependency planning  
Evidence cut: 2026-09-24  
Canonical branch at audit start: `feat/agent-hub-p9-owner-fence-canonical-contract`  
Canonical HEAD at audit start: `7bf0e116ab569e081f8c0c8cf4cbbd3eee4ac043`  
Remote `main`: `43a1cca354d12893ee33b6e43cd9117794f78e04`

This document supersedes historical sequencing that placed Backup Copy 2,
AH-T01B, AH-R01 or V1 retirement on the Phase-9 or Phase-10 product critical
path. It does not replace the safety prerequisites of those legacy workstreams.
No production action is authorized by this document.

## Executive decision

After Phase 9, run two independent lanes:

1. **Product lane:** `PHASE_9_PASS` -> select exactly one Phase-10 channel ->
   preview/test/package -> bounded production gate -> channel acceptance.
2. **Legacy-risk lane:** AH-T01B telemetry, AH-R01 Redis independence, portable
   Copy 2/custody and bridge/catalog work -> fresh pre-AH03 snapshot -> staged
   V1 deprecation and retirement.

There is no authoritative strict dependency from AH-T01B, AH-R01, Copy 2,
AH-03 or V1 retirement to Phase-10 entry. Add such an edge only if the chosen
Phase-10 channel later proves it needs one of them.

## Phase 9 remains P0

Current state: source/package preparation is complete; Gate C authentic cohort
creation is terminal PASS; Owner Gate 2 is approved for the exact one-delivery
operation but has not executed.

Remaining critical outcomes, in order:

1. one authentic `lead_created` delivery under the approved Gate 2;
2. authentic 15-minute SLA evaluation from the original event clock;
3. final bounded production UAT;
4. Owner internal-use acceptance -> `PHASE_9_PASS`.

Gate 2 remains subject to its existing JIT, hash, time, claim and fail-closed
guards. This roadmap audit neither executes nor changes that authority.

## Authoritative inventory

| ID | Purpose | Original dependency | Current dependency | Implementation / tests / CI | Production state | Owner authority | Disposition | Remaining work |
|---|---|---|---|---|---|---|---|---|
| P9-CLOSE | Close Phase 9 internal Journey/Score/NBA/SLA workflow | Historical roadmaps also listed Copy 2 and legacy work | Only the four authentic outcomes above | Phase-9 source merged; Gate-2 focused 49/49, delivery/SLA 90/90, UAT 36/36, failure contracts 18/18, regression 509/509, evaluator 20/20, ops 187 PASS/1 skipped, exact-source CI 4/4 | Gate C PASS; Gate 2 approved but claim/stage/deploy/delivery none | Gate 2 already granted; later final-UAT gate and internal-use acceptance remain | **REQUIRED** | Execute only in current authority; preserve evidence; finish SLA/UAT/Owner acceptance |
| AH-01/01B/01C | Inventory V1 and close unknowns/readiness baseline | Before decommission planning | Fresh volatile refresh only before AH-03 | PRs #37/#39/#40 merged; `UNKNOWN=0`; destructive change remains false | Audit/source only | None for completed audit | **ALREADY_SATISFIED** | Do not reopen; refresh only volatile facts at pre-AH03 |
| AH-02 | Versioned Agent Hub–Video Factory boundary | Before production bridge/deprecation | Live bridge acceptance belongs to AH-03 | PR #38 merged; offline/mock contract and tests PASS | No live V2/V3 call | Production bridge requires separate gate | **ALREADY_SATISFIED** for source; live part **MERGE_WITH_OTHER** | Validate accepted live bridge/policy before AH-03 |
| AH-T01B | Identity-safe V1 API/renderer telemetry and 14-day caller map | Historically serialized after Phase 9 | Required only for AH-03/V1 retirement | PRs #41/#43/#44 merged; target/rollback locked to API+renderer; historical 7-check CI green | No deployment PASS receipt; observation `NOT_STARTED` | Fresh exact deployment gate, then Owner accepts observation | **REQUIRED** for legacy lane | Refresh current-main package; deploy API+renderer only; verify telemetry; obtain 14 complete accepted days |
| AH-T01B scheduler V3/V3.1 E+A/W32Time | Unattended trigger provenance for an old retry path | Historical scheduled execution | None for operator-controlled telemetry deployment | Historical evidence retained; automation paused; E+A live integration incomplete | Never produced a successful deployment | Only if Owner explicitly chooses scheduling again | **SUPERSEDED** | Do not revive for a normal operator-controlled gate |
| AH-R01 | Move Agent Hub DB1 to Agent Hub-owned Redis | Before stopping V1-owned Redis | Required only for safe V1 retirement and ownership isolation | PR #42 merged; M0/offline export/restore/parity PASS; historical 7-check CI green | M1–M4 not executed | M1, M2, M3 and M4 acceptance are distinct boundaries | **REQUIRED** for legacy lane | M1 empty target; M2 portable encrypted export/rehearsal; M3 quiesced cutover; M4 7–14-day acceptance |
| COPY2 | Independent V1 backup copy and portable recovery custody | Before V1 shutdown | Required before disable/removal; not Phase 10 | Primary 1.896-GB encrypted bundle restore-tested; no independent Copy 2; DPAPI CurrentUser only | Not created | Exact destination/custodians/key escrow/retention/action gate | **MERGE_WITH_OTHER** legacy custody prerequisite | Independent storage copy, checksum parity, portable escrow, isolated recovery, named custody and retention acceptance |
| DB1 portable backup | Portable namespace recovery for Agent Hub | Sometimes listed as a standalone backup task | AH-R01 M2 | Phase-9 backup evidence is dated and DPAPI-only; latest observations differ in key count | No AH-R01 production export | AH-R01 M2 authority | **MERGE_WITH_OTHER** | Bind to fresh M2 export/restore; do not create a duplicate track |
| AH-03 / Stage A | Block/deprecate new V1 work while preserving reads/compatibility | After telemetry, Redis split and custody | T01B 14-day acceptance + R01 M4 + Copy 2 + accepted catalog/bridge + fresh snapshot | Readiness/source partially prepared; no production deprecation | `NO-GO` | Fresh pre-AH03 Owner gate | **REQUIRED only if retiring V1** / partially satisfied | Fresh snapshot; write fencing; attributable compatibility/deprecation; no deletion |
| AH-04 | Historical label for later V1 disable/rollback | After AH-03 | Covered by staged retirement B–E | No authoritative independent contract, entry/exit criteria, PR or gate | `NO-GO` | No separate gate should be invented | **MERGE_WITH_OTHER** | Remove standalone box; use Stages B–E |
| V1-RETIRE | Drain, disable, observe and ultimately remove V1 | After AH-03 | Stage A -> B drain -> C disable -> D 14-day observe -> E removal | Staged shutdown/rollback plan exists; no execution | Shutdown/removal `NO-GO` | Separate gates by risk, with deletion separate from disable | **DEFER** from Phase-10 critical path; still required before removal | Preserve compatibility/rollback; execute stages only after prerequisites and exact approvals |
| RCA16–18A minimal product pieces | Authentic SLA/cohort, bounded no-eviction guard | Phase-9 closure | Already absorbed into Phase 9 | Canonical Phase-9 packages/tests include the needed bounded pieces | Covered only within bounded Phase-9 authority | Existing Phase-9 gates | **ALREADY_SATISFIED / MERGE_WITH_PHASE9** | Do not reopen as infrastructure work |
| FUTURE-CUSTODY | Generalized retention, all-store integration, PG journal, S3 Object Lock, issuer/KMS/service identities, Google-sub enrollment | Historical hardening program | Triggered only by future eviction/trim/hold-release/archive/legal need | Design/source branches exist but are not ancestors of canonical HEAD; production bindings absent | Not activated | Future consolidated custody gate only if triggered | **DEFER** / optional hardening | Keep evidence; select backend/identities only when product or policy evidence requires it |
| REJECTED-CUSTODY | Email/role-alias authority, shared credentials, Memory/SQLite production authority, stale-hash trim, implicit eviction | Historical alternatives | None | Rejected by RCA evidence | None | None | **DROP_NOT_NEEDED** | Preserve history; never treat as fallback |
| PHASE10 | Execute one external channel under control | Historically after Phase 9 | Strictly `PHASE_9_PASS`; legacy lane is independent unless a chosen channel proves otherwise | Objective exists; no first-channel source/package/CI yet | `NO-GO`; all external write capabilities disabled | Per-channel execution and acceptance gates | **REQUIRED** product lane | Choose first channel; bind account/action/caps; implement preview, approval, idempotency, rollback, reconciliation and channel acceptance |
| PHASE11/12 | Creative/CRO optimization and executive revenue control tower | After accepted preceding product capability | Phase-specific scopes not yet prepared | Roadmap statement only | Not started | Future gates | **DEFER** | Reconcile after first Phase-10 channel acceptance |

No open GitHub PR existed at the evidence cut. Remote `main` remained at the
Phase-9 source baseline. Historical branch presence is evidence, not active
roadmap authority.

## AH-T01B acceptance

Static/local preparation may run independently: refresh source and image
provenance, tests, target-isolation checks, strict-SSH proof, evaluator and
package seals.

Production acceptance requires all of the following:

1. fresh exact source/images/window/operators/salt/receipt bindings;
2. queue=0, processing=0 and no render in flight;
3. worker, Agent Hub, Redis, Caddy, networks, ports and `AGENT_REDIS_URL`
   immutable;
4. deploy/rollback target exactly `{api, renderer}`;
5. only non-business safe probes and zero job/provider/publish action;
6. API legacy-route plus renderer `/render` and `/media` coverage without raw
   identity, payload or secret leakage;
7. PASS receipt defines `verified_at` and starts observation;
8. fourteen complete consecutive days with no telemetry gaps, unexplained
   caller, unaccepted restart, disabled identity or counter discontinuity;
9. Owner acceptance of the caller map and observation report.

A PASS still leaves `ah03_authorized=false` until every other AH-03 prerequisite
and a fresh Owner gate pass.

## AH-R01 acceptance

AH-R01 has no strict dependency on Phase 9 or AH-T01B. Static preparation can
run now; production windows should avoid Phase-9 evidence capture and can run
in parallel with the AH-T01B observation clock.

- **M1:** empty authenticated target, AOF healthy, internal-only/no host port;
  V1 Redis and Agent Hub identities unchanged.
- **M2:** fresh namespace-only encrypted export with no plaintext disk; exact
  key/type/TTL/content parity, zero outside-namespace keys, restart persistence,
  read-model probe and rollback rehearsal. This is also the DB1 portable-backup
  closure.
- **M3:** quiesce Agent Hub writers only; final stable export/restore/parity;
  change only the Agent Hub Redis binding; recreate Agent Hub only; rollback on
  regression.
- **M4:** preserve both instances/evidence for 7–14 days and obtain Owner
  acceptance before old DB1 is archived.

Historical key counts are not authority for M2; JIT export and parity are
mandatory.

## Phase 10 definition

### Authoritative objective

Move from recommendation/preview to controlled execution of exactly one
approved channel capability at a time: Meta Ads, Google Ads, a dedicated Email
provider, a dedicated Zalo/ZBS provider, or the WordPress landing-page
publisher.

### Entry criteria

1. `PHASE_9_PASS` and Owner internal-use acceptance;
2. exactly one selected channel, action, account and allowlist/cap policy;
3. least-privilege credentials with named custody;
4. preview/dry-run, approval records, idempotency and reconciliation;
5. exact rollback/containment and monitoring plan;
6. source/tests/CI/package PASS;
7. explicit bounded production Owner gate.

### Exit criteria

For one channel: channel-specific production/readback/rollback evidence and
Owner acceptance PASS. The repository does not yet define whether one accepted
channel or all five channels completes Phase 10 globally; that is an exact
scope gap and must not be invented.

### Remaining scope gaps

- first channel and business KPI are not selected;
- account/action/volume/spend/recipient allowlists and caps are absent;
- credential/custodian contract is absent;
- provider payload, rate-limit, idempotency, reconciliation, monitoring and
  rollback contracts are absent;
- source/package/CI and exact Owner-gate templates for the first channel are
  absent;
- phase-wide completion semantics are absent.

Production impact may include external provider/CMS writes, customer contact or
spend. All remain disabled until the channel-specific gate.

## Dependency DAG

### Strict dependencies

```text
Gate 2 authentic lead_created
  -> authentic SLA result
  -> final production UAT
  -> Owner internal-use acceptance
  -> PHASE_9_PASS
  -> choose one Phase-10 channel
  -> channel package/preview/rollback PASS
  -> channel production gate
  -> channel acceptance

AH-T01B deploy PASS -> 14 accepted telemetry days -----------+
AH-R01 M1 -> M2 -> M3 -> M4 -------------------------------+
Copy2/custody -> isolated portable recovery PASS -----------+--> fresh pre-AH03 snapshot
accepted bridge/policy + catalog actions + mapped callers ---+    -> Stage A -> B -> C -> D -> E
```

### Soft dependencies

- Prefer legacy production windows after Phase 9 closes to reduce operational
  interference; this is scheduling, not a technical dependency.
- Reuse Phase-9 protected-service inventory and evidence-capture patterns, but
  refresh volatile values JIT.
- Phase-10 channel design may begin statically before `PHASE_9_PASS`; production
  execution may not.

### Independent work

- AH-T01B static packaging, AH-R01 M1/M2 preparation, Copy2 custody planning,
  catalog/bridge review and first-channel Phase-10 definition can run together.
- AH-T01B 14-day observation and AH-R01 M3/M4 can run together under separate
  gates.
- Generalized custody hardening remains outside both critical paths unless a
  concrete trigger is proven.

## Fast-track waves

| Wave | Parallel work | Blocking work | Owner boundaries | Terminal state |
|---|---|---|---|---|
| 0 | None outside already prepared read-only support | Gate 2 delivery -> SLA -> final UAT -> internal-use acceptance | Current Gate 2 already granted; later UAT gate and acceptance | `PHASE_9_PASS` |
| 1 | Refresh AH-T01B package; refresh AH-R01 snapshots/dossiers; choose Copy2 destination/custody; audit bridge/catalog; define first Phase-10 channel | No production work | None for audit/tests/CI/package prep | All next packages `READY_FOR_OWNER_GATE` |
| 2 | Non-overlapping AH-T01B deploy, AH-R01 M1/M2 and Copy2 creation/recovery; build first-channel source/preview | Exact current baselines and respective gates | Separate T01B, R01 and custody authorities | T01B clock running; R01 target/export proven; Copy2 portable PASS; Phase10 candidate local PASS |
| 3 | T01B observation; AH-R01 M3/M4; finalize first-channel package | Phase9 PASS for Phase10 execution; each lane's own acceptance | R01 cutover/acceptance; T01B observation acceptance | Agent Hub Redis-independent; caller map accepted; Phase10 execution-ready |
| 4 | First Phase-10 channel gate/acceptance and, independently, legacy prerequisite convergence | Phase10 does not wait for legacy; AH-03 waits for all legacy prerequisites | Phase10 per-channel gate; fresh AH-03/Stage gates separately | One controlled channel accepted; legacy proceeds only as ready |

## Owner intervention plan

The current Gate 2 approval needs no new Owner action unless it aborts, expires
or drifts. After it, the known minimum is **16 new authority or acceptance
decisions** through acceptance of the first Phase-10 channel and V1 Stage E:

1. Phase-9 final-UAT action gate;
2. Phase-9 internal-use acceptance;
3. first Phase-10 channel execution gate;
4. first-channel acceptance;
5. AH-T01B deployment gate;
6. AH-T01B 14-day observation acceptance;
7. AH-R01 M1;
8. AH-R01 M2;
9. AH-R01 M3;
10. AH-R01 M4 acceptance;
11. Copy2/custody action and acceptance, batched under one exact dossier;
12. V1 Stage A deprecation;
13. Stage B drain;
14. Stage C disable;
15. Stage D observation acceptance;
16. Stage E removal.

Of these, **12 known production-access/action windows remain including the
already-approved Gate 2**; eleven will require fresh authority. Observation and
business acceptance signoffs are not mutation windows. Data deletion/secret
expiry requires an additional separate decision if pursued, and each additional
Phase-10 channel adds its own execution and acceptance boundaries.

Preparation, tests, CI, documentation, reseal and read-only audit must not
create extra Owner gates. Do not create a standalone AH-04 gate or one gate per
RCA16–18A artifact.

## Completion measures

### Phase 9

- **Implementation:** 100% of the currently defined source, package, fixture
  and failure-contract preparation is complete.
- **Acceptance:** 0/4 remaining terminal outcomes are complete. Gate 2 is
  approved but not executed; approval is not acceptance.

### Entire Agent Hub roadmap

Use accepted terminal outcome groups, not source-only readiness:

- product roadmap: phases 1–8 complete; phases 9–12 remain at their respective
  acceptance states -> 8/12;
- independent legacy lane: AH-01 and AH-02 complete; AH-T01B, AH-R01, Copy2 and
  AH-03/retirement remain -> 2/6;
- combined evidence-based estimate: **10/18 = 55.6%** terminal outcome groups.

This denominator excludes AH-04 because it is merged into staged retirement and
excludes optional/deferred custody hardening. Phase-9 implementation readiness
is not counted as Phase-9 acceptance. Phase-10 completion will remain a range
until Owner defines whether one or all channels complete the phase.

## Recommended action after `PHASE_9_PASS`

Immediately start Wave 1 in parallel and ask Owner to select the first Phase-10
channel. Prepare that channel's exact source-only contract while separately
refreshing AH-T01B, AH-R01 and Copy2 dossiers. The next product-value gate is the
first bounded Phase-10 channel; the next legacy-risk gates are AH-T01B and
AH-R01 M1/M2. Neither lane should serialize the other.

## Evidence basis

- `docs/ARCHITECTURE_ROADMAP.md`
- `docs/PHASE_9_MARKETING_PILOT.md`
- `docs/AGENT_HUB_HANDOFF_AND_ROADMAP_20260911.md`
- `docs/video-factory-v1-decommission/AH_T01_TELEMETRY_DEPLOYMENT_GATE.md`
- `docs/video-factory-v1-decommission/AH_R01_REDIS_INDEPENDENCE_GATE.md`
- `docs/video-factory-v1-decommission/AGENT_HUB_REDIS_OWNERSHIP_MIGRATION_PLAN.md`
- `docs/video-factory-v1-decommission/BACKUP_CUSTODY_PLAN.md`
- `docs/video-factory-v1-decommission/PRE_AH03_SNAPSHOT_RUNBOOK.md`
- `docs/video-factory-v1-decommission/SHUTDOWN_PLAN.md`
- `docs/AH_P9_MINIMAL_INTERNAL_AUDIT_LANE.md`
- `HANDOFF.md` and `handoff.json`
- external Gate-2 and RCA16–18A evidence bundles referenced by the repository handoff.

## Safety result

- Production writes: 0
- Real provider calls: 0
- Actual cost: 0
- Phase 10: `NO-GO`
- AH-T01B/AH-R01/AH-03/AH-04/V1 retirement: not executed
