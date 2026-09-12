# AH-P9-RCA-02: remote preflight RCA and source capture candidate

Verdict: `REVIEW_REQUIRED`. The capture candidate passed local regression tests
and an independent remote sentinel. The historical capture gap remains, and
the aborted operation is immutable. Fresh pilot gate preparation is `HOLD`.

## Verified baseline and root cause

The supplied handoff commit `656e6f9ccf45e1741f03552a22e1df9ac3071250` is an
ancestor of the current handoff commit
`00521f72b40cf1ddec6901c2415ef01a0de7844a`. The Agent Hub application tree is
identical at that handoff and source exact-main
`43a1cca354d12893ee33b6e43cd9117794f78e04`. Remote main still equals that
source SHA, and its seven CI checks are successful. Those checks do not attest
to this new source capture candidate.

Two failures explain the terminal error:

1. The sealed remote verifier correctly rejected `PROTECTED_SERVICE_DRIFT`.
   Exactly one protected service, `n8n-marketing-pricing-policy-sync-1`, changed
   its container ID and image ID. Its creation time is
   `2026-09-11T04:45:44.539639862Z`, before dispatch at
   `2026-09-11T13:00:19.4406767Z`. The sealed protected digest is
   `dafe99c16a9f3059cb20d5d5e746c35ae5438668fe8155d5df034a87b02d9302`;
   the independently revalidated current digest is
   `6e0167343174e4cb719b3799015dc5d438b8cdcc545774dc72d53f61cf2c648e`.
2. The local launcher checked nonzero return code before parsing stdout and
   derived its reason solely from `sha256(stderr)[:16]`. The remote exception
   handler writes a sanitized failure JSON to stdout and exits `2`.
   Consequently, empty stderr yielded `e3b0c44298fc1c14` and the launcher
   discarded the useful stdout, child return code and generated invocation UUID.

The original SSH-child stdout, return code and UUID are not recovered. The
historical remote reason is strongly supported by source, pre-window creation
time, the prior RCA and independent reproductions; it is not a newly recovered
primary historical child receipt.

## Layer checks and reproductions

| Layer | Evidence and result |
| --- | --- |
| SSH/auth/host key | Existing dedicated known-hosts file, source/client hashes and exact host fingerprint matched. Strict checking, batch mode and identities-only remained enabled. A real SSH handshake passed. Historical SSH journal has one accepted key, zero failed keys and zero timeouts. |
| Shell/path/runtime | Fresh program streamed to `python3 -B -`; no envelope, upload or remote temporary file. Remote cwd `/root`, uid `0`, Python `3.12.3`; Compose `2.35.1`. |
| Quoting/pipes/redirection | Local argv with `shell=False`; only fixed remote command words. Program supplied on stdin, stdout/stderr captured separately. No remote pipeline or redirection. |
| Config/target | Agent Hub env, Caddy and base Compose hashes match the sealed values. Target signature remains `10231d87a7d1a7a50b4b8826e9fc542013ae3a5dc629538f0e684371244c9d2c`; health/readiness HTTP checks returned 200. |
| Protected verifier | Recomputed all 18 protected signatures with the sealed pure signature functions. Exactly one changed service. The exact extracted sealed verifier rejects those signatures before safety/routes/Compose rendering. |
| Output capture | Independent remote sentinel produces sanitized failure JSON on stdout, empty stderr, and child exit `2`. New capture candidate retains its receipt before raising the reason. |
| Exit code | Independent local native fixture exits `2`; the recorded outer PowerShell wrapper reproduces exit `1`. |
| Old launcher | Exact extracted `invoke_remote` with a local fixture reproduces `REMOTE_PREFLIGHT_FAILED_e3b0c44298fc1c14`. Neither old main nor old dispatcher runs. |
| Artifacts | Historical manifest 14/14 and sealed source/snapshot hashes 4/4 match. Old claim/attempt/state/stage paths remain absent. Observation is `NOT_STARTED`. |

Two initial independent metadata probes failed because their Docker template
assumed every container had a health field. The collector was corrected to
handle an absent field. Their transport receipts and the sanitized template
failure are retained; they are separate from the 11 September pilot failure.

Passive protected-container metadata was used only to evaluate the Agent Hub
binding. No container environment values, application logs, customer records,
CRM/Sales Hub APIs, Redis data or Video Factory application endpoints were queried.
The Agent Hub env file was hashed without parsing or emitting credential values.

## Minimal source candidate

`scripts/ops/agent_hub_phase9/remote_preflight_capture.py` is a library with no
dispatcher, approval, claim or deployment entrypoint. It accepts a caller's
validated strict-SSH invoker. It atomically publishes an exclusive, fsynced
receipt containing invocation UUID, binding, child return code, timestamps,
stdin hash/length and separate stdout/stderr hashes/lengths before returning
success or raising a bounded failure reason.

A narrowly allowlisted, same-binding, non-sensitive failure JSON is also
retained verbatim as base64, preserving whitespace and line endings. Opaque
output remains redacted with exact byte lengths/hashes; authorization argv and
stdin contents are never persisted. Nonzero exit never becomes success. Timeout
and launch failures, including the existing SSH contract's wrapped exceptions,
produce receipts and abort. Missing capture evidence also aborts. Success
requires matching operation/mode and explicit read-only safety flags.

For a future freshly sealed launcher, after its existing authority/transport
validation, replace only its preflight invocation-result handling with:

```python
try:
    result, receipt = invoke_preflight(
        invoke_argv, argv,
        input_bytes=REMOTE_RUNTIME.read_bytes(), timeout=timeout,
        evidence_directory=NEW_AUTHORITY / "remote-captures",
        binding_id=envelope["operation_id"],
        invocation_id=envelope["invocation_id"],
        success_verifier=verify_fresh_preflight_bindings,
    )
except CaptureStop as error:
    raise Stop(error.reason) from None
```

RCA-03 hardening makes `verify_fresh_preflight_bindings` mandatory for success:
the future dispatcher must define it to validate all fresh response bindings and
return exactly `True`. A missing/failed verifier, unsafe sanitization flag or
nonempty success stderr aborts after capture. This sketch is preparation guidance,
not an adopted dispatcher. See `AH_P9_CANDIDATE_REVIEW_RESEAL_20260912.md`.

This candidate is exercised by the independent diagnostic sentinel, but is not
adopted into an executable pilot dispatcher. The old sealed package, operation,
approval, window, guard, dispatcher and remote runtime are unchanged. Adoption
requires a new dispatcher/payload, new hashes and a new gate; the old package
must never be edited or invoked to try this change.

## Validation and remaining gates

- New source regression tests: `19/19 PASS` on Windows/Python 3.13.
- Historical RCA tests: `12/12 PASS`.
- Exact old launcher/verifier local behavior reproductions: `2/2 PASS`.
- Independent remote failure sentinel and local wrapper chain: `PASS`.
- Candidate branch CI: `NOT_RUN`; no push, PR, merge or production deployment.
- Production writes `0`; real provider calls `0`; actual cost `0`.

`FRESH_GATE_READINESS.json` records `HOLD_EVIDENCE_INSUFFICIENT`. No replacement
operation, approval, claim, token, window, staging or executable gate was created.
The owner must review the immutable capture gap and candidate, then request
adoption/resealing and a new protected-set snapshot with an invalidating-change
or freeze coordination record before fresh gate preparation.

Phase 9 UAT/business acceptance remains incomplete. The order remains
`Phase 9 UAT/business acceptance -> Sales SLA + Backup Copy 2 -> AH-T01B -> AH-R01 -> AH-03`.
Phase 10 stays `NO-GO`.

Evidence bundle:
`C:/Users/VANG NGUYEN/Documents/Codex/2026-09-12/referenced-chatgpt-conversation-this-is-an/outputs/ah-p9-rca-20260912`.

`NEXT_SAFE_ACTION`: owner reviews this RCA and source capture candidate; a
subsequent source-only task may adopt/reseal a fresh dispatcher and prepare a
new gate after fresh protected-set evidence and bindings are sufficient.
No pilot execution follows automatically.
