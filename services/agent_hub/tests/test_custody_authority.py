"""Synthetic, process-local keys/principals only. No real identity/token issuance."""
from concurrent.futures import ThreadPoolExecutor
import ast
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
import time
from uuid import uuid4
from types import SimpleNamespace
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
import jwt
import fakeredis
import pytest

from npd_agent_hub.auth import Principal, Role, principal_capabilities
from npd_agent_hub.custody_authority import (
    ACTION_CAPABILITY, TOKEN_TYPE, AuthenticatedCommitHook, CustodyAction as A,
    CustodyActionRequest, CustodyCapability as C, LocalCustodyAuthority,
    PrincipalBinding, ScopedCustodyAuthenticator, custody_archive_digest,
    custody_input_digest, sha,
)
from npd_agent_hub.retention_custody import CustodyBlocked, RawRecord, GuardedRedis
from local_custody_fixture import fixture_retention as coordinator

ISSUER = "https://synthetic-custody-issuer.invalid"
OWNER = "synthetic-human-subject-01"
VERIFIER = "synthetic-verifier-subject-02"
CUSTODIAN = "synthetic-custodian-subject-03"
INPUT = sha(b"synthetic exact raw/linked/policy input")
ARCHIVE = sha(b"synthetic archive version proof")


@pytest.fixture(scope="module")
def key():
    # Never written/exported to a file or printed. Test process lifetime only.
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def setup(key):
    pub = key.public_key().public_bytes(serialization.Encoding.PEM,
                                       serialization.PublicFormat.SubjectPublicKeyInfo)
    bindings = (
        PrincipalBinding(OWNER, "human", frozenset(C), Role.OWNER),
        PrincipalBinding(VERIFIER, "service", frozenset({C.ARCHIVE_VERIFY, C.COMMIT})),
        PrincipalBinding(CUSTODIAN, "service", frozenset({C.ARCHIVE_WRITE, C.ARCHIVE_VERIFY, C.COMMIT})),
        PrincipalBinding("synthetic-viewer", "human", frozenset(C), Role.VIEWER),
        PrincipalBinding("synthetic-operator", "human", frozenset(), Role.OPERATOR),
    )
    auth = ScopedCustodyAuthenticator(issuer=ISSUER, audience="synthetic-custody",
        public_keys={"synthetic-key-01": pub}, principals=bindings)
    return LocalCustodyAuthority(auth), key


def request(action=A.HOLD_REQUEST, *, custody_id=None, input_sha256=INPUT,
            result_sha256=None, previous=None):
    return CustodyActionRequest(custody_id=custody_id or str(uuid4()), action=action,
        input_sha256=input_sha256, result_sha256=result_sha256 or input_sha256,
        previous_receipt_sha256=previous)


def credential(key, req, *, subject=OWNER, caps=None, update=None, header=None):
    now = int(time.time())
    payload = {"iss": ISSUER, "aud": "synthetic-custody", "sub": subject,
        "iat": now, "nbf": now, "exp": now + 600, "jti": str(uuid4()),
        "capabilities": caps if caps is not None else [ACTION_CAPABILITY[req.action].value],
        "custody_id": req.custody_id, "action": req.action.value,
        "input_sha256": req.input_sha256, "result_sha256": req.result_sha256,
        "previous_receipt_sha256": req.previous_receipt_sha256}
    payload.update(update or {})
    return "Bearer " + jwt.encode(payload, key, algorithm="RS256",
        headers={"kid": "synthetic-key-01", "typ": TOKEN_TYPE, **(header or {})})


def start(setup, *, input_sha256=INPUT):
    authority, key = setup
    req = request(input_sha256=input_sha256)
    receipt = authority.perform(credential(key, req), req)
    return req.custody_id, receipt


def archived(setup, *, input_sha256=INPUT, archive_sha256=ARCHIVE):
    authority, key = setup
    custody_id, prior = start(setup, input_sha256=input_sha256)
    req = request(A.ARCHIVE_WRITE, custody_id=custody_id, input_sha256=input_sha256,
                  result_sha256=archive_sha256, previous=prior.sha256)
    return custody_id, authority.perform(credential(key, req, subject=CUSTODIAN), req)


def committed(setup, *, input_sha256=INPUT, archive_sha256=ARCHIVE):
    authority, key = setup
    custody_id, prior = archived(setup, input_sha256=input_sha256, archive_sha256=archive_sha256)
    verify = request(A.CUSTODY_VERIFY, custody_id=custody_id, input_sha256=input_sha256,
        result_sha256=archive_sha256, previous=prior.sha256)
    receipt = authority.perform(credential(key, verify, subject=VERIFIER), verify)
    commit = request(A.CUSTODY_COMMIT, custody_id=custody_id, input_sha256=input_sha256,
        result_sha256=archive_sha256, previous=receipt.sha256)
    return custody_id, authority.perform(credential(key, commit, subject=CUSTODIAN), commit)


def test_three_authenticated_parties_chain_and_consume_once(setup):
    authority, _ = setup
    custody_id, receipt = committed(setup)
    rows = authority.receipts
    assert [r.actor_subject for r in rows] == [OWNER, CUSTODIAN, VERIFIER, CUSTODIAN]
    assert [r.effective_capability for r in rows] == [c.value for c in
        (C.HOLD_REQUEST, C.ARCHIVE_WRITE, C.ARCHIVE_VERIFY, C.COMMIT)]
    assert all(r.authorization_decision == "ALLOW" and datetime.fromisoformat(r.observed_utc).tzinfo
               for r in rows)
    assert all(r.custody_id == custody_id and r.input_sha256 == INPUT for r in rows)
    assert rows[0].previous_receipt_sha256 is None
    assert all(b.previous_receipt_sha256 == a.sha256 for a, b in zip(rows, rows[1:]))
    authority.consume_commit(custody_id, INPUT, ARCHIVE, receipt.sha256)
    with pytest.raises(CustodyBlocked, match="CONSUMED"):
        authority.consume_commit(custody_id, INPUT, ARCHIVE, receipt.sha256)


@pytest.mark.parametrize("subject,caps,reason", [
    (OWNER, [], "CAPABILITY_DENIED"),
    ("synthetic-unknown", None, "PRINCIPAL_UNKNOWN"),
    ("Owner", None, "PRINCIPAL_UNKNOWN"),
    ("npd-agent-hub-custody-verifier-p9", None, "PRINCIPAL_UNKNOWN"),
    ("synthetic-viewer", None, "HUMAN_ROLE_DENIED"),
    ("synthetic-operator", [], "CAPABILITY_DENIED"),
])
def test_role_and_name_are_not_authority(setup, subject, caps, reason):
    authority, key = setup
    req = request()
    with pytest.raises(CustodyBlocked, match=reason):
        authority.perform(credential(key, req, subject=subject, caps=caps), req)
    assert authority.receipts[-1].authorization_decision == "DENY"
    assert req.custody_id not in authority._transactions


@pytest.mark.parametrize("update,reason", [
    ({"exp": int(time.time()) - 1}, "INVALID_OR_EXPIRED"),
    ({"nbf": int(time.time()) + 999}, "INVALID_OR_EXPIRED"),
    ({"iss": "https://untrusted.invalid"}, "INVALID_OR_EXPIRED"),
    ({"aud": "browser-session"}, "INVALID_OR_EXPIRED"),
    ({"exp": int(time.time()) + 1000}, "LIFETIME_INVALID"),
    ({"custody_id": str(uuid4())}, "TRANSACTION_MISMATCH"),
    ({"input_sha256": "0" * 64}, "TRANSACTION_MISMATCH"),
    ({"result_sha256": "0" * 64}, "TRANSACTION_MISMATCH"),
    ({"action": "CUSTODY_VERIFY"}, "TRANSACTION_MISMATCH"),
    ({"role": "owner"}, "UNEXPECTED_TOKEN_CLAIM"),
    ({"principal": OWNER}, "UNEXPECTED_TOKEN_CLAIM"),
    ({"capabilities": ["custody.hold.release"]}, "CAPABILITY_DENIED"),
    ({"capabilities": [C.HOLD_REQUEST.value] * 2}, "CAPABILITY_DENIED"),
])
def test_signed_token_must_have_exact_scope_and_no_identity_alias_claim(setup, update, reason):
    authority, key = setup
    req = request()
    with pytest.raises(CustodyBlocked, match=reason):
        authority.perform(credential(key, req, update=update), req)


@pytest.mark.parametrize("authorization", [None, "Owner", "Bearer synthetic-static-owner-token",
    "Bearer npd-agent-hub-custody-verifier-p9", "Bearer ", "Bearer not.a.signature"])
def test_legacy_or_invalid_credentials_are_not_custody_credentials(setup, authorization):
    authority, _ = setup
    with pytest.raises(CustodyBlocked):
        authority.perform(authorization, request())
    assert authority.receipts[-1].actor_subject is None


@pytest.mark.parametrize("header", [{"typ": "JWT"}, {"kid": "untrusted-key"},
    {"jku": "https://untrusted.invalid/key"}])
def test_fixed_key_type_and_header_contract(setup, header):
    authority, key = setup
    req = request()
    with pytest.raises(CustodyBlocked, match="INVALID_OR_EXPIRED"):
        authority.perform(credential(key, req, header=header), req)


def test_wrong_signing_key_and_algorithm_denied(setup):
    authority, _ = setup
    req = request()
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(CustodyBlocked, match="INVALID_OR_EXPIRED"):
        authority.perform(credential(other_key, req), req)
    token = jwt.encode({"sub": OWNER}, "synthetic-only-hmac-value-not-a-real-secret", algorithm="HS256",
                       headers={"kid": "synthetic-key-01", "typ": TOKEN_TYPE})
    with pytest.raises(CustodyBlocked, match="INVALID_OR_EXPIRED"):
        authority.perform("Bearer " + token, req)


@pytest.mark.parametrize("subject,reason", [(OWNER, "SELF_VERIFICATION_OR_COMMIT"),
    (CUSTODIAN, "WRITER_SELF_VERIFICATION")])
def test_requester_and_archive_writer_cannot_independently_verify(setup, subject, reason):
    authority, key = setup
    custody_id, prior = archived(setup)
    req = request(A.CUSTODY_VERIFY, custody_id=custody_id, result_sha256=ARCHIVE, previous=prior.sha256)
    with pytest.raises(CustodyBlocked, match=reason):
        authority.perform(credential(key, req, subject=subject), req)
    assert authority._transactions[custody_id].state == A.ARCHIVE_WRITE
    assert authority.receipts[-1].actor_subject == subject


def test_verifier_cannot_commit_as_custodian(setup):
    authority, key = setup
    custody_id, prior = archived(setup)
    req = request(A.CUSTODY_VERIFY, custody_id=custody_id, result_sha256=ARCHIVE, previous=prior.sha256)
    receipt = authority.perform(credential(key, req, subject=VERIFIER), req)
    req = request(A.CUSTODY_COMMIT, custody_id=custody_id, result_sha256=ARCHIVE, previous=receipt.sha256)
    with pytest.raises(CustodyBlocked, match="CUSTODIAN_SEPARATION"):
        authority.perform(credential(key, req, subject=VERIFIER), req)


def test_changed_input_result_and_receipt_chain_rejected(setup):
    authority, key = setup
    custody_id, prior = archived(setup)
    for changes, reason in [({"input_sha256": "0" * 64}, "INPUT_DIGEST_CHANGED"),
        ({"result_sha256": "0" * 64}, "RESULT_DIGEST_CHANGED"),
        ({"previous_receipt_sha256": "0" * 64}, "CHAIN_MISMATCH")]:
        req = request(A.CUSTODY_VERIFY, custody_id=custody_id, result_sha256=ARCHIVE, previous=prior.sha256)
        req = req.model_copy(update=changes)
        with pytest.raises(CustodyBlocked, match=reason):
            authority.perform(credential(key, req, subject=VERIFIER), req)
    assert authority._transactions[custody_id].state == A.ARCHIVE_WRITE


def test_replay_and_concurrent_same_token_single_success(setup):
    authority, key = setup
    req = request()
    token = credential(key, req)
    def submit():
        try:
            authority.perform(token, req)
            return "ALLOW"
        except CustodyBlocked:
            return "DENY"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: submit(), range(2))) == ["ALLOW", "DENY"]
    with pytest.raises(CustodyBlocked, match="REPLAY"):
        authority.perform(credential(key, req), req)
    assert authority.receipts[-1].reason == "CUSTODY_TRANSACTION_REPLAY_DENIED"


def test_approval_expires_before_commit_or_cas(setup, monkeypatch):
    authority, _ = setup
    custody_id, prior = committed(setup)
    monkeypatch.setattr("npd_agent_hub.custody_authority.time.time", lambda: time.time_ns() / 1e9 + 601)
    with pytest.raises(CustodyBlocked, match="EXPIRED"):
        authority.consume_commit(custody_id, INPUT, ARCHIVE, prior.sha256)


def test_hold_release_absent_and_default_trust_hold(setup):
    authority, _ = setup
    assert not hasattr(authority, "release_hold") and not hasattr(authority, "delete_custody")
    with pytest.raises(CustodyBlocked, match="DEFERRED"):
        authority.perform(None, request(A.HOLD_RELEASE))
    with pytest.raises(CustodyBlocked, match="TRUST_UNBOUND"):
        LocalCustodyAuthority().perform(None, request())


def test_local_http_input_cannot_supply_principal_role_or_capability(setup):
    authority, key = setup
    app = FastAPI()
    @app.post("/synthetic-fixture/custody")
    def fixture(req: CustodyActionRequest, authorization: str | None = Header(default=None)):
        try:
            return asdict(authority.perform(authorization, req))
        except CustodyBlocked as error:
            raise HTTPException(403, str(error)) from error
    client = TestClient(app)
    req = request()
    body = req.model_dump(mode="json")
    for field, value in [("subject", OWNER), ("role", "owner"), ("capabilities", [C.HOLD_REQUEST.value])]:
        response = client.post("/synthetic-fixture/custody", json={**body, field: value},
                               headers={"Authorization": credential(key, req)})
        assert response.status_code == 422
    assert len(authority.receipts) == 0
    assert client.post("/synthetic-fixture/custody", json=body).status_code == 403
    allowed = client.post("/synthetic-fixture/custody", json=body,
                         headers={"Authorization": credential(key, req)})
    assert allowed.status_code == 200 and allowed.json()["actor_subject"] == OWNER
    assert allowed.json()["authorization_decision"] == "ALLOW"


def test_existing_analyze_rbac_does_not_grant_custody():
    for role in Role:
        caps = principal_capabilities(Principal(role, role.name.lower()))
        assert not any(c.startswith("custody.") for c in caps)


def test_authenticated_denial_actor_is_preserved_without_supplied_alias(setup):
    authority, key = setup
    req = request()
    with pytest.raises(CustodyBlocked, match="CAPABILITY_DENIED"):
        authority.perform(credential(key, req, caps=[]), req)
    receipt = authority.receipts[-1]
    assert receipt.actor_subject == OWNER and receipt.actor_issuer == ISSUER
    assert receipt.effective_capability is None and receipt.authorization_decision == "DENY"


def test_malformed_caller_identifiers_never_enter_audit_actor_or_digest(setup):
    authority, _ = setup
    req = request().model_copy(update={"custody_id": "synthetic-not-an-identity",
        "input_sha256": "synthetic-caller-value", "result_sha256": "synthetic-caller-value"})
    with pytest.raises(CustodyBlocked, match="ID_INVALID"):
        authority.perform(None, req)
    receipt = authority.receipts[-1]
    assert receipt.custody_id is None and receipt.input_sha256 is None and receipt.result_sha256 is None
    assert receipt.actor_subject is None


def test_private_key_and_role_alias_trust_configuration_denied(key):
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
    with pytest.raises(CustodyBlocked, match="PUBLIC_KEY_REQUIRED"):
        ScopedCustodyAuthenticator(issuer=ISSUER, audience="fixture", public_keys={"fixture": private},
            principals=(PrincipalBinding(OWNER, "human", frozenset({C.HOLD_REQUEST}), Role.OWNER),))
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    with pytest.raises(CustodyBlocked, match="PRINCIPAL_BINDING_INVALID"):
        ScopedCustodyAuthenticator(issuer=ISSUER, audience="fixture", public_keys={"fixture": public},
            principals=(PrincipalBinding("Owner", "human", frozenset({C.HOLD_REQUEST}), Role.OWNER),))


class FakeSession:
    """Deterministic fixture for the real coordinator.finalize commit hook."""
    def __init__(self, coord, row):
        self.coordinator = coord
        self.row = row
        self.configuration = (coord.policy, coord.archive, coord.classify, coord.resolve_links, coord.authority_gate)
        self.committed = False
        self.fail_cas = False
    def victims(self):
        return (self.row,)
    def commit(self):
        if self.fail_cas:
            raise CustodyBlocked("SYNTHETIC_LEDGER_CAS_CONFLICT_NO_RETRY")
        self.committed = True


def prepared_writer(setup):
    coord = coordinator()
    row = RawRecord("synthetic-fixture", "synthetic-record", b"exact raw bytes\r\n")
    session = FakeSession(coord, row)
    bound = replace(row, links=coord.resolve_links(row, session))
    receipts = coord.preserve((bound,))
    custody_id, grant = committed(setup, input_sha256=custody_input_digest(coord.policy, (bound,)),
                                 archive_sha256=custody_archive_digest(receipts))
    coord.authority_gate = AuthenticatedCommitHook(setup[0], custody_id, grant.sha256)
    session.configuration = (coord.policy, coord.archive, coord.classify, coord.resolve_links, coord.authority_gate)
    return coord, session


def test_archive_independent_verify_authenticated_hook_before_atomic_commit(setup):
    coord, session = prepared_writer(setup)
    coord.finalize(session, coord.generation)
    assert session.committed and len(coord.receipts) == 1
    with pytest.raises(CustodyBlocked, match="CONSUMED"):
        coord.finalize(FakeSession(coord, session.row), coord.generation)


@pytest.mark.parametrize("tamper,reason", [
    ("raw", "COMMIT_BINDING_MISMATCH"), ("linked", "ARCHIVE_OVERWRITE_FORBIDDEN"),
    ("policy", "COMMIT_BINDING_MISMATCH"), ("gate", "POLICY_OR_BACKEND_CHANGED"),
    ("missing_grant", "COMMIT_MISSING"), ("archive", "ARCHIVE_UNAVAILABLE"),
])
def test_writer_hook_fails_closed_without_any_commit(setup, tamper, reason):
    coord, session = prepared_writer(setup)
    if tamper == "raw":
        session.row = replace(session.row, raw=b"modified raw bytes")
    elif tamper == "linked":
        coord.resolve_links = lambda row, current: (("synthetic-link", b"modified linked raw"),)
        session.configuration = (coord.policy, coord.archive, coord.classify, coord.resolve_links, coord.authority_gate)
    elif tamper == "policy":
        coord.policy = replace(coord.policy, policy_id="changed-policy")
        coord.archive.receipts.clear()
        session.configuration = (coord.policy, coord.archive, coord.classify, coord.resolve_links, coord.authority_gate)
    elif tamper == "gate":
        coord.authority_gate = None
    elif tamper == "missing_grant":
        coord.authority_gate = replace(coord.authority_gate, custody_id=str(uuid4()))
        session.configuration = (coord.policy, coord.archive, coord.classify, coord.resolve_links, coord.authority_gate)
    elif tamper == "archive":
        coord.archive.fail = True
    with pytest.raises(CustodyBlocked, match=reason):
        coord.finalize(session, coord.generation)
    assert not session.committed


def test_failed_ledger_cas_consumes_authority_without_retry(setup):
    coord, session = prepared_writer(setup)
    session.fail_cas = True
    with pytest.raises(CustodyBlocked, match="CAS_CONFLICT"):
        coord.finalize(session, coord.generation)
    assert not session.committed
    with pytest.raises(CustodyBlocked, match="CONSUMED"):
        coord.finalize(FakeSession(coord, session.row), coord.generation)


def test_protected_terminal_and_unknown_never_reach_authority(setup):
    coord, session = prepared_writer(setup)
    coord.classify = lambda row: "terminal_phase9_recovery"
    session.configuration = (coord.policy, coord.archive, coord.classify, coord.resolve_links, coord.authority_gate)
    with pytest.raises(CustodyBlocked, match="MUST_NOT_EVICT"):
        coord.finalize(session, coord.generation)
    assert not session.committed


@pytest.mark.parametrize("failure", [None, "missing_commit", "cas_conflict"])
def test_actual_fakeredis_writer_archive_verify_guard_append_trim(setup, failure):
    coord = coordinator()
    obj = SimpleNamespace(retention=coord, _key=lambda *p: ":".join(("synthetic-authority", *p)))
    raw = b' {"source_ledger_id":"synthetic-oldest"}\r\n'
    ledger = "synthetic-authority:audit"
    client = fakeredis.FakeRedis(decode_responses=True)
    client.rpush(ledger, raw)
    obj.redis = GuardedRedis(client, obj)
    row = RawRecord(ledger, sha(raw), raw)
    receipts = coord.preserve((row,))
    custody_id, grant = committed(setup, input_sha256=custody_input_digest(coord.policy, (row,)),
                                  archive_sha256=custody_archive_digest(receipts))
    coord.authority_gate = AuthenticatedCommitHook(setup[0], custody_id, grant.sha256)
    if failure == "missing_commit":
        coord.authority_gate = replace(coord.authority_gate, custody_id=str(uuid4()))
    def write():
        with coord.batch(obj):
            obj.redis.set("synthetic-authority:business", "synthetic-only")
            obj.redis.rpush(ledger, "synthetic-new")
            obj.redis.ltrim(ledger, -1, -1)
            if failure == "cas_conflict":
                client.rpush(ledger, "concurrent-external-writer-fixture")
    if failure is None:
        write()
        assert client.lrange(ledger, 0, -1) == ["synthetic-new"]
        assert client.get("synthetic-authority:business") == "synthetic-only"
        assert setup[0]._transactions[custody_id].consumed
    else:
        with pytest.raises(CustodyBlocked, match="COMMIT_MISSING|LEDGER_CHANGED_NO_RETRY"):
            write()
        assert client.get("synthetic-authority:business") is None
        assert client.lindex(ledger, 0).encode() == raw
        assert setup[0]._transactions[custody_id].consumed == (failure == "cas_conflict")
        if failure == "cas_conflict":
            with pytest.raises(CustodyBlocked, match="CONSUMED"):
                setup[0].consume_commit(custody_id, INPUT, ARCHIVE, grant.sha256)


def test_writer_input_and_archive_digests_are_separate_and_linked_raw_tamper_denied(setup):
    coord, session = prepared_writer(setup)
    bound = replace(session.row, links=(("synthetic-snapshot", b"different linked bytes"),))
    receipt = coord.archive.receipts[session.row.identity]
    assert custody_input_digest(coord.policy, (session.row,)) != custody_archive_digest((receipt,))
    with pytest.raises(CustodyBlocked, match="COMMIT_BINDING_MISMATCH"):
        coord.authority_gate(coord.policy, (bound,), (receipt,))
    assert not session.committed


def test_new_local_authority_memory_writers_have_auth_and_lock_boundaries():
    path = Path(__file__).parents[1] / "npd_agent_hub/custody_authority.py"
    tree = ast.parse(path.read_text(encoding="utf8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "LocalCustodyAuthority")
    methods = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}
    for name in ("perform", "consume_commit"):
        locks = [n for n in ast.walk(methods[name]) if isinstance(n, ast.With)
            and any(ast.unparse(item.context_expr) == "self._lock" for item in n.items)]
        assert len(locks) == 1
    assert "self.authenticator.authenticate(authorization, request)" in ast.unparse(methods["perform"])
    assert "tx.consumed = True" in ast.unparse(methods["consume_commit"])
    callers = [n.name for n in methods.values() if any(isinstance(c, ast.Call)
        and ast.unparse(c.func) == "self._receipt" for c in ast.walk(n))]
    assert callers == ["perform"]
    assert "self._receipts.append(receipt)" in ast.unparse(methods["_receipt"])


def test_forged_principal_object_cannot_replace_a_credential(setup):
    authority, _ = setup
    with pytest.raises(CustodyBlocked, match="AUTHENTICATION_REQUIRED"):
        authority.perform(Principal(Role.OWNER, OWNER), request())
    assert authority.receipts[-1].actor_subject is None
