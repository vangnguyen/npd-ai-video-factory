# AH-P9-RCA-10: owned stdout custody

The approved pilot's saved preflight stdout was 1,953 bytes. Its SHA-256 was
`0140bfe2364271a69b96df1e225044e115b47ac795217a35c79daeb0bf60f000`,
matching the original transport capture receipt. The remote process emitted
`json.dumps(result, indent=2, sort_keys=True)` plus LF. The sealed followup
instead used `json.dumps(preflight, sort_keys=True)` plus LF: 1,805 bytes and
SHA-256 `bdb66e060d704d885f8277198a2a52e26879fc3ba8d90ac757eb854a50098fb2`.
Removing pretty-print whitespace accounted for exactly 148 bytes. This fixture
contains no CRLF, BOM, Unicode, or null bytes. Integrity verification correctly
failed, but it compared semantic serialization against a raw transport digest.

## Explicit v2 capture contract

`capture_hash_contract.py` is the common producer/consumer implementation.

- `raw_stdout_sha256` is SHA-256 of immutable binary stdout without decoding,
  newline normalization, trimming, sanitization, or reserialization.
- `canonical_payload_sha256` is SHA-256 of the domain prefix
  `npd.agent-hub.phase9.canonical-payload.v1\0` followed by strict UTF-8 JSON
  with sorted keys, compact separators, `ensure_ascii=False`, and no final LF.
  Unicode code points are retained without normalization. Duplicate keys,
  nonfinite numbers, BOM, malformed UTF-8, and unpaired surrogates are rejected.
- `raw_stderr_sha256` describes the separate binary stderr stream. Successful
  preflight still requires empty stderr; a digest never grants permission.
- Legacy `stdout.sha256` and `stdout.length_bytes` continue to describe raw
  transport bytes. The raw and canonical digest domains are never substituted.

The producer publishes its fsynced receipt before reporting errors. Owned
preflight additionally retains an exclusive, UUID-bound `.stdout.bin` sidecar
only after read-only flags and the caller's package/binding verifier pass.
Opaque, failed, or unverified output is not archived verbatim. Text-mode
transport output cannot provide raw custody. The owned runner binds both
explicit digests and the contract identifier before any claim. Followup checks
the raw sidecar, its strict semantic payload, and all existing ownership,
approval, package, operation, snapshot, dependency, and initial timing proofs.

## Historical custody and static adoption

The exact production raw bytes, the parsed semantic object, the 1,805-byte
legacy representation, and provenance-only metadata are separate fixtures.
They authorize no operation. The unmodified historical package still reproduces
`OWNED_CAPTURE_INVALID`. V1 receipts are rejected by the v2 consumer even if
their outer receipt hash is updated. The new module is a required transitive
pilot dependency. The recovered `ae039afa` identity and aborted `2da31c5f`
identity cannot be used for fresh execution. Historical records remain intact.

Future static adoption must copy and bind the new common hash module, producer,
dispatcher, runner, verifier, and canonical operation identity module from one
exact candidate HEAD. Runtime/image application content is unchanged by this
host-side fix. This RCA prepares static review evidence only; it creates no
execution operation, window, counter TTL receipt, confirmation, or approval.
JIT preparation and pilot execution require subsequent separate authorization.
