# AH-P9-RCA-18A4: authenticated custody source contract

Review only. Production identities, backend provisioning, connection, archive,
activation, campaign/lead creation and pilot execution remain unauthorized.

The accepted source baseline is 469b8a732074c65d476e3355a3eecf961c314b06.
RCA18A3 receipt is
7861be734a8d353ffa6d95de1b70488006f91412215086563e23bccc65e3186a.

## Current auth inventory

`auth.py` compares three distinct static bearer values and returns subjects
`owner`, `operator`, `viewer`. These identify a role credential, not a named
person. Development auth returns `auth-disabled`. Neither is custody authority.
The existing Google OIDC flow validates login and issues an HMAC session with
subject email, role, issue/expiry; session authentication rechecks the current
allowlist. It provides a named authenticated subject, with Origin checking for
writes, but no custody transaction scopes or independent service capabilities.
The session subject is a normalized allowlisted email, not an immutable Google
issuer/sub pair retained end-to-end. A bridge must bind a stable issuer/sub
before service acceptance; this change does not manufacture that bridge.

Owner/Operator/Viewer ordering governs business endpoints. The capability
framework currently projects `agent_tasks.analyze`; bootstrap/whoami includes
authenticated role/subject and capability expiry. API audit actors use
`principal.subject`. The existing signed service-request implementation in the
disabled Video Factory integration shows that authenticated service identity is
a realistic extension, but it is neither imported nor changed by this work.

One Owner bearer can submit arbitrary labels to a local policy constructor;
that constructor checks shape only. There was no custody API through which
this became production authority. RCA18A3 correctly stopped the adapter.
No existing bearer/session or client bootstrap flag gains custody capabilities
with the new source module.

## Two-party versus three-party

Two-party: authenticated Owner requests; one distinct service archives,
verifies and commits. This prevents Owner self-verification but makes the
archive writer its own verifier. It can be acceptable only if Owner deliberately
accepts that reduced independence with external readback assurance.

Recommendation: retain the already accepted three-party direction for the
initial source contract. Requester is an authenticated named human Owner;
custodian is a scoped archive writer/commit service; verifier is a different
read-only custody service. Verification therefore remains independent of both
requester and archive writer. This adds one service binding to preserve an
existing security objective, without adding a release/delete endpoint.

This recommendation needs Owner review. It is not production adoption or an
identity provisioning decision. Two-party is not silently activated by a flag.

## Credentials and capabilities

`ScopedCustodyAuthenticator` verifies separately issued signed scoped bearers
using fixed RS256, pinned public keys, exact issuer/audience and explicit JWT
type `npd-custody+jwt`. PyJWT and cryptography are already repository
dependencies. No key generation, issuer, token creation, credential lookup,
JWKS/network fetch, OAuth exchange or runtime environment config is added.
Test keys and signed fixtures are synthetic and live only in the test process.

Trusted configuration maps `(issuer, stable subject)` to principal kind,
optional business role and an explicit maximum capability set. A token must
carry an allowed capability and exact action/transaction/input/result/previous
receipt scope. Role claims, unexpected identity claims, unknown subjects,
wrong key/type/algorithm/audience, expired tokens and role aliases are denied.
Lifetime is capped at 900 seconds for this source contract, with no leeway or
refresh/retry endpoint. Actual issuer/key IDs/stable human/service subjects and
credential independence are UNBOUND; no production credentials are issued.

Canonical capabilities follow the existing dotted naming convention:

| Action | Capability | Required actor |
|---|---|---|
| HOLD_REQUEST | custody.hold.request | Named authenticated human Owner |
| ARCHIVE_WRITE | custody.archive.write | Separate custodian service |
| CUSTODY_VERIFY | custody.archive.verify | Service distinct from requester and writer |
| CUSTODY_COMMIT | custody.commit | Original custodian, distinct from requester/verifier |

`HOLD_REQUEST` records a bound classification/archive request; it does not
remove a hold, make protected evidence evictable, or approve business writes.
Custody authorization composes with business RBAC rather than replacing it.
Caller-supplied principal, role and capability fields are forbidden by the
action request schema; every action authenticates the bearer again.

## Receipts, replay and retention composition

Each receipt records authenticated actor issuer/subject, effective capability,
custody UUID, action, UTC, input/result digest, previous receipt digest and
ALLOW/DENY decision. Unauthenticated denial has null actor; supplied subjects
are never promoted into audit actor identity. Receipt hashes use a separate
domain. Successful action order is request → archive → independent verification
→ commit. Input, archive result and previous receipt are immutable bindings.
Every authenticated token submission and transaction action is single-use.

The local journal serializes submissions with a lock. The commit hook binds
exact current policy, raw record and linked digests plus archive receipt bytes.
It consumes a verified commit before the existing writer CAS. A CAS conflict
leaves that authorization consumed; no automatic retry. Archive/checksum,
protected-category, shared-reference and generation checks execute first.
Replacing the configured hook during a batch fails the configuration pin.

The optional hook is exposed only in the existing explicit local coordinator
model. Existing synthetic fixtures may omit it. The persistent factory remains
inactive; real Redis is rejected even by an enabled local model. This is not a
production adapter or proof of deployed all-writer authority enforcement.
The original 50 writer/67 call boundaries and 22 file dispositions remain
inventoried and tested. Three additional local authority control-memory writer
methods (`perform`, private `_receipt`, `consume_commit`) have explicit auth,
lock/call-site/one-use boundaries, with a separate static coverage test. They
are not new DB1 or production file writers. File helpers remain separately
scoped/default HOLD.

## Hold release and remaining acceptance gates

DEFER_HOLD_RELEASE. Protected/unknown/terminal Phase 9 custody stays indefinite
HOLD. `HOLD_RELEASE` is recognized solely to deny. No release, delete or general
hold removal interface is implemented. Period expiry is not deletion authority.
Existing stricter 365-day source defaults and Owner-bound 90/180/365 mapping
remain unchanged; classification cannot silently shorten historical custody.

Future separately authorized acceptance must establish: exact named requester,
trusted scoped issuer/public keys and distinct service subjects; independent
credential ownership and least-privilege backend read/write permissions;
durable append-only signed/attested receipt and replay storage tied to the
writer transaction across restart/multiple processes; independently verified
S3 Object Lock version/raw/linked/retention readback; live all-writer/reference
census; outage/concurrency/migration/rollback evidence. The local journal does
not prove these production properties. Missing trust/backend/journal remains
HOLD. No activation gate is prepared here.

JWT verification follows fixed-algorithm/type separation described by
[PyJWT API](https://pyjwt.readthedocs.io/en/stable/api.html) and
[RFC 8725](https://www.rfc-editor.org/rfc/rfc8725.html). Public documentation
verification involved no production connection or backend provisioning.
