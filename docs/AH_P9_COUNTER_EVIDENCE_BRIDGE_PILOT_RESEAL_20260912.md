# AH-P9-RCA-05: counter evidence bridge and fresh pilot reseal

Workstream: Agent Hub ONLY. Preparation verdict: REVIEW_REQUIRED.
Owner execution approval: NOT_GRANTED. No pilot is executed.

Owner authorized exactly four existing Video Factory DB0 counters as an
evidence-only exception. It does not open Video Factory work or execution.
The immutable exception receipt SHA-256 is
`f523cc2a7df00459fab545e1a4d8e3a82733555efe09acf93fa819fbf247e4e6`.

| Existing counter | Required observation | Observed value |
| --- | --- | ---: |
| video_factory_job_count | Existing npd:video-job:* key count | 12 |
| video_factory_queue_count | LLEN npd:video-jobs:queue | 0 |
| video_factory_processing_count | LLEN npd:video-jobs:processing | 0 |
| video_factory_in_flight_count | Existing non-terminal job status/stage rule | 0 |

Identifiers were extracted from the existing safety contract. Before any
query, the exact identifiers, query, target and response format were saved in
COUNTER_QUERY_PLAN.json and COUNTER_QUERY_SPEC.json. Target: root SSH on
157.10.201.169, Agent Hub container / configured Redis endpoint, database 0.
One atomic EVAL_RO computes only these four integers with SCAN/GET/LLEN.
The Redis server rejects writes from EVAL_RO; no EVAL fallback exists.
Job keys/values remain inside Redis; only counter values and sanitized
metadata leave the query. No VF workflow/provider/config/budget API is called.

Every fresh transport receipt preserves stdout/stderr hashes and lengths,
child exit code, invocation UUID, UTC timestamps and stdin/command bindings
atomically before verification. All accepted four-counter observations are
12/0/0/0, with no inferred zero or substituted historical value. Observations
were refreshed only as necessary for changed HEAD/freshness/package validation.
The proof concerns this task's read-only operations; it does not attest to
unrelated actors across the whole production system.

Protected service baseline: 18 services, accepted canonical digest
`6e0167343174e4cb719b3799015dc5d438b8cdcc545774dc72d53f61cf2c648e`. Running target ID/image/config/files/health remain unchanged.
Fresh encrypted namespace and rollback-image capture and actual isolated RAM
Redis restore pass: 10,692/10,692 keys before and after fixture restart.
Roles/whoami 3/3 and Agent Hub counters pass. No production Redis key/value
write, service restart, claim, job creation or workflow execution occurs.

The historical protected-service drift remains confirmed. Historical child
stdout/exit/UUID remain unavailable. Owner's previously accepted fresh
substitution is preparation evidence, not recovered historical primary data.
The terminal operation/approval/package remain immutable and cannot be reused.

## Source and dispatcher review

New files are confined to scripts/ops/agent_hub_phase9. Agent Hub application,
Video Factory application, deploy/config/workflow trees are unchanged. The
candidate image application's tree equals exact main 43a1cca354d12893ee33b6e43cd9117794f78e04.
Fresh image archive headers/tag are repacked and every OCI blob reverified;
no Docker build/load/pull, production staging or deployment is performed.

The fresh runtime retains 46 audited helpers. Only fresh window guards,
authorization parser, preparation preflight and claim hash retention change.
The old embedded DB0 probe had invalid indentation; the new compiled probe
uses the same exact four-counter EVAL_RO bridge. All embedded Python probes
compile. Identity, HEAD, snapshot, counter, exception and dependency binding
are mandatory. Preparation preflight has no mutation window or action.
Claim/deploy require separately granted owner approval and a fresh UTC window.

Package/manifest/file-set verification occurs before and after child preflight.
Missing/modified evidence, extra file, manifest mismatch, wrong HEAD/snapshot/
baseline, stale counter, wrong operation and dependency hash all deny before
the child. Actual sealed dispatcher integration uses strict pinned OpenSSH,
performs only read-only observations and verifies all eleven returned counters.
The runner refuses --execute with absent owner execution approval before any
transport/claim/staging. Confirmation is a new random 32-byte value held only
in CurrentUser DPAPI with operation/HEAD/snapshot-specific entropy. Public
files contain hashes only. No plaintext approval or token is generated.

Local checks: 68 ops tests, 299 Agent Hub tests, 20 mock evals, 12 RCA tests,
31 historical gate fixtures, 24 transport fixtures; all pass. Ten tamper cases
also pass on copies of the actual package. Fixture PILOT_PASS is test output,
not a real pilot. Code HEAD 726bc9c93818d098703aa3f7774197e8590599a4 has actual CI 3/3 PASS;
source exact-main has 7/7 PASS. The docs/handoff commit requires its own exact
HEAD CI; the final receipt records the actual result, not a forecast.

## Final gate and owner review

New final operation identity: `PHASE9-LIMITED-PILOT-RCA05-29db0877-9203-4796-bf3a-8046ab19a0f5`.
The code-HEAD package is retained as preparation proof only. The final package
is built after the committed handoff HEAD has actual CI PASS, a refreshed
full snapshot and four-counter receipt. It uses fresh confirmation material.
Final status/hashes are externally sealed to avoid a self-referential commit.
The canonical final receipt and package verifier must both pass and bind the
current repository HEAD; absent/mismatched final evidence means HOLD.

Final evidence: `C:/Users/VANG NGUYEN/Documents/Codex/2026-09-12/referenced-chatgpt-conversation-this-is-an-2/outputs/ah-p9-rca-05-20260912`.
Read HANDOFF_RECEIPT.json, CI_EVIDENCE.json, pilot-package.SEAL.json,
pilot-package.DISPATCHER_INTEGRATION.json and pilot-package.TAMPER_TESTS.json.
All dependency hashes are in RESEALED_DEPENDENCIES.json and the externally
anchored pilot-package/PACKAGE_MANIFEST.json. The private protected backup
and confirmation custody are excluded from the public review archive.

Counter freshness is limited to 600 seconds before initial dispatch. Owner
review does not stop that clock. Expiry requires fresh observations/reseal
and exact fresh approval. No stale approval/window material is accepted.
The UTC execution window is UNBOUND; no approval is requested or fabricated
by this preparation task. Actual browser UAT and Phase 9 acceptance remain
pending. Portable copy2 is unavailable; recovery custody is CurrentUser-only.

NEXT_SAFE_ACTION: OWNER REVIEW + EXPLICIT FRESH EXECUTION APPROVAL.
Stop. Operation execution/claim/stage/deploy NONE; production writes,
Video Factory writes, real provider calls and actual cost all 0. Phase 10,
AH-T01B, AH-R01, AH-03/AH-04 and other workstreams remain closed.
