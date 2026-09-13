# Agent Hub AH-P9-RCA-11: preflight child exit 2

The failed operation `PHASE9-LIMITED-PILOT-RCA06-0936a195-e70a-4189-9434-2a1def050d0a`
is `ABORTED_BEFORE_CLAIM_NOT_REUSABLE`. Its exact Owner grant was consumed.
This RCA changes local source and static preparation only. It grants no pilot,
claim, staging, deploy, UAT, recovery, TTL observation or execution approval.

## Exact child and evidence

`pilot_runner.observe` calls `pilot_dispatcher.dispatch_preflight`, then
`remote_preflight_capture.invoke_preflight` and the pinned `pilot_transport.invoke`.
The local SSH subprocess uses argv and `shell=False`; SSH's remote command is
`shlex.join(['python3', '-B', '-', 'preflight', encoded_envelope])`. The remote
Python program arrives as binary stdin, not as a file or PowerShell pipeline.

The original capture UUID is `293808de-f60d-4896-927d-3ea510f2c818`.
It started at `2026-09-13T11:48:42.267449+00:00` and completed at
`2026-09-13T11:48:44.302709+00:00`. The child returned 2, without timeout or
launch error. The 60,484 stdin bytes have SHA-256
`020d388f479455477d78f22f140fc69a017501b738f986e2235aeefd5e8fcfb5`.
Stderr is exactly empty, SHA-256
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.
Failure stdout has 186 bytes, SHA-256
`19760b785add72c0922795952586dcb4198ccfabf7535362046a582f3b6b0ded`.

The raw failure stdout sidecar and original encoded envelope/runner correlation
were not retained. They cannot be reconstructed as original primary evidence.
The source emits each bounded runtime failure with sorted JSON plus LF. Among
these documents, only `COMPOSE_FILE_LABEL_DRIFT` matches both the captured length
and digest. Saved inspect evidence independently confirms the rejected labels.
An unchanged sealed-program local replay reproduces that exact failure digest
and exit 2, with earlier I/O mocked and reconstructed binding constants plus a
synthetic correlation. Linux UTF-8/LF stdout is modeled explicitly on Windows.
This replay is a reproduction, never a replacement primary capture.

Fresh inspect-only diagnostic resolves Python to `/usr/bin/python3` (3.12.3),
cwd `/root`, and env keys PATH, HOME, USER, LOGNAME, LANG. These are current
observations, not proof of the historical PID/environment/encoded argv.
Original local entry cwd was the task workspace and the parent was the sealed
Owner entry Python process. Its dynamic child argv/PID were not persisted.

## Root cause

After bounded recovery, the current rollback container retains the compose
config label `[base_compose, attempts/ae039afa.../rollback-override.json]`.
The next operation's runtime previously accepted `[base_compose]` or
`[base_compose, attempts/0936a195.../rollback-override.json]`.
`verify_baseline` reaches `compose_context` after the protected, safety and route
checks; its exact path allowlist raises `GateStop('COMPOSE_FILE_LABEL_DRIFT')`.
The remote `main` catches this guard, writes its bounded failure to stdout and
exits 2. It is not an argparse, quoting, missing-file or corrupted-package
diagnosis inferred from the numeric exit code. No claim is reached.

The capture allowlist omitted this bounded reason. It therefore classified the
stdout as opaque/UNCLASSIFIED and raised before retaining the raw sidecar. The
stderr was captured correctly; its absence was intentional runtime behavior.

## Minimal responsible contract

`baseline_compose_context.py` defines one explicit recovered-compose provenance
contract. It binds the exact recovered operation and attempt, current container
and signature, rollback image, two exact config paths, three raw custody hashes,
recovery receipt and read-only observation digest. Runtime acceptance requires
the exact private root-owned nonsymlink files, byte hashes, terminal
`ROLLED_BACK_VERIFIED` state, original claim ownership, no retry and an image-only
rollback override. Unknown paths, another image/container, active/staged/deployed
state, changed bytes or unsafe ownership remain failures.

The renderer inlines this same module, binds its context and baseline identity,
and the gate verifies the evidence/profile/standalone-runtime constants together.
The existing current-operation candidate/rollback paths and all topology checks
remain strict. Future JIT must copy `evidence/BASELINE_COMPOSE_BINDING.json`,
`evidence/COMPLETED_RECOVERY_RECEIPT.json` and
`evidence/RECOVERED_COMPOSE_READONLY.json` into its manifest/dependency closure,
and place the exact context in `RUNTIME_PROFILE.baseline_compose_binding`.
Static packaging performs none of that future execution work.

Custody parsing cannot authorize the recovered operation. Canonical fresh-ID
validation now also permanently retires 0936a195 alongside the two prior terminal
operations. Old HEAD/package/window/capture authority is not migrated or reused.

The producer archives only approved non-sensitive failure documents before
abort, records component/exit/classification and sanitized stderr, and preserves
the caller correlation and safe invocation shape. Opaque streams stay redacted;
their lengths and exact byte hashes remain available. Nonzero child exit never
calls the success verifier or becomes PASS. The raw stdout and domain-separated
canonical payload digests retain their existing distinct contracts.

## Preparation boundary

Regression includes the production-shaped compose-label fixture, actual local
CLI rejection, standalone rendering, gate/runtime context binding, exact custody
tamper/state/owner/path rejection, safe failure capture and existing approval,
TTL, canonical digest, staging, terminalization, recovery and replay suites.
Changed source requires new exact candidate CI. Only a static review package is
prepared; Owner static adoption is required before any subsequent manual JIT.
All production/Video Factory writes, provider calls and actual cost in RCA-11
are zero. Existing recovery writes are historical provenance, not this task.
