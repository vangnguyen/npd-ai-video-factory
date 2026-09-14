"""Actual local crypto/disk/process acceptance. Private fixture keys stay in RAM.

No Google exchange, issuer process, production credential or backend connection.
"""
from dataclasses import asdict, replace
import multiprocessing
from pathlib import Path
import sqlite3
import time
from types import SimpleNamespace
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi import HTTPException
import jwt
import pytest

from npd_agent_hub.auth import Role, StaticTokenAuthorizer, SESSION_COOKIE
from npd_agent_hub.authority_journal import LocalJournalScope, SQLiteFixtureAuthorityJournal, raw_json, sha
from npd_agent_hub.config import HubSettings
from npd_agent_hub.custody_authority import (CustodyAction as A, CustodyActionRequest,
    AuthenticatedCommitHook, custody_input_digest, custody_archive_digest)
from npd_agent_hub.custody_identity import GOOGLE_ISSUER, OwnerOriginPin, origin_principal
from npd_agent_hub.custody_identity import canonical
from npd_agent_hub.hybrid_custody_authority import HybridCustodyAuthority, HybridSQLiteFixtureJournal as Journal
from npd_agent_hub.retention_custody import CustodyBlocked, RawRecord
from npd_agent_hub.scoped_custody_issuer import (PROPOSED_ISSUER, AUDIENCE, TOKEN_TYPE, VERIFIER, CUSTODIAN,
    CAPABILITIES, PublicServiceKey, CustodyTrustBundle, LocalFixtureTrustStore, verify_service_token)
import npd_agent_hub.google_login as login
from local_custody_fixture import fixture_retention
from test_custody_authority import FakeSession

OWNER_SUB = "synthetic-google-immutable-sub-01"
OWNER_EMAIL = "owner@fixture.invalid"
INPUT, ARCHIVE = sha(b"synthetic exact immutable input"), sha(b"synthetic archive version")


def settings():
    return HubSettings(auth_mode="static_token", owner_token="fixture-owner-business-only",
        browser_auth_mode="google_oidc", public_base_url="https://fixture.invalid",
        google_client_id="synthetic-google-audience", google_client_secret="synthetic-not-production",
        session_signing_key="ephemeral-fixture-session-secret-" * 2, owner_emails=(OWNER_EMAIL,))


@pytest.fixture(scope="module")
def keys():
    return {name: rsa.generate_private_key(public_exponent=65537, key_size=2048)
            for name in ("google", VERIFIER, CUSTODIAN)}


def bundle(keys, **changes):
    now = int(time.time())
    args = dict(issuer=PROPOSED_ISSUER, audience=AUDIENCE, epoch=1, keys=tuple(
        PublicServiceKey(subject, subject + "-key-1", keys[subject].public_key().public_bytes(
            Encoding.PEM, PublicFormat.SubjectPublicKeyInfo), now - 5) for subject in (VERIFIER, CUSTODIAN)))
    args.update(changes)
    return CustodyTrustBundle(**args)


def verified_owner(keys, monkeypatch, *, update=None):
    now = int(time.time())
    claims = dict(iss=GOOGLE_ISSUER, aud=settings().google_client_id, sub=OWNER_SUB,
        iat=now, exp=now+600, email=OWNER_EMAIL, email_verified=True, nonce="fixture-nonce")
    claims.update(update or {})
    monkeypatch.setattr(login.jwt, "PyJWKClient", lambda url: SimpleNamespace(
        get_signing_key_from_jwt=lambda token: SimpleNamespace(key=keys["google"].public_key())))
    token = jwt.encode(claims, keys["google"], algorithm="RS256", headers={"kid": "google-fixture-key"})
    return login.verify_google_identity(token, settings(), "fixture-nonce")


@pytest.fixture
def setup(keys, monkeypatch, tmp_path):
    pin = OwnerOriginPin(GOOGLE_ISSUER, OWNER_SUB, settings().google_client_id)
    auth = StaticTokenAuthorizer(settings())
    identity = verified_owner(keys, monkeypatch)
    cookie = auth.create_session(identity.email, Role.OWNER, stable_context=identity.stable_context)
    trust = LocalFixtureTrustStore(bundle(keys))
    journal = Journal.create_fixture(scope=LocalJournalScope(tmp_path),
        trust_sha256=HybridCustodyAuthority.binding_sha256(pin, trust.snapshot()))
    authority = HybridCustodyAuthority(owner_pin=pin, authorizer=auth, trust_store=trust, journal=journal)
    return authority, keys, cookie


def request(action=A.HOLD_REQUEST, *, txid=None, previous=None, input_sha256=INPUT, result_sha256=None):
    return CustodyActionRequest(custody_id=txid or str(uuid4()), action=action,
        input_sha256=input_sha256, result_sha256=result_sha256 or input_sha256,
        previous_receipt_sha256=previous)


def credential(keys, req, *, subject=CUSTODIAN, signer=None, update=None, headers=None):
    now = int(time.time())
    cap = {A.ARCHIVE_WRITE:"custody.archive.write", A.CUSTODY_VERIFY:"custody.archive.verify",
           A.CUSTODY_COMMIT:"custody.commit", A.HOLD_REQUEST:"custody.hold.request"}[req.action]
    claims = dict(iss=PROPOSED_ISSUER, aud=AUDIENCE, sub=subject, iat=now, nbf=now, exp=now+300,
        jti=str(uuid4()), trust_epoch=1, capabilities=[cap], custody_id=req.custody_id,
        action=req.action.value, input_sha256=req.input_sha256, result_sha256=req.result_sha256,
        previous_receipt_sha256=req.previous_receipt_sha256)
    claims.update(update or {})
    signer = signer or subject
    return "Bearer " + jwt.encode(claims, keys[signer], algorithm="RS256",
        headers={"kid": signer + "-key-1", "typ": TOKEN_TYPE, **(headers or {})})


def advance(setup, count=4, *, input_sha256=INPUT, archive_sha256=ARCHIVE):
    authority, keys, cookie = setup
    req = request(input_sha256=input_sha256)
    receipt = authority.perform_owner(cookie, req, origin="https://fixture.invalid")
    for action, subject in list(zip((A.ARCHIVE_WRITE,A.CUSTODY_VERIFY,A.CUSTODY_COMMIT),
                                   (CUSTODIAN,VERIFIER,CUSTODIAN)))[:count-1]:
        req = request(action, txid=req.custody_id, previous=receipt.sha256,
                      input_sha256=input_sha256, result_sha256=archive_sha256)
        receipt = authority.perform_service(credential(keys, req, subject=subject), req)
    return req.custody_id, receipt


def reopen(authority):
    old = authority.journal
    journal = Journal(scope=old.scope, name=old.name, journal_id=old.journal_id,
        trust_sha256=old.trust_sha256, minimum_checkpoint=old.checkpoint())
    return HybridCustodyAuthority(owner_pin=authority.owner_pin, authorizer=authority.authorizer,
        trust_store=authority.trust_store, journal=journal)


def test_actual_callback_retains_verified_origin_and_business_projection(setup, monkeypatch):
    authority, keys, _ = setup
    identity = verified_owner(keys, monkeypatch, update={"iss":"accounts.google.com"})
    monkeypatch.setattr(login, "exchange_google_code", lambda *args: identity)
    auth = authority.authorizer
    state = auth.sign_payload(dict(typ="oauth_state", state="fixture-state", nonce="fixture-nonce", exp=int(time.time())+60))
    response = login.complete_google_login(auth, code="synthetic", state="fixture-state", state_cookie=state)
    from http.cookies import SimpleCookie
    parsed = SimpleCookie(response.headers["set-cookie"])
    principal = auth.authenticate_session(parsed[SESSION_COOKIE].value)
    assert principal.subject == OWNER_EMAIL and principal.role == Role.OWNER
    assert principal.stable_context.issuer == GOOGLE_ISSUER
    assert principal.stable_context.subject == OWNER_SUB
    assert principal.stable_context.principal_id == origin_principal(GOOGLE_ISSUER,OWNER_SUB)
    assert auth.capability_payload(principal, parsed[SESSION_COOKIE].value)["capabilities"] == ["agent_tasks.analyze"]
    assert "custody" not in auth.capability_payload(principal, parsed[SESSION_COOKIE].value)
    assert response.status_code == 303 and response.headers["location"] == "/command-center"


@pytest.mark.parametrize("case", ["legacy", "same-email-wrong-sub", "missing-owner-map", "static-role", "wrong-origin", "expired-session", "bad-context"])
def test_owner_authority_denies_without_independent_stable_binding(setup, monkeypatch, case):
    authority, keys, cookie = setup
    auth = authority.authorizer
    origin = "https://fixture.invalid"
    if case == "legacy": cookie=auth.create_session(OWNER_EMAIL,Role.OWNER)
    if case == "same-email-wrong-sub":
        identity = verified_owner(keys,monkeypatch,update={"sub":"different-immutable-sub"})
        cookie = auth.create_session(OWNER_EMAIL,Role.OWNER,stable_context=identity.stable_context)
    if case == "missing-owner-map": auth.settings=replace(auth.settings,owner_emails=())
    if case == "static-role": cookie=None
    if case == "wrong-origin": origin="https://forged.invalid"
    if case == "expired-session": cookie=auth.create_session(OWNER_EMAIL,Role.OWNER,now=1)
    if case == "bad-context":
        payload=auth.verify_payload(cookie); payload["custody_origin"]["principal_id"]="pid:"+"0"*64
        cookie=auth.sign_payload(payload)
    with pytest.raises(CustodyBlocked): authority.perform_owner(cookie,request(),origin=origin)
    assert not authority.journal.read_snapshot()["receipts"]


def test_changed_email_same_sub_requires_current_owner_mapping(setup, monkeypatch):
    authority, keys, _=setup
    identity=verified_owner(keys,monkeypatch,update={"email":"new-owner@fixture.invalid"})
    auth=authority.authorizer
    cookie=auth.create_session(identity.email,Role.OWNER,stable_context=identity.stable_context)
    with pytest.raises(CustodyBlocked): authority.perform_owner(cookie,request(),origin="https://fixture.invalid")
    auth.settings=replace(auth.settings,owner_emails=(identity.email,))
    assert authority.perform_owner(cookie,request(),origin="https://fixture.invalid").actor_subject==OWNER_SUB


def test_real_independent_crypto_chain_and_restart_commit_consumption(setup):
    authority, _, _=setup
    txid, receipt=advance(setup)
    rows=authority.receipts
    assert rows[0].actor_issuer==GOOGLE_ISSUER and rows[0].actor_subject==OWNER_SUB
    assert rows[1].actor_subject==CUSTODIAN and rows[2].actor_subject==VERIFIER
    assert len({r.actor_public_key_sha256 for r in rows})==3
    assert all(r.trust_epoch==1 and r.payload_sha256 and r.actor_kid for r in rows)
    assert rows[-1].previous_receipt_sha256==rows[-2].sha256
    restarted=reopen(authority)
    restarted.consume_commit(txid,INPUT,ARCHIVE,receipt.sha256)
    with pytest.raises(CustodyBlocked,match="CONSUMED"): reopen(restarted).consume_commit(txid,INPUT,ARCHIVE,receipt.sha256)


@pytest.mark.parametrize("case", ["wrong-signer","wrong-kid-subject","wrong-issuer","wrong-audience","wrong-sub","wrong-capability",
    "expired","not-yet-valid","stale-epoch","wrong-tx","changed-digest","altered-payload","altered-signature","v1-type","missing-epoch","key-url"])
def test_real_crypto_rejects_forged_expired_or_unbound_token(setup, case):
    authority, keys, _=setup
    txid, receipt=advance(setup,2)
    req=request(A.CUSTODY_VERIFY,txid=txid,previous=receipt.sha256,result_sha256=ARCHIVE)
    args=dict(subject=VERIFIER); now=int(time.time())
    updates={"wrong-issuer":{"iss":"https://forged.invalid"},"wrong-audience":{"aud":"other"},
        "wrong-sub":{"sub":"Owner"},"wrong-capability":{"capabilities":["custody.commit"]},
        "expired":{"iat":now-600,"nbf":now-600,"exp":now-1},"not-yet-valid":{"nbf":now+20},
        "stale-epoch":{"trust_epoch":0},"wrong-tx":{"custody_id":str(uuid4())},
        "changed-digest":{"input_sha256":"1"*64}}
    if case in updates: args["update"]=updates[case]
    if case=="wrong-signer": args.update(signer=CUSTODIAN,headers={"kid":VERIFIER+"-key-1"})
    if case=="wrong-kid-subject": args["signer"]=CUSTODIAN
    if case=="v1-type": args["headers"]={"typ":"npd-custody+jwt"}
    if case=="key-url": args["headers"]={"jku":"https://forged.invalid/jwks"}
    token=credential(keys,req,**args)
    if case in {"altered-payload","altered-signature"}:
        parts=token[7:].split("."); index=1 if case=="altered-payload" else 2
        parts[index]=("a" if parts[index][0]!="a" else "b")+parts[index][1:]
        token="Bearer "+".".join(parts)
    if case=="missing-epoch":
        claims=jwt.decode(token[7:],options={"verify_signature":False}); claims.pop("trust_epoch")
        token="Bearer "+jwt.encode(claims,keys[VERIFIER],algorithm="RS256",headers={"kid":VERIFIER+"-key-1","typ":TOKEN_TYPE})
    before=authority.journal.checkpoint()
    with pytest.raises(CustodyBlocked): authority.perform_service(token,req)
    assert authority.journal.checkpoint()==before


@pytest.mark.parametrize("case", ["subject","kid","jti"])
def test_real_revocation_denies_new_actor_and_fences_inflight_transaction(setup, case):
    authority, keys, _=setup
    txid, receipt=advance(setup,2)
    req=request(A.CUSTODY_VERIFY,txid=txid,previous=receipt.sha256,result_sha256=ARCHIVE)
    token=credential(keys,req,subject=VERIFIER)
    old=authority.trust_store.snapshot()
    if case=="subject": new=replace(old,epoch=2,revoked_subjects=frozenset({VERIFIER}))
    if case=="kid": new=replace(old,epoch=2,keys=tuple(replace(k,status="revoked") if k.subject==VERIFIER else k for k in old.keys))
    if case=="jti":
        jti=jwt.decode(token[7:],options={"verify_signature":False})["jti"]
        new=replace(old,epoch=2,revoked_jtis=frozenset({jti}))
    authority.trust_store.replace_fixture(new,expected_sha256=old.binding_sha256)
    with pytest.raises(CustodyBlocked): verify_service_token(token,req,new)
    with pytest.raises(CustodyBlocked,match="TRUST_CHANGED"): authority.perform_service(token,req)


def test_restart_replay_and_consumed_owner_request_never_reactivate(setup):
    authority,keys,cookie=setup
    txid,receipt=advance(setup,1)
    req=request(A.ARCHIVE_WRITE,txid=txid,previous=receipt.sha256,result_sha256=ARCHIVE)
    token=credential(keys,req)
    authority.perform_service(token,req)
    with pytest.raises(CustodyBlocked,match="REPLAY"): reopen(authority).perform_service(token,req)
    with pytest.raises(CustodyBlocked): reopen(authority).perform_owner(cookie,request(txid=txid),origin="https://fixture.invalid")


@pytest.mark.parametrize("case", ["shared-key","short-rsa","ambiguous-active","unavailable","unknown-state","production"])
def test_trust_config_unavailable_or_unsafe_denies(setup,case):
    authority,keys,cookie=setup; old=authority.trust_store.snapshot()
    if case=="shared-key":
        with pytest.raises(CustodyBlocked): replace(old,keys=(old.keys[0],replace(old.keys[1],public_pem=old.keys[0].public_pem)))
    if case=="short-rsa":
        key=rsa.generate_private_key(public_exponent=65537,key_size=1024)
        with pytest.raises(CustodyBlocked): replace(old,keys=(replace(old.keys[0],public_pem=key.public_key().public_bytes(Encoding.PEM,PublicFormat.SubjectPublicKeyInfo)),old.keys[1]))
    if case=="ambiguous-active":
        with pytest.raises(CustodyBlocked): replace(old,keys=(*old.keys,replace(old.keys[0],kid="alias")))
    if case in {"unavailable","unknown-state"}:
        if case=="unavailable": authority.trust_store.unavailable=True
        else: authority.trust_store._bundle=None
        with pytest.raises(CustodyBlocked): authority.perform_owner(cookie,request(),origin="https://fixture.invalid")
    if case=="production":
        with pytest.raises(CustodyBlocked): HybridCustodyAuthority(owner_pin=authority.owner_pin,authorizer=authority.authorizer,
            trust_store=authority.trust_store,journal=authority.journal,production_mode=True)


def test_previous_key_overlap_is_bounded_and_expires(keys):
    old=bundle(keys); now=int(time.time()); original=old.keys[0]
    newkey=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    rotated=replace(old,epoch=2,keys=(replace(original,verify_until=now+60,overlap_from=now),old.keys[1],
        PublicServiceKey(VERIFIER,"verifier-new",newkey.public_key().public_bytes(Encoding.PEM,PublicFormat.SubjectPublicKeyInfo),now)))
    req=request(A.CUSTODY_VERIFY)
    token=credential(keys,req,subject=VERIFIER,update={"trust_epoch":2,"iat":now-1,"nbf":now-1})
    assert verify_service_token(token,req,rotated).kid==original.kid
    with pytest.raises(CustodyBlocked): verify_service_token(credential(keys,req,subject=VERIFIER,update={"trust_epoch":2}),req,rotated)
    with pytest.raises(CustodyBlocked): replace(rotated,keys=(replace(rotated.keys[0],verify_until=now+901),*rotated.keys[1:]))
    expired=replace(rotated,keys=(replace(rotated.keys[0],overlap_from=now-2,verify_until=now),*rotated.keys[1:]))
    with pytest.raises(CustodyBlocked): verify_service_token(token,req,expired)


@pytest.mark.parametrize("case", ["corrupt","missing","unavailable","v1-journal","chain-break","actor-digest"])
def test_journal_and_receipt_corruption_fails_closed(setup,case):
    authority,_,cookie=setup; advance(setup,2); old=authority.journal
    if case=="unavailable": old.unavailable=True
    if case=="missing": old.scope.path(old.name).unlink()
    if case=="corrupt":
        with sqlite3.connect(old.scope.path(old.name)) as connection: connection.execute("UPDATE commits SET state=? WHERE sequence=1",(b"corrupt",))
    if case in {"chain-break","actor-digest"}:
        snapshot=old.read_snapshot()
        field="previous_receipt_sha256" if case=="chain-break" else "actor_public_key_sha256"
        snapshot["receipts"][1][field]="0"*64
        with pytest.raises(CustodyBlocked): authority._restore(snapshot)
        return
    if case=="v1-journal":
        v1=SQLiteFixtureAuthorityJournal.create_fixture(scope=old.scope,name="historical-v1.sqlite",trust_sha256=old.trust_sha256)
        with pytest.raises(CustodyBlocked): HybridCustodyAuthority(owner_pin=authority.owner_pin,authorizer=authority.authorizer,
            trust_store=authority.trust_store,journal=v1)
        return
    with pytest.raises(CustodyBlocked): authority.perform_owner(cookie,request(),origin="https://fixture.invalid")


def concurrent_actor(root, journal_id, checkpoint, pin, config, trust, token, req, event, queue):
    try:
        store=LocalFixtureTrustStore(trust)
        journal=Journal(scope=LocalJournalScope(Path(root)),name="authority.sqlite",journal_id=journal_id,
            trust_sha256=HybridCustodyAuthority.binding_sha256(pin,trust),minimum_checkpoint=checkpoint)
        authority=HybridCustodyAuthority(owner_pin=pin,authorizer=StaticTokenAuthorizer(config),trust_store=store,journal=journal)
        event.wait(15)
        authority.perform_service(token,req)
        queue.put("PASS")
    except CustodyBlocked: queue.put("DENY")


@pytest.mark.parametrize("count", [1,2,3])
@pytest.mark.parametrize("distinct_jti", [False,True])
def test_actual_multiprocess_single_winner_archive_verify_commit(setup,count,distinct_jti):
    authority,keys,_=setup; txid,receipt=advance(setup,count)
    action=(A.ARCHIVE_WRITE,A.CUSTODY_VERIFY,A.CUSTODY_COMMIT)[count-1]
    subject=VERIFIER if action==A.CUSTODY_VERIFY else CUSTODIAN
    req=request(action,txid=txid,previous=receipt.sha256,result_sha256=ARCHIVE)
    token=credential(keys,req,subject=subject)
    context=multiprocessing.get_context("spawn"); event=context.Event(); queue=context.Queue()
    args=(str(authority.journal.scope.fixture_root),authority.journal.journal_id,authority.journal.checkpoint(),
          authority.owner_pin,authority.authorizer.settings,authority.trust_store.snapshot(),token,req,event,queue)
    other_args=(*args[:6],credential(keys,req,subject=subject),*args[7:]) if distinct_jti else args
    children=[context.Process(target=concurrent_actor,args=arguments) for arguments in (args,other_args)]
    try:
        for child in children: child.start()
        event.set()
        for child in children: child.join(25); assert child.exitcode==0
        assert sorted(queue.get(timeout=5) for _ in children)==["DENY","PASS"]
        assert len([row for row in reopen(authority).receipts if row.authorization_decision=="ALLOW"])==count+1
    finally:
        for child in children:
            if child.is_alive(): child.terminate(); child.join(10)


@pytest.mark.parametrize("cas_conflict", [False,True])
def test_archive_verify_journal_commit_retention_guard_no_rearm(setup,cas_conflict):
    authority,_,_=setup; coord=fixture_retention()
    row=RawRecord("synthetic-fixture","synthetic-record",b"exact immutable raw\r\n")
    session=FakeSession(coord,row); bound=replace(row,links=coord.resolve_links(row,session))
    proofs=coord.preserve((bound,))
    txid,receipt=advance(setup,input_sha256=custody_input_digest(coord.policy,(bound,)),archive_sha256=custody_archive_digest(proofs))
    coord.authority_gate=AuthenticatedCommitHook(authority,txid,receipt.sha256)
    session.configuration=(coord.policy,coord.archive,coord.classify,coord.resolve_links,coord.authority_gate)
    session.fail_cas=cas_conflict
    if cas_conflict:
        with pytest.raises(CustodyBlocked,match="CAS_CONFLICT"): coord.finalize(session,coord.generation)
    else: coord.finalize(session,coord.generation); assert session.committed
    assert reopen(authority).journal.read_snapshot()["transactions"][txid]["consumed"]
    with pytest.raises(CustodyBlocked): coord.finalize(FakeSession(coord,row),coord.generation)


def test_requester_cannot_verify_and_service_roles_cannot_swap(setup):
    authority,keys,cookie=setup; txid,receipt=advance(setup,2)
    req=request(A.CUSTODY_VERIFY,txid=txid,previous=receipt.sha256,result_sha256=ARCHIVE)
    with pytest.raises(CustodyBlocked): authority.perform_owner(cookie,req,origin="https://fixture.invalid")
    with pytest.raises(CustodyBlocked): authority.perform_service(credential(keys,req,subject=CUSTODIAN),req)
    req=request(A.CUSTODY_COMMIT,txid=txid,previous=receipt.sha256,result_sha256=ARCHIVE)
    with pytest.raises(CustodyBlocked): authority.perform_service(credential(keys,req,subject=VERIFIER),req)


@pytest.mark.parametrize("field", ["subject","role","principal","capability"])
def test_caller_identity_fields_never_authority(field):
    with pytest.raises(ValueError): CustodyActionRequest(**request().model_dump(),**{field:"Owner"})


@pytest.mark.parametrize("case", ["trust","owner-map"])
def test_actual_commit_fence_rolls_back_if_public_trust_or_owner_mapping_changes(setup,monkeypatch,case):
    authority,_,cookie=setup; checkpoint=authority.journal.checkpoint()
    append=authority.journal._append_commit
    def mutate(connection,previous,state,tip):
        append(connection,previous,state,tip)
        if case=="trust":
            old=authority.trust_store.snapshot()
            authority.trust_store.replace_fixture(replace(old,epoch=2),expected_sha256=old.binding_sha256)
        else: authority.authorizer.settings=replace(authority.authorizer.settings,owner_emails=())
    monkeypatch.setattr(authority.journal,"_append_commit",mutate)
    with pytest.raises(CustodyBlocked,match="CHANGED_HOLD_NO_RETRY"):
        authority.perform_owner(cookie,request(),origin="https://fixture.invalid")
    assert authority.journal.checkpoint()==checkpoint and not authority.journal.read_snapshot()["receipts"]


def test_owner_mapping_change_after_request_is_hold_even_after_restart(setup):
    authority,_,_=setup; advance(setup,1)
    authority.authorizer.settings=replace(authority.authorizer.settings,owner_emails=("other@fixture.invalid",))
    with pytest.raises(CustodyBlocked,match="SEMANTIC_CORRUPTION_HOLD"): reopen(authority)


def test_google_key_cannot_double_as_service_credential(setup,keys):
    authority,_,cookie=setup; old=authority.trust_store.snapshot()
    shared=replace(old,keys=(replace(old.keys[0],public_pem=keys["google"].public_key().public_bytes(
        Encoding.PEM,PublicFormat.SubjectPublicKeyInfo)),old.keys[1]))
    journal=Journal.create_fixture(scope=authority.journal.scope,name="shared-owner-key.sqlite",
        trust_sha256=HybridCustodyAuthority.binding_sha256(authority.owner_pin,shared))
    candidate=HybridCustodyAuthority(owner_pin=authority.owner_pin,authorizer=authority.authorizer,
        trust_store=LocalFixtureTrustStore(shared),journal=journal)
    with pytest.raises(CustodyBlocked): candidate.perform_owner(cookie,request(),origin="https://fixture.invalid")


@pytest.mark.parametrize("role", [Role.VIEWER,Role.OPERATOR])
def test_business_roles_without_custody_authority_deny(setup,role):
    authority,_,cookie=setup; payload=authority.authorizer.verify_payload(cookie)
    emails=(OWNER_EMAIL,)
    authority.authorizer.settings=replace(authority.authorizer.settings,owner_emails=(),
        viewer_emails=emails if role==Role.VIEWER else (),operator_emails=emails if role==Role.OPERATOR else ())
    payload["role"]=role.name.lower()
    cookie=authority.authorizer.sign_payload(payload)
    with pytest.raises(CustodyBlocked): authority.perform_owner(cookie,request(),origin="https://fixture.invalid")


def test_commit_fence_failure_does_not_reactivate_existing_consumed_action(setup,monkeypatch):
    authority,_,_=setup; txid,receipt=advance(setup)
    before=authority.journal.checkpoint()
    append=authority.journal._append_commit
    def fail(connection,previous,state,tip):
        append(connection,previous,state,tip)
        authority.trust_store.unavailable=True
    monkeypatch.setattr(authority.journal,"_append_commit",fail)
    with pytest.raises(CustodyBlocked): authority.consume_commit(txid,INPUT,ARCHIVE,receipt.sha256)
    authority.trust_store.unavailable=False
    assert authority.journal.checkpoint()==before
    # Earlier authenticated action/JTI remains consumed; no pilot/execution retry.
    assert authority.journal.read_snapshot()["transactions"][txid]["state"]==A.CUSTODY_COMMIT.value


@pytest.mark.parametrize("category", ["active_operation","terminal_phase9_recovery","owner_authorization","held_security_incident","unknown"])
def test_protected_or_unknown_never_becomes_trim_eligible(setup,category):
    authority,_,_=setup; coord=fixture_retention(); coord.classify=lambda row: category
    session=FakeSession(coord,RawRecord("synthetic","record",b"protected raw"))
    before=authority.journal.checkpoint()
    with pytest.raises(CustodyBlocked): coord.finalize(session,coord.generation)
    assert not session.committed and authority.journal.checkpoint()==before


@pytest.mark.parametrize("case", ["roundtrip","wrong-digest","tampered-fingerprint","private-jwk","capability","duplicate-key","unknown-issuer"])
def test_public_jwks_trust_import_is_pinned_and_public_only(keys,case):
    trust=bundle(keys); doc=trust.public_document(); raw=canonical(doc)
    if case=="roundtrip":
        assert CustodyTrustBundle.from_public_bytes(raw,expected_sha256=sha(raw)).binding_sha256==trust.binding_sha256
        return
    if case=="tampered-fingerprint": doc["keys"][0]["fingerprint"]="0"*64
    if case=="private-jwk": doc["keys"][0]["jwk"]["d"]="forbidden-private-component-fixture-no-real-material"
    if case=="capability": doc["keys"][0]["capabilities"]=["custody.hold.request"]
    if case=="duplicate-key": doc["keys"].append(doc["keys"][0])
    if case=="unknown-issuer": doc["issuer"]="https://forged.invalid"
    raw=canonical(doc)
    with pytest.raises(CustodyBlocked): CustodyTrustBundle.from_public_bytes(raw,
        expected_sha256="0"*64 if case=="wrong-digest" else sha(raw))
