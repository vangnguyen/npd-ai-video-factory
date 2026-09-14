# AH-P9-RCA-18A6-A3 — Hybrid custody identity source preparation

Source baseline: 86869aefd9fd942d37eda8fd9e116ae43915aaf5. Previous A2 receipt: fab2d19ecfe1ae072a6148b6c9e748d4714e75b0efb8da03eed3207c7e1ebfa5.

This source candidate preserves verified Google issuer/sub/audience and verification provenance in the existing HMAC-signed session. Business subject/email, roles, Analyze capabilities, redirect and cookies remain compatible. Legacy email-only sessions work for business login and cannot request custody. No new custody endpoint is mounted.

The stable principal is `pid:` + SHA256(`npd.agent-hub.custody.origin-principal.v1` + NUL + deterministic strict UTF-8 JSON `{issuer,subject}`). Google issuer aliases are canonicalized only after signature/audience/nonce verification. A separately enrolled exact Google issuer/sub pin AND the current Owner mapping are required. There is no first-login enrollment. Same email/different sub is denied; changed email/same sub requires the current explicitly authorized business mapping. Mapping change during a journal transaction is HOLD, including restart; no prior request becomes authority through email continuity.

## Scoped issuer bootstrap design

Proposed identifier: `urn:npd:agent-hub:custody:phase9`. This is a new, unprovisioned controlled enrollment namespace with separately delegated subject signing credentials. It is not a general Agent Hub identity provider. No process, token minting endpoint or production trust backend is implemented. Public trust/JWKS import is pinned to exact independently supplied manifest bytes and rejects private JWK fields, wrong fingerprints, unknown scope and duplicate keys. No token-supplied JKU/X5U keys are fetched.

Audience `npd-agent-hub-custody-p9`; type `npd-custody-service+jwt`; pinned RS256/RSA>=2048; exact signed issuer/audience/sub/iat/nbf/exp/JTI/epoch/capability/action/custody UUID/input/result/previous-receipt fields. Lifetime <=900s. Tokens are action-specific. Verifier is verify-only; custodian is write/commit-only. Google requester never acts as verifier/custodian. Trust admin is not a runtime actor.

Each service has a different subject, kid, SPKI fingerprint and credential controller. Reusing one public/private key behind aliases is rejected, including a service key matching the Owner Google verification key. Private fixture keys exist only in test RAM. Production private keys, tokens, credentials, identities and trust stores do not exist in this task's outputs.

## Rotation, revocation and commit fences

New key enrollment creates a new controlled epoch. New issuance switches to its new current kid. Previous-key verification overlap is explicitly bounded to <=900s with exclusive retirement; a previous kid cannot issue tokens at/after overlap start. Epoch mismatch remains denied even during overlap: overlap does not rescue in-flight old-epoch authority. Receipts pin exact kid/SPKI hash/epoch. Transactions cannot bridge a trust change. The local public store supports monotonic CAS epoch/revocation fixtures; revocation tombstones are never removed by fallback.

Subject, kid or JTI revocation denies new actions. Unavailable/unknown trust, journal corruption, receipt-chain mismatch, token replay, actor collisions or expiry HOLD/DENY. Trust/Owner mapping/expiry are checked again after the journal INSERT and before COMMIT. No automatic retry or in-memory fallback. Multi-host production trust/revocation fencing must be accepted with PostgreSQL; the local RLock and SQLite tests are not production acceptance.

## Journal compatibility and retention

The existing v1 authority engine is unchanged. The SQL journal's default v1 schema/domain/snapshot contract remains unchanged. Hybrid authority has a separate v2 schema and receipt/commit domains. It rejects v1 journals and malformed/stale v1 service tokens. There is no historical receipt migration or authority upgrade.

Google Owner request → custodian archive receipt → independent verifier → original custodian commit → durable commit consumption → existing archive/verify/retention CAS guard. The authority proof does not replace durable archive readback or the ledger CAS. Commit is consumed before CAS; a failed ledger CAS cannot rearm it after restart. Protected/unknown remains HOLD and never reaches trim eligibility. Hold release/delete is deferred.

Current source census retains all 50 DB1/Memory functions, 67 call sites and 22 file custody helper dispositions. Four new local control writers are explicitly inventoried in WRITER_SUPPLEMENT.json; inherited SQL controls remain guarded. No retention/backend activation occurs.

## Provisioning remains HOLD

The companion manifest lists 12 public enrollment/configuration/custody actions and four separate private credential actions. Actual Google Owner sub, named authenticated controllers, real key pins and production ownership/storage bindings are unbound. These proposals are not exact executable authorization. Gate A is HOLD_NOT_PREPARED, NOT_GRANTED and NOT_EXECUTED. Resolve those bindings through a separate reviewed enrollment/preparation step before issuing an exact provisioning approval. PostgreSQL/S3 provisioning, real-backend acceptance and runtime activation remain separate gates.

## Evidence and limits

Actual ephemeral RS256 fixtures exercise callback/session, actor/key independence, expiry/revocation/epoch/replay, restart, multiprocess races, tamper and retention CAS. Production evidence from A2 is retained as timestamped immutable provenance and is not a new observation. No production HTTP, Redis, CRM/Sales/VF, Google token exchange, PG/S3/KMS or provider call is made by this task.

Primary contract references: [Google OIDC](https://developers.google.com/identity/openid-connect/openid-connect), [JWT security requirements](https://datatracker.ietf.org/doc/html/rfc8725).
