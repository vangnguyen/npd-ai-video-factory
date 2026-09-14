"""Durable wrapper around the accepted authority engine, no issuer/prod activation."""
from __future__ import annotations
from dataclasses import asdict, fields
from datetime import datetime, timezone
import json
from types import MappingProxyType

import jwt
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from .authority_journal import AuthorityJournal, SCHEMA, empty_snapshot
from .custody_authority import (
    ACTION_CAPABILITY, AuthorityReceipt, CustodyAction, CustodyCapability,
    LocalCustodyAuthority, ScopedCustodyAuthenticator, _Transaction,
    encoded, exact_digest, exact_uuid, sha,
)
from .auth import Role
from .retention_custody import CustodyBlocked


class IndependentCredentialAuthenticator(ScopedCustodyAuthenticator):
    """Verified key→subject binding, with three distinct actual public-key hashes.

    A shared signing key hidden behind three kid/role aliases is rejected. Keys
    are separately delegated, issuer-approved subject credentials, not a shared
    issuer key accessible to any party. No private key or issuer is implemented.
    """
    def __init__(self, *, subject_key_ids, **kwargs):
        super().__init__(**kwargs)
        if set(subject_key_ids) != set(self.principals) or len(subject_key_ids) != 3:
            raise CustodyBlocked("THREE_AUTHENTICATED_CREDENTIAL_BINDINGS_REQUIRED")
        fingerprints = {}
        requesters = []
        verifiers = []
        custodians = []
        for subject, key_id in subject_key_ids.items():
            if key_id not in self.keys:
                raise CustodyBlocked("CUSTODY_CREDENTIAL_KEY_UNBOUND")
            fingerprints[subject] = sha(self.keys[key_id].public_bytes(Encoding.DER,
                                                                     PublicFormat.SubjectPublicKeyInfo))
            principal = self.principals[subject]
            if principal.kind == "human" and principal.role == Role.OWNER and principal.capabilities == {CustodyCapability.HOLD_REQUEST}:
                requesters.append(subject)
            elif principal.kind == "service" and principal.capabilities == {CustodyCapability.ARCHIVE_VERIFY}:
                verifiers.append(subject)
            elif principal.kind == "service" and principal.capabilities == {CustodyCapability.ARCHIVE_WRITE, CustodyCapability.COMMIT}:
                custodians.append(subject)
            else:
                raise CustodyBlocked("CUSTODY_CREDENTIAL_CAPABILITY_BOUNDARY_INVALID")
        if len(requesters) != 1 or len(verifiers) != 1 or len(custodians) != 1:
            raise CustodyBlocked("THREE_PARTY_CREDENTIAL_ROLE_BOUNDARIES_REQUIRED")
        if len(set(fingerprints.values())) != 3 or len(set(subject_key_ids.values())) != 3:
            raise CustodyBlocked("SHARED_CUSTODY_CREDENTIAL_FORBIDDEN")
        if set(subject_key_ids.values()) != set(self.keys):
            raise CustodyBlocked("EXTRA_UNBOUND_CUSTODY_CREDENTIAL_KEY")
        self.subject_key_ids = MappingProxyType(dict(subject_key_ids))

    @property
    def binding_sha256(self):
        return sha(b"npd.agent-hub.custody.credential-trust.v1\0" + encoded({
            "issuer": self.issuer, "audience": self.audience, "token_type": "npd-custody+jwt",
            "max_token_seconds": self.max_token_seconds,
            "bindings": [{"subject": subject, "kind": principal.kind,
                "role": principal.role.name if principal.role else None,
                "capabilities": sorted(c.value for c in principal.capabilities),
                "key_id": self.subject_key_ids[subject],
                "public_key_sha256": sha(self.keys[self.subject_key_ids[subject]].public_bytes(
                    Encoding.DER, PublicFormat.SubjectPublicKeyInfo))}
                for subject, principal in sorted(self.principals.items())]}))

    def authenticate(self, authorization, request):
        actor = super().authenticate(authorization, request)
        # Header is already signature/type/algorithm verified by the base class.
        key_id = jwt.get_unverified_header(authorization[7:])["kid"]
        if self.subject_key_ids[actor.subject] != key_id:
            raise CustodyBlocked("CUSTODY_SIGNING_KEY_SUBJECT_MISMATCH")
        return actor


def export_model(model):
    # Match the exact on-disk JSON type contract before validating or committing.
    return json.loads(encoded({"schema": SCHEMA, "receipts": [asdict(r) for r in model.receipts],
        "seen_token_ids": sorted(model._seen_tokens),
        "transactions": {key: asdict(tx) for key, tx in sorted(model._transactions.items())}}))


def restore_model(snapshot, authenticator):
    """Strict schema and successful actor/receipt chain validation before replay."""
    try:
        if not isinstance(snapshot, dict) or set(snapshot) != set(empty_snapshot()) or snapshot["schema"] != SCHEMA:
            raise ValueError()
        if (not isinstance(snapshot["receipts"], list) or not isinstance(snapshot["seen_token_ids"], list)
            or not isinstance(snapshot["transactions"], dict)):
            raise ValueError()
        model = LocalCustodyAuthority(authenticator)
        receipt_fields = {field.name for field in fields(AuthorityReceipt)}
        successful = {}
        for raw in snapshot["receipts"]:
            if not isinstance(raw, dict) or set(raw) != receipt_fields:
                raise ValueError()
            receipt = AuthorityReceipt(**raw)
            action = CustodyAction(receipt.action)
            observed = datetime.fromisoformat(receipt.observed_utc)
            if observed.tzinfo is None or observed.utcoffset() != timezone.utc.utcoffset(observed):
                raise ValueError()
            if receipt.authorization_decision not in {"ALLOW", "DENY"} or not isinstance(receipt.reason, str):
                raise ValueError()
            if receipt.actor_subject is not None and (receipt.actor_issuer != authenticator.issuer
                or receipt.actor_subject not in authenticator.principals):
                raise ValueError()
            if receipt.effective_capability is not None:
                CustodyCapability(receipt.effective_capability)
            if receipt.authorization_decision == "ALLOW":
                exact_uuid(receipt.custody_id)
                exact_digest(receipt.input_sha256)
                exact_digest(receipt.result_sha256)
                if (receipt.actor_subject is None or action not in ACTION_CAPABILITY or
                    receipt.effective_capability != ACTION_CAPABILITY[action].value
                    or ACTION_CAPABILITY[action] not in authenticator.principals[receipt.actor_subject].capabilities
                    or receipt.reason != "PASS"):
                    raise ValueError()
                rows = successful.setdefault(receipt.custody_id, [])
                expected = [CustodyAction.HOLD_REQUEST, CustodyAction.ARCHIVE_WRITE,
                            CustodyAction.CUSTODY_VERIFY, CustodyAction.CUSTODY_COMMIT]
                if len(rows) >= 4 or action != expected[len(rows)]:
                    raise ValueError()
                if rows:
                    if (receipt.previous_receipt_sha256 != rows[-1].sha256
                        or receipt.input_sha256 != rows[0].input_sha256
                        or observed < datetime.fromisoformat(rows[-1].observed_utc)):
                        raise ValueError()
                    if len(rows) >= 2 and receipt.result_sha256 != rows[1].result_sha256:
                        raise ValueError()
                elif receipt.previous_receipt_sha256 is not None or receipt.result_sha256 != receipt.input_sha256:
                    raise ValueError()
                rows.append(receipt)
            model._receipts.append(receipt)
        tokens = snapshot["seen_token_ids"]
        if len(tokens) != len(set(tokens)):
            raise ValueError()
        for token in tokens:
            exact_uuid(token)
        model._seen_tokens = set(tokens)
        if set(snapshot["transactions"]) != set(successful):
            raise ValueError()
        tx_fields = {field.name for field in fields(_Transaction)}
        for custody_id, raw in snapshot["transactions"].items():
            if not isinstance(raw, dict) or set(raw) != tx_fields or type(raw["consumed"]) is not bool or type(raw["expires_at"]) is not int:
                raise ValueError()
            rows = successful[custody_id]
            requester = [authenticator.issuer, rows[0].actor_subject]
            custodian = [authenticator.issuer, rows[1].actor_subject] if len(rows) >= 2 else None
            verifier = [authenticator.issuer, rows[2].actor_subject] if len(rows) >= 3 else None
            if (raw["input_sha256"] != rows[0].input_sha256 or raw["requester"] != requester
                or raw["custodian"] != custodian or raw["verifier"] != verifier
                or raw["state"] != rows[-1].action or raw["last_receipt"] != asdict(rows[-1])
                or raw["archive_sha256"] != (rows[1].result_sha256 if len(rows) >= 2 else None)
                or (raw["consumed"] and len(rows) != 4)):
                raise ValueError()
            if (custodian is not None and custodian == requester) or (verifier is not None and verifier in (requester, custodian)):
                raise ValueError()
            if len(rows) == 4 and rows[3].actor_subject != rows[1].actor_subject:
                raise ValueError()
            if authenticator.principals[rows[0].actor_subject].kind != "human":
                raise ValueError()
            if len(rows) >= 2 and authenticator.principals[rows[1].actor_subject].kind != "service":
                raise ValueError()
            latest_expiry = min(int(datetime.fromisoformat(r.observed_utc).timestamp()) +
                                authenticator.max_token_seconds for r in rows)
            if not 0 < raw["expires_at"] <= latest_expiry:
                raise ValueError()
            model._transactions[custody_id] = _Transaction(raw["input_sha256"], tuple(requester),
                raw["expires_at"], rows[-1], CustodyAction(raw["state"]),
                tuple(custodian) if custodian else None, tuple(verifier) if verifier else None,
                raw["archive_sha256"], raw["consumed"])
        return model
    except (ValueError, TypeError, KeyError, AttributeError, CustodyBlocked) as error:
        raise CustodyBlocked("AUTHORITY_JOURNAL_SEMANTIC_CORRUPTION_HOLD") from error


class DurableCustodyAuthority:
    """Persistence before success/eligibility; no production memory fallback."""
    synthetic_local_only = True

    def __init__(self, *, authenticator: IndependentCredentialAuthenticator,
                 journal: AuthorityJournal | None, production_mode=False):
        if production_mode:
            raise CustodyBlocked("PRODUCTION_DURABLE_AUTHORITY_NOT_ACCEPTED_HOLD")
        if journal is None or not isinstance(authenticator, IndependentCredentialAuthenticator):
            raise CustodyBlocked("DURABLE_AUTHORITY_JOURNAL_AND_INDEPENDENT_CREDENTIALS_REQUIRED")
        self.authenticator = authenticator
        self.journal = journal
        self._check_trust()
        restore_model(journal.read_snapshot(), authenticator)

    def _check_trust(self):
        if self.journal.trust_sha256 != self.authenticator.binding_sha256:
            raise CustodyBlocked("AUTHORITY_JOURNAL_AUTHENTICATOR_TRUST_MISMATCH_HOLD")

    @property
    def receipts(self):
        self._check_trust()
        return restore_model(self.journal.read_snapshot(), self.authenticator).receipts

    def perform(self, authorization, request):
        self._check_trust()
        rejected = None
        with self.journal.atomic() as snapshot:
            model = restore_model(snapshot, self.authenticator)
            try:
                receipt = model.perform(authorization, request)
            except CustodyBlocked as error:
                rejected = error
            current = export_model(model)
            # Validate produced typed state before any durable append is queued.
            restore_model(current, self.authenticator)
            snapshot.clear()
            snapshot.update(current)
        if rejected is not None:
            raise rejected
        return receipt

    def consume_commit(self, custody_id, input_sha256, archive_sha256, commit_receipt_sha256):
        self._check_trust()
        with self.journal.atomic() as snapshot:
            model = restore_model(snapshot, self.authenticator)
            model.consume_commit(custody_id, input_sha256, archive_sha256, commit_receipt_sha256)
            current = export_model(model)
            restore_model(current, self.authenticator)
            snapshot.clear()
            snapshot.update(current)
