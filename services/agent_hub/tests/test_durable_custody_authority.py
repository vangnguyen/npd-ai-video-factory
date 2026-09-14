"""Real LOCAL disk/process proof; ephemeral synthetic keys never persisted."""
from dataclasses import asdict, replace
import copy
import multiprocessing
from pathlib import Path
import sqlite3
import time
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
import jwt
import pytest

from npd_agent_hub.auth import Role
from npd_agent_hub.authority_journal import (
    DOMAIN, SCHEMA, LocalJournalScope, SQLiteFixtureAuthorityJournal as Journal,
    raw_json, sha, strict_json,
)
from npd_agent_hub.custody_authority import (
    ACTION_CAPABILITY, TOKEN_TYPE, AuthenticatedCommitHook, CustodyAction as A,
    CustodyActionRequest, CustodyCapability as C, PrincipalBinding,
    custody_archive_digest, custody_input_digest,
)
from npd_agent_hub.durable_custody_authority import (
    DurableCustodyAuthority, IndependentCredentialAuthenticator,
)
from npd_agent_hub.retention_custody import CustodyBlocked, RawRecord
from local_custody_fixture import fixture_retention
from test_custody_authority import FakeSession

ISSUER = "https://synthetic-three-key-issuer.invalid"
AUDIENCE = "synthetic-local-durable-custody"
OWNER, VERIFIER, CUSTODIAN = "synthetic-owner-01", "synthetic-verifier-02", "synthetic-custodian-03"
SUBJECTS = (OWNER, VERIFIER, CUSTODIAN)
KEY_IDS = dict(zip(SUBJECTS, ("synthetic-key-a", "synthetic-key-b", "synthetic-key-c")))
INPUT, ARCHIVE = sha(b"exact synthetic source and links"), sha(b"synthetic archive version proof")


def authenticator(publics, **changes):
    args = dict(issuer=ISSUER, audience=AUDIENCE, public_keys=publics,
        subject_key_ids=KEY_IDS, principals=(
            PrincipalBinding(OWNER, "human", frozenset({C.HOLD_REQUEST}), Role.OWNER),
            PrincipalBinding(VERIFIER, "service", frozenset({C.ARCHIVE_VERIFY})),
            PrincipalBinding(CUSTODIAN, "service", frozenset({C.ARCHIVE_WRITE, C.COMMIT}))))
    args.update(changes)
    return IndependentCredentialAuthenticator(**args)


@pytest.fixture(scope="module")
def keys():
    return {subject: rsa.generate_private_key(public_exponent=65537, key_size=2048)
            for subject in SUBJECTS}


def public_keys(keys):
    return {KEY_IDS[subject]: key.public_key().public_bytes(serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo) for subject, key in keys.items()}


@pytest.fixture
def setup(keys, tmp_path):
    auth = authenticator(public_keys(keys))
    journal = Journal.create_fixture(scope=LocalJournalScope(tmp_path), trust_sha256=auth.binding_sha256)
    return DurableCustodyAuthority(authenticator=auth, journal=journal), keys


def request(action=A.HOLD_REQUEST, *, custody_id=None, input_sha256=INPUT,
            result_sha256=None, previous=None):
    return CustodyActionRequest(custody_id=custody_id or str(uuid4()), action=action,
        input_sha256=input_sha256, result_sha256=result_sha256 or input_sha256,
        previous_receipt_sha256=previous)


def credential(keys, req, *, subject=OWNER, caps=None, update=None, signing_subject=None, header=None):
    now = int(time.time())
    payload = dict(iss=ISSUER, aud=AUDIENCE, sub=subject, iat=now, nbf=now, exp=now + 600,
        jti=str(uuid4()), capabilities=caps if caps is not None else [ACTION_CAPABILITY[req.action].value],
        custody_id=req.custody_id, action=req.action.value, input_sha256=req.input_sha256,
        result_sha256=req.result_sha256, previous_receipt_sha256=req.previous_receipt_sha256)
    payload.update(update or {})
    signer = signing_subject or (subject if subject in keys else OWNER)
    return "Bearer " + jwt.encode(payload, keys[signer], algorithm="RS256",
        headers={"kid": KEY_IDS[signer], "typ": TOKEN_TYPE, **(header or {})})


def advance(setup, count=4, *, input_sha256=INPUT, archive_sha256=ARCHIVE):
    authority, keys = setup
    custody_id = str(uuid4())
    receipt = None
    for action, subject in list(zip((A.HOLD_REQUEST, A.ARCHIVE_WRITE, A.CUSTODY_VERIFY, A.CUSTODY_COMMIT),
                                    (OWNER, CUSTODIAN, VERIFIER, CUSTODIAN)))[:count]:
        req = request(action, custody_id=custody_id, input_sha256=input_sha256,
            result_sha256=input_sha256 if action == A.HOLD_REQUEST else archive_sha256,
            previous=receipt.sha256 if receipt else None)
        receipt = authority.perform(credential(keys, req, subject=subject), req)
    return custody_id, receipt


def reopen(authority, *, checkpoint=None):
    old = authority.journal
    journal = Journal(scope=old.scope, name=old.name, journal_id=old.journal_id,
        trust_sha256=old.trust_sha256, minimum_checkpoint=checkpoint or old.checkpoint())
    return DurableCustodyAuthority(authenticator=authority.authenticator, journal=journal)


def test_restart_persists_actor_chain_and_consumed_commit(setup):
    authority, _ = setup
    custody_id, receipt = advance(setup)
    assert [r.actor_subject for r in reopen(authority).receipts] == [OWNER, CUSTODIAN, VERIFIER, CUSTODIAN]
    reopen(authority).consume_commit(custody_id, INPUT, ARCHIVE, receipt.sha256)
    snapshot = reopen(authority).journal.read_snapshot()
    assert snapshot["transactions"][custody_id]["consumed"] is True
    with pytest.raises(CustodyBlocked, match="CONSUMED"):
        reopen(authority).consume_commit(custody_id, INPUT, ARCHIVE, receipt.sha256)


def test_restart_rejects_token_and_transaction_replay(setup):
    authority, keys = setup
    req = request()
    token = credential(keys, req)
    authority.perform(token, req)
    for replay in (token, credential(keys, req)):
        with pytest.raises(CustodyBlocked, match="REPLAY"):
            reopen(authority).perform(replay, req)
    assert len([r for r in authority.receipts if r.authorization_decision == "ALLOW"]) == 1


def test_read_is_idempotent_and_never_appends(setup):
    authority, _ = setup
    advance(setup)
    before = authority.journal.checkpoint()
    for _ in range(3):
        assert authority.receipts == reopen(authority).receipts
        assert authority.journal.checkpoint() == before


def process_action(root, journal_id, checkpoint, publics, req_body, token, ready, start, result, consume=None):
    """Only public pins and scoped synthetic credentials cross process RAM."""
    try:
        auth = authenticator(publics)
        journal = Journal(scope=LocalJournalScope(Path(root)), name="authority.sqlite",
            journal_id=journal_id, trust_sha256=auth.binding_sha256, minimum_checkpoint=checkpoint)
        authority = DurableCustodyAuthority(authenticator=auth, journal=journal)
        ready.put("READY")
        if not start.wait(20):
            result.put(("DENY", "LOCAL_FIXTURE_START_TIMEOUT"))
            return
        if consume:
            authority.consume_commit(*consume)
        else:
            req = CustodyActionRequest.model_validate(req_body)
            authority.perform(token, req)
        result.put(("ALLOW", None))
    except CustodyBlocked as error:
        result.put(("DENY", str(error)))
    except Exception as error:
        # Never return argv/token/keys or arbitrary exception data.
        result.put(("UNEXPECTED", type(error).__name__))


def processes(setup, requests, tokens, *, consume=None):
    authority, keys = setup
    context = multiprocessing.get_context("spawn")
    ready, result, start = context.Queue(), context.Queue(), context.Event()
    checkpoint = authority.journal.checkpoint()
    children = [context.Process(target=process_action, args=(str(authority.journal.scope.fixture_root),
        authority.journal.journal_id, checkpoint, public_keys(keys), req.model_dump(mode="json"),
        token, ready, start, result, consume)) for req, token in zip(requests, tokens)]
    try:
        for child in children:
            child.start()
        for _ in children:
            assert ready.get(timeout=25) == "READY"
        start.set()
        outcomes = [result.get(timeout=25) for _ in children]
        for child in children:
            child.join(25)
            assert child.exitcode == 0
        assert not any(row[0] == "UNEXPECTED" for row in outcomes)
        return outcomes
    finally:
        for child in children:
            if child.is_alive():
                child.terminate()
                child.join(10)
        ready.close()
        result.close()


@pytest.mark.parametrize("stage", ["request", "archive", "verify", "commit", "consume"])
def test_multiprocess_single_winner_each_transition(setup, stage):
    authority, keys = setup
    prior_count = {"request": 0, "archive": 1, "verify": 2, "commit": 3, "consume": 4}[stage]
    if prior_count:
        custody_id, receipt = advance(setup, prior_count)
    else:
        custody_id, receipt = str(uuid4()), None
    action = {"request": A.HOLD_REQUEST, "archive": A.ARCHIVE_WRITE,
              "verify": A.CUSTODY_VERIFY, "commit": A.CUSTODY_COMMIT, "consume": A.CUSTODY_COMMIT}[stage]
    subject = {"request": OWNER, "verify": VERIFIER}.get(stage, CUSTODIAN)
    req = request(action, custody_id=custody_id, result_sha256=INPUT if stage == "request" else ARCHIVE,
                  previous=receipt.sha256 if receipt else None)
    token = credential(keys, req, subject=subject)
    outcomes = processes(setup, (req, req), (token, credential(keys, req, subject=subject)),
        consume=(custody_id, INPUT, ARCHIVE, receipt.sha256) if stage == "consume" else None)
    assert sorted(row[0] for row in outcomes) == ["ALLOW", "DENY"]
    assert any("NO_RETRY" in (reason or "") or "MISMATCH" in (reason or "") or "REPLAY" in (reason or "")
               or "CONSUMED" in (reason or "") for decision, reason in outcomes if decision == "DENY"), outcomes
    expected = prior_count + (0 if stage == "consume" else 1)
    assert len([r for r in reopen(authority).receipts if r.authorization_decision == "ALLOW"]) == expected


def test_fresh_process_restart_replay_rejected(setup):
    authority, keys = setup
    req = request()
    token = credential(keys, req)
    authority.perform(token, req)
    outcomes = processes(setup, (req,), (token,))
    assert outcomes == [("DENY", "CUSTODY_RECEIPT_REPLAY_DENIED")]


def test_lock_conflict_does_not_retry_or_append(setup):
    authority, keys = setup
    before = authority.journal.checkpoint()
    with authority.journal.atomic():
        req = request()
        with pytest.raises(CustodyBlocked, match="CONCURRENCY_CONFLICT_NO_RETRY"):
            authority.perform(credential(keys, req), req)
    assert authority.journal.checkpoint() == before


@pytest.mark.parametrize("failure", ["missing", "unavailable", "corrupt_file", "wrong_trust", "wrong_identity", "empty"])
def test_backend_failure_has_no_authority_fallback(setup, failure):
    authority, keys = setup
    req = request()
    journal = authority.journal
    path = journal.scope.path(journal.name)
    if failure == "missing":
        path.unlink()
    elif failure == "unavailable":
        journal.unavailable = True
    elif failure == "corrupt_file":
        path.write_bytes(b"not a sqlite journal")
    elif failure == "wrong_trust":
        journal.trust_sha256 = "0" * 64
    elif failure == "wrong_identity":
        journal.journal_id = str(uuid4())
    elif failure == "empty":
        with sqlite3.connect(path) as connection:
            connection.execute("DELETE FROM commits")
    with pytest.raises(CustodyBlocked, match="HOLD"):
        authority.perform(credential(keys, req), req)
    if failure == "missing":
        assert not path.exists()


@pytest.mark.parametrize("tamper", ["raw", "parent", "state_digest", "commit_digest", "unknown", "token_type", "actor", "receipt_chain", "transaction_state_array", "transaction_state_null"])
def test_corrupt_or_semantically_invalid_chain_denies_even_rehashed_state(setup, tamper):
    authority, keys = setup
    advance(setup, 3)
    path = authority.journal.scope.path(authority.journal.name)
    with sqlite3.connect(path) as connection:
        sequence, parent, raw, digest, tip = connection.execute("SELECT * FROM commits ORDER BY sequence DESC LIMIT 1").fetchone()
        state = strict_json(raw)
        if tamper == "raw":
            raw += b" "
        elif tamper == "parent":
            parent = "0" * 64
        elif tamper == "state_digest":
            digest = "0" * 64
        elif tamper == "commit_digest":
            tip = "0" * 64
        else:
            if tamper == "unknown":
                state["schema"] = "unknown"
            elif tamper == "token_type":
                state["seen_token_ids"].append({"untrusted": "value"})
            elif tamper == "actor":
                state["receipts"][-1]["actor_subject"] = OWNER
            elif tamper == "receipt_chain":
                state["receipts"][-1]["previous_receipt_sha256"] = "0" * 64
            elif tamper.startswith("transaction_state"):
                next(iter(state["transactions"].values()))["state"] = [] if tamper.endswith("array") else None
            raw = raw_json(state)
            digest = sha(raw)
            tip = sha(DOMAIN + raw_json([authority.journal.journal_id, authority.journal.trust_sha256,
                                       sequence, parent, digest]))
        connection.execute("UPDATE commits SET previous_sha256=?,state=?,state_sha256=?,commit_sha256=? WHERE sequence=?",
            (parent, raw, digest, tip, sequence))
    req = request()
    with pytest.raises(CustodyBlocked, match="HOLD"):
        authority.perform(credential(keys, req), req)


def test_checkpoint_rejects_consistent_journal_rollback(setup):
    authority, _ = setup
    custody_id, receipt = advance(setup)
    before = authority.journal.checkpoint()
    authority.consume_commit(custody_id, INPUT, ARCHIVE, receipt.sha256)
    trusted_latest = authority.journal.checkpoint()
    with sqlite3.connect(authority.journal.scope.path(authority.journal.name)) as connection:
        connection.execute("DELETE FROM commits WHERE sequence > ?", (before.sequence,))
    with pytest.raises(CustodyBlocked, match="ROLLBACK"):
        reopen(authority, checkpoint=trusted_latest)


def test_missing_checkpoint_or_production_mode_denies(setup):
    authority, _ = setup
    journal = authority.journal
    args = dict(scope=journal.scope, name=journal.name, journal_id=journal.journal_id,
                trust_sha256=journal.trust_sha256, minimum_checkpoint=None)
    with pytest.raises(CustodyBlocked, match="BINDING_INVALID"):
        Journal(**args)
    with pytest.raises(CustodyBlocked, match="PRODUCTION"):
        Journal(**args, production_mode=True)
    with pytest.raises(CustodyBlocked, match="PRODUCTION"):
        DurableCustodyAuthority(authenticator=authority.authenticator, journal=journal, production_mode=True)
    with pytest.raises(CustodyBlocked, match="REQUIRED"):
        DurableCustodyAuthority(authenticator=authority.authenticator, journal=None)


def test_create_only_and_fixture_scope_are_enforced(setup):
    authority, _ = setup
    with pytest.raises(FileExistsError):
        Journal.create_fixture(scope=authority.journal.scope, trust_sha256=authority.journal.trust_sha256)
    with pytest.raises(CustodyBlocked, match="FIXTURE_SCOPE"):
        LocalJournalScope(Path.cwd()).path("authority.sqlite")
    for name in ("../outside.sqlite", "memory:sqlite", "\\network\\journal"):
        with pytest.raises(CustodyBlocked):
            authority.journal.scope.path(name)


@pytest.mark.parametrize("update,reason", [
    ({"exp": 1}, "INVALID_OR_EXPIRED"),
    ({"iss": "https://wrong-issuer.invalid"}, "INVALID_OR_EXPIRED"),
    ({"aud": "wrong-audience"}, "INVALID_OR_EXPIRED"),
    ({"sub": "unknown"}, "PRINCIPAL_UNKNOWN"),
    ({"sub": "Owner"}, "PRINCIPAL_UNKNOWN"),
    ({"sub": "Viewer"}, "PRINCIPAL_UNKNOWN"),
    ({"sub": "Operator"}, "PRINCIPAL_UNKNOWN"),
    ({"custody_id": str(uuid4())}, "TRANSACTION_MISMATCH"),
    ({"input_sha256": "0" * 64}, "TRANSACTION_MISMATCH"),
    ({"capabilities": []}, "CAPABILITY_DENIED"),
])
def test_wrong_token_binding_denies_with_durable_receipt(setup, update, reason):
    authority, keys = setup
    req = request()
    with pytest.raises(CustodyBlocked, match=reason):
        authority.perform(credential(keys, req, update=update), req)
    rows = reopen(authority).receipts
    assert rows[-1].authorization_decision == "DENY"
    assert not authority.journal.read_snapshot()["transactions"]


@pytest.mark.parametrize("subject,signer", [(VERIFIER, OWNER), (CUSTODIAN, OWNER), (VERIFIER, CUSTODIAN)])
def test_cryptographically_valid_other_key_cannot_impersonate_subject(setup, subject, signer):
    authority, keys = setup
    custody_id, prior = advance(setup, 2 if subject == VERIFIER else 1)
    req = request(A.CUSTODY_VERIFY if subject == VERIFIER else A.ARCHIVE_WRITE,
                  custody_id=custody_id, result_sha256=ARCHIVE, previous=prior.sha256)
    with pytest.raises(CustodyBlocked, match="SIGNING_KEY_SUBJECT_MISMATCH"):
        authority.perform(credential(keys, req, subject=subject, signing_subject=signer), req)


def test_shared_credential_and_verifier_custodian_collision_denied(keys):
    publics = public_keys(keys)
    shared = dict(publics)
    shared[KEY_IDS[VERIFIER]] = shared[KEY_IDS[CUSTODIAN]]
    with pytest.raises(CustodyBlocked, match="SHARED_CUSTODY_CREDENTIAL"):
        authenticator(shared)
    with pytest.raises(CustodyBlocked):
        authenticator(publics, subject_key_ids={OWNER: KEY_IDS[OWNER], VERIFIER: KEY_IDS[VERIFIER]})
    with pytest.raises(CustodyBlocked, match="CAPABILITY_BOUNDARY"):
        authenticator(publics, principals=(
            PrincipalBinding(OWNER, "human", frozenset({C.HOLD_REQUEST}), Role.OWNER),
            PrincipalBinding(VERIFIER, "service", frozenset({C.ARCHIVE_VERIFY, C.COMMIT})),
            PrincipalBinding(CUSTODIAN, "service", frozenset({C.ARCHIVE_WRITE, C.COMMIT}))))


def test_requester_self_verification_and_custodian_self_verification_deny(setup):
    authority, keys = setup
    custody_id, prior = advance(setup, 2)
    req = request(A.CUSTODY_VERIFY, custody_id=custody_id, result_sha256=ARCHIVE, previous=prior.sha256)
    for subject in (OWNER, CUSTODIAN):
        with pytest.raises(CustodyBlocked, match="CAPABILITY_DENIED"):
            authority.perform(credential(keys, req, subject=subject), req)
    assert authority.journal.read_snapshot()["transactions"][custody_id]["state"] == A.ARCHIVE_WRITE


@pytest.mark.parametrize("changes,reason", [
    ({"input_sha256": "0" * 64}, "INPUT_DIGEST_CHANGED"),
    ({"result_sha256": "0" * 64}, "ARCHIVE_RESULT_DIGEST_CHANGED"),
    ({"previous_receipt_sha256": "0" * 64}, "RECEIPT_CHAIN_MISMATCH"),
])
def test_transaction_digest_and_receipt_chain_fail_closed(setup, changes, reason):
    authority, keys = setup
    custody_id, prior = advance(setup, 2)
    req = request(A.CUSTODY_VERIFY, custody_id=custody_id, result_sha256=ARCHIVE,
                  previous=prior.sha256).model_copy(update=changes)
    with pytest.raises(CustodyBlocked, match=reason):
        authority.perform(credential(keys, req, subject=VERIFIER), req)


def prepared_writer(setup):
    authority, _ = setup
    coord = fixture_retention()
    row = RawRecord("synthetic-fixture", "synthetic-record", b"exact source bytes\r\n")
    session = FakeSession(coord, row)
    bound = replace(row, links=coord.resolve_links(row, session))
    receipts = coord.preserve((bound,))
    custody_id, grant = advance(setup, input_sha256=custody_input_digest(coord.policy, (bound,)),
        archive_sha256=custody_archive_digest(receipts))
    coord.authority_gate = AuthenticatedCommitHook(authority, custody_id, grant.sha256)
    session.configuration = (coord.policy, coord.archive, coord.classify, coord.resolve_links, coord.authority_gate)
    return coord, session, custody_id


def test_retention_hook_consumes_durably_before_ledger_cas(setup):
    authority, _ = setup
    coord, session, custody_id = prepared_writer(setup)
    coord.finalize(session, coord.generation)
    assert session.committed
    assert reopen(authority).journal.read_snapshot()["transactions"][custody_id]["consumed"]
    with pytest.raises(CustodyBlocked, match="CONSUMED"):
        coord.finalize(FakeSession(coord, session.row), coord.generation)


def test_failed_ledger_cas_does_not_rearm_after_restart(setup):
    authority, _ = setup
    coord, session, custody_id = prepared_writer(setup)
    session.fail_cas = True
    with pytest.raises(CustodyBlocked, match="CAS_CONFLICT_NO_RETRY"):
        coord.finalize(session, coord.generation)
    assert not session.committed
    assert reopen(authority).journal.read_snapshot()["transactions"][custody_id]["consumed"]
    with pytest.raises(CustodyBlocked, match="CONSUMED"):
        coord.finalize(FakeSession(coord, session.row), coord.generation)


def test_unavailable_journal_prevents_retention_commit(setup):
    authority, _ = setup
    coord, session, _ = prepared_writer(setup)
    authority.journal.unavailable = True
    with pytest.raises(CustodyBlocked, match="UNAVAILABLE_HOLD"):
        coord.finalize(session, coord.generation)
    assert not session.committed


def test_protected_and_unknown_never_reach_journal_eligibility(setup):
    authority, _ = setup
    for category in ("active_operation", "unknown"):
        coord = fixture_retention()
        coord.classify = lambda row, category=category: category
        session = FakeSession(coord, RawRecord("synthetic", "record", b"held raw"))
        before = authority.journal.checkpoint()
        with pytest.raises(CustodyBlocked):
            coord.finalize(session, coord.generation)
        assert not session.committed and authority.journal.checkpoint() == before


def test_interrupted_journal_append_is_rolled_back_no_allow(setup, monkeypatch):
    authority, keys = setup
    checkpoint = authority.journal.checkpoint()
    original = authority.journal._append_commit
    def fail(connection, previous, state, tip):
        original(connection, previous, state, tip)
        raise sqlite3.OperationalError("synthetic failure before durable commit")
    monkeypatch.setattr(authority.journal, "_append_commit", fail)
    req = request()
    with pytest.raises(CustodyBlocked, match="BACKEND_ERROR_HOLD"):
        authority.perform(credential(keys, req), req)
    assert authority.journal.checkpoint() == checkpoint
    assert not authority.receipts


def test_lost_commit_ack_is_hold_and_restart_does_not_rearm(setup, monkeypatch):
    authority, keys = setup
    original = authority.journal._connect
    class LostAck:
        def __init__(self, connection):
            self.connection = connection
        def __getattr__(self, name):
            return getattr(self.connection, name)
        def commit(self):
            self.connection.commit()
            raise sqlite3.OperationalError("synthetic ACK lost after durable commit")
    monkeypatch.setattr(authority.journal, "_connect", lambda write=False:
        LostAck(original(write)) if write else original(write))
    req = request()
    token = credential(keys, req)
    with pytest.raises(CustodyBlocked, match="COMMIT_UNCERTAIN_HOLD_NO_RETRY"):
        authority.perform(token, req)
    assert len(reopen(authority).receipts) == 1
    with pytest.raises(CustodyBlocked, match="REPLAY"):
        reopen(authority).perform(token, req)


def interrupted_process(root, journal_id, checkpoint, publics):
    auth = authenticator(publics)
    journal = Journal(scope=LocalJournalScope(Path(root)), name="authority.sqlite",
        journal_id=journal_id, trust_sha256=auth.binding_sha256, minimum_checkpoint=checkpoint)
    connection = journal._connect(write=True)
    connection.execute("BEGIN IMMEDIATE")
    previous, tip = journal._load(connection)
    state = copy.deepcopy(previous)
    state["seen_token_ids"].append(str(uuid4()))
    journal._append_commit(connection, previous, state, tip)
    # Simulate termination after the actual INSERT, before commit/ACK.
    import os
    os._exit(23)


def test_process_termination_before_ack_preserves_last_committed_state(setup):
    authority, keys = setup
    custody_id, _ = advance(setup, 1)
    checkpoint = authority.journal.checkpoint()
    context = multiprocessing.get_context("spawn")
    child = context.Process(target=interrupted_process, args=(str(authority.journal.scope.fixture_root),
        authority.journal.journal_id, checkpoint, public_keys(keys)))
    try:
        child.start()
        child.join(25)
        assert child.exitcode == 23
    finally:
        if child.is_alive():
            child.terminate()
            child.join(10)
    assert reopen(authority).journal.checkpoint() == checkpoint
    assert custody_id in reopen(authority).journal.read_snapshot()["transactions"]
