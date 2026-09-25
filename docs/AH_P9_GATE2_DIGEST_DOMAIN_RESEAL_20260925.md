# AH-P9 Gate 2 digest-domain remediation and fresh reseal

## Disposition

The 25 September Gate-2 retry stopped before claim, stage, image load,
deployment or business POST. The operation is terminal and non-reusable.
Agent Hub remained on the healthy `phase9_creation` rollback image; no DB1,
provider, customer or Video Factory action occurred.

Root cause is `DIGEST_DOMAIN_REPRESENTATION_MISMATCH`:

- Gate C bound SHA-256 of the exact authenticated HTTP response bytes:
  `60cb41b0da6384ee8677fff7d7cc5b89d6a759e0355ac6b0c56d8e7ae4c50cd8`.
- Gate 2 recomputed `content_sha256(Campaign)`, the semantic Pydantic-model
  digest:
  `8c06ad499c8bffc40ff26fe2361e0ae7a4226ff4d5d738ecd41f73bc938614ec`.
- The campaign had not changed. The verifier compared values from different
  digest domains under one ambiguous name.

## Source remediation

`scripts/ops/agent_hub_phase9/gate2_digest_contract.py` defines a strict
evidence object with independently named `raw_transport_sha256` and
`semantic_model_sha256` fields. It rejects missing/extra fields, swapped or
substituted domains, wrong types/status/campaign, empty responses, and any
claim that raw body or secrets were exported.

The sanitized production-shaped fixture records only response length and the
two hashes. It contains no response body, bearer token, cookie, authorization
header or raw PII.

## Fresh package policy

The previous Gate-2 operation, approval, window, transport receipt and package
remain immutable terminal evidence. The fresh package uses a new operation and
proposed window. It reuses the previously verified application image because
the application source/image did not change; only external runner, verifier,
evidence contract and package code changed.

Before a new Owner gate is presented, the immutable package must pass:

1. full offline/tamper/failure-matrix tests;
2. repository regression, evaluator and exact-head CI;
3. strict-host-key transport rehearsal;
4. the exact sealed JIT collector in read-only rehearsal mode.

The read-only rehearsal and future claim mode call the same collector. The
rehearsal cannot create directories or claims, invoke SCP, load/tag images,
run Compose or issue the delivery POST. A future owner consent must bind the
package manifest and both rehearsal receipt hashes.

## Irreducible live condition

Offline tests cannot guarantee that mutable production state will remain
unchanged until a future window. The same checks therefore run again before
the atomic one-shot claim. Any later drift aborts before stage or mutation; it
is never auto-rebaselined.

Production writes: `0`. Real provider calls: `0`. Actual cost: `0`.
