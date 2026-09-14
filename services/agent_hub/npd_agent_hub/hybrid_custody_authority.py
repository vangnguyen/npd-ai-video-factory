"""Hybrid Google Owner/service-key authority v2, unmounted and LOCAL/TEST ONLY.

v1 journals/receipts are never reinterpreted. SQL consumes action and commit
identities before success; a trust change stops an existing transaction. A real
PostgreSQL trust/revocation commit fence remains a separate acceptance gate.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
import time
from uuid import UUID

from fastapi import HTTPException

from .auth import Role, StaticTokenAuthorizer
from .authority_journal import SQLiteFixtureAuthorityJournal, empty_snapshot
from .custody_authority import CustodyAction, CustodyActionRequest, exact_digest, exact_uuid
from .custody_identity import OwnerOriginPin, canonical, digest
from .retention_custody import CustodyBlocked
from .scoped_custody_issuer import (
    CAPABILITIES, CUSTODIAN, VERIFIER, CustodyTrustStore, VerifiedServiceActor, verify_service_token)

SCHEMA_V2 = "npd.agent-hub.custody.hybrid-authority-journal.local-sql.v2"
RECEIPT_DOMAIN_V2 = b"npd.agent-hub.custody.hybrid-authority-receipt.v2\0"
A = CustodyAction
ORDER = [A.HOLD_REQUEST.value, A.ARCHIVE_WRITE.value, A.CUSTODY_VERIFY.value, A.CUSTODY_COMMIT.value]


class HybridSQLiteFixtureJournal(SQLiteFixtureAuthorityJournal):
    schema = SCHEMA_V2
    domain = b"npd.agent-hub.custody.hybrid-journal-commit.v2\0"


@dataclass(frozen=True)
class HybridAuthorityReceipt:
    schema: str
    actor_issuer: str
    actor_subject: str
    effective_capability: str
    actor_kid: str
    actor_public_key_sha256: str
    trust_epoch: int
    owner_mapping_sha256: str
    custody_id: str
    action: str
    observed_utc: str
    payload_sha256: str
    input_sha256: str
    result_sha256: str
    previous_receipt_sha256: str | None
    authorization_decision: str
    reason: str
    token_id: str
    expires_at: int

    @property
    def sha256(self):
        return digest(RECEIPT_DOMAIN_V2 + canonical(asdict(self)))


class HybridCustodyAuthority:
    synthetic_local_only = True

    def __init__(self, *, owner_pin: OwnerOriginPin, authorizer: StaticTokenAuthorizer,
                 trust_store: CustodyTrustStore, journal, production_mode=False):
        if production_mode:
            raise CustodyBlocked("PRODUCTION_HYBRID_AUTHORITY_NOT_ACCEPTED_HOLD")
        if (not isinstance(owner_pin, OwnerOriginPin) or not isinstance(authorizer, StaticTokenAuthorizer)
            or not isinstance(journal, HybridSQLiteFixtureJournal)):
            raise CustodyBlocked("HYBRID_DURABLE_JOURNAL_AND_OWNER_PIN_REQUIRED_HOLD")
        self.owner_pin = owner_pin
        self.authorizer = authorizer
        self.trust_store = trust_store
        self.journal = journal
        try:
            self._bundle = trust_store.snapshot()
        except (AttributeError, TypeError) as error:
            raise CustodyBlocked("CUSTODY_TRUST_UNAVAILABLE_OR_UNKNOWN_HOLD") from error
        self._trust_sha256 = self._bundle.binding_sha256
        if journal.trust_sha256 != self.binding_sha256(owner_pin, self._bundle):
            raise CustodyBlocked("HYBRID_JOURNAL_TRUST_BINDING_MISMATCH_HOLD")
        self._restore(journal.read_snapshot())

    @staticmethod
    def binding_sha256(owner_pin, bundle):
        return digest(b"npd.agent-hub.custody.hybrid-binding.v2\0" + canonical({
            "owner_origin": owner_pin.binding, "service_trust_sha256": bundle.binding_sha256,
            "receipt_schema": "npd.agent-hub.custody.hybrid-authority-receipt.v2"}))

    def _restore(self, snapshot):
        """Validate exact actor/digest chain and reconstruct allowed transitions."""
        try:
            if (set(snapshot) != set(empty_snapshot(SCHEMA_V2)) or snapshot["schema"] != SCHEMA_V2
                or type(snapshot["receipts"]) is not list or type(snapshot["seen_token_ids"]) is not list
                or type(snapshot["transactions"]) is not dict):
                raise ValueError()
            expected = {}
            token_ids = []
            receipts = []
            for raw in snapshot["receipts"]:
                if type(raw) is not dict or set(raw) != {f.name for f in fields(HybridAuthorityReceipt)}:
                    raise ValueError()
                r = HybridAuthorityReceipt(**raw)
                if (r.schema != "npd.agent-hub.custody.hybrid-authority-receipt.v2"
                    or r.action not in ORDER or r.authorization_decision not in {"ALLOW", "DENY"}
                    or type(r.trust_epoch) is not int or r.trust_epoch != self._bundle.epoch
                    or r.owner_mapping_sha256 != self._owner_mapping_sha256()
                    or type(r.expires_at) is not int or not isinstance(r.reason, str)):
                    raise ValueError()
                observed = datetime.fromisoformat(r.observed_utc)
                if observed.tzinfo is None or observed.utcoffset().total_seconds() != 0:
                    raise ValueError()
                if not int(observed.timestamp()) < r.expires_at <= int(observed.timestamp()) + 900:
                    raise ValueError()
                for value in (r.payload_sha256, r.input_sha256, r.result_sha256, r.actor_public_key_sha256):
                    exact_digest(value)
                if r.previous_receipt_sha256 is not None:
                    exact_digest(r.previous_receipt_sha256)
                exact_uuid(r.custody_id)
                exact_uuid(r.token_id)
                if r.token_id in token_ids:
                    raise ValueError()
                token_ids.append(r.token_id)
                if r.action == A.HOLD_REQUEST.value:
                    if (r.actor_issuer != self.owner_pin.issuer or r.actor_subject != self.owner_pin.subject
                        or r.effective_capability != "custody.hold.request" or not r.actor_kid):
                        raise ValueError()
                else:
                    key = next(k for k in self._bundle.keys if k.kid == r.actor_kid)
                    cap = {A.ARCHIVE_WRITE.value: "custody.archive.write", A.CUSTODY_VERIFY.value:
                           "custody.archive.verify", A.CUSTODY_COMMIT.value: "custody.commit"}[r.action]
                    if (r.actor_issuer != self._bundle.issuer or r.actor_subject != key.subject
                        or r.actor_public_key_sha256 != key.fingerprint or r.effective_capability != cap
                        or cap not in CAPABILITIES[key.subject]):
                        raise ValueError()
                if r.authorization_decision == "ALLOW":
                    actor = [r.actor_issuer, r.actor_subject]
                    prior = expected.get(r.custody_id)
                    if r.action == A.HOLD_REQUEST.value:
                        if prior or r.previous_receipt_sha256 is not None or r.input_sha256 != r.result_sha256:
                            raise ValueError()
                        expected[r.custody_id] = {"state": r.action, "requester": actor,
                            "custodian": None, "verifier": None, "input_sha256": r.input_sha256,
                            "archive_sha256": None, "expires_at": r.expires_at, "consumed": False,
                            "last_receipt_sha256": r.sha256}
                    else:
                        if (prior is None or ORDER.index(r.action) != ORDER.index(prior["state"]) + 1
                            or r.previous_receipt_sha256 != prior["last_receipt_sha256"]
                            or r.input_sha256 != prior["input_sha256"] or actor == prior["requester"]
                            or int(observed.timestamp()) >= prior["expires_at"]):
                            raise ValueError()
                        if r.action == A.ARCHIVE_WRITE.value:
                            prior["custodian"], prior["archive_sha256"] = actor, r.result_sha256
                        elif r.result_sha256 != prior["archive_sha256"]:
                            raise ValueError()
                        if r.action == A.CUSTODY_VERIFY.value:
                            if actor == prior["custodian"]:
                                raise ValueError()
                            prior["verifier"] = actor
                        if r.action == A.CUSTODY_COMMIT.value and (actor != prior["custodian"] or actor == prior["verifier"]):
                            raise ValueError()
                        prior.update(state=r.action, expires_at=min(prior["expires_at"], r.expires_at),
                                     last_receipt_sha256=r.sha256)
                receipts.append(r)
            if snapshot["seen_token_ids"] != token_ids or set(snapshot["transactions"]) != set(expected):
                raise ValueError()
            for txid, derived in expected.items():
                actual = snapshot["transactions"][txid]
                if type(actual) is not dict or set(actual) != set(derived) or type(actual["consumed"]) is not bool:
                    raise ValueError()
                if actual["consumed"] and actual["state"] != A.CUSTODY_COMMIT.value:
                    raise ValueError()
                derived["consumed"] = actual["consumed"]
                if actual != derived:
                    raise ValueError()
            return receipts
        except (ValueError, TypeError, KeyError, AttributeError, StopIteration) as error:
            raise CustodyBlocked("HYBRID_JOURNAL_SEMANTIC_CORRUPTION_HOLD") from error

    def _owner_actor(self, session_cookie, request, origin, bundle):
        if request.action != A.HOLD_REQUEST:
            raise CustodyBlocked("OWNER_CANNOT_ACT_AS_SERVICE_HOLD")
        try:
            principal = self.authorizer.require(Role.OWNER, None, session_cookie, method="POST", origin=origin)
            context = principal.stable_context
            payload = self.authorizer.verify_payload(session_cookie)
            now = int(time.time())
            if (principal.auth_method != "session" or not self.owner_pin.accepts(context)
                or self.authorizer.role_for_email(principal.subject) != Role.OWNER
                or not context.issued_at <= now < context.expires_at
                or context.verified_at > now
                or context.public_key_sha256 in {k.fingerprint for k in bundle.keys}
                or type(payload.get("iat")) is not int or payload["iat"] > now):
                raise ValueError()
        except (HTTPException, ValueError, TypeError, AttributeError) as error:
            raise CustodyBlocked("STABLE_CURRENT_OWNER_AUTHORITY_REQUIRED_HOLD") from error
        # Request-specific single-use identity derived from verified signed context;
        # no new requester token is issued and no original credential is journaled.
        proof = digest(b"npd.agent-hub.custody.owner-action.v2\0" + canonical({
            "session_sha256": digest(session_cookie.encode("ascii")), "request": request.model_dump(mode="json")}))
        return VerifiedServiceActor(context.issuer, context.subject, "custody.hold.request", context.kid,
            context.public_key_sha256, bundle.epoch, str(UUID(hex=proof[:32])), proof,
            min(payload["exp"], context.expires_at, now + 900))

    @property
    def receipts(self):
        with self.trust_store.fence(self._trust_sha256):
            return self._restore(self.journal.read_snapshot())

    def perform_owner(self, session_cookie, request, *, origin):
        return self._perform(request, lambda bundle: self._owner_actor(session_cookie, request, origin, bundle))

    def perform_service(self, authorization, request):
        return self._perform(request, lambda bundle: verify_service_token(authorization, request, bundle))

    def _perform(self, request, authenticate):
        if not isinstance(request, CustodyActionRequest) or request.action == A.HOLD_RELEASE:
            raise CustodyBlocked("HOLD_RELEASE_OR_UNKNOWN_ACTION_DEFERRED")
        exact_uuid(request.custody_id)
        exact_digest(request.input_sha256)
        exact_digest(request.result_sha256)
        if request.previous_receipt_sha256 is not None:
            exact_digest(request.previous_receipt_sha256)
        rejected = None
        owner_mapping_sha256 = self._owner_mapping_sha256()
        with self.trust_store.fence(self._trust_sha256) as bundle:
            actor = authenticate(bundle)  # No caller-supplied principal entry point.
            with self.journal.atomic(commit_fence=lambda: self._commit_fence(owner_mapping_sha256, actor.expires_at)) as snapshot:
                self._restore(snapshot)
                if actor.token_id in snapshot["seen_token_ids"]:
                    raise CustodyBlocked("HYBRID_ACTION_JTI_REPLAY_DENIED")
                now = int(time.time())
                if now >= actor.expires_at:
                    raise CustodyBlocked("HYBRID_ACTOR_EXPIRED_HOLD")
                tx = snapshot["transactions"].get(request.custody_id)
                if request.action == A.HOLD_REQUEST:
                    valid = tx is None and request.previous_receipt_sha256 is None and request.result_sha256 == request.input_sha256
                else:
                    identity = [actor.issuer, actor.subject]
                    valid = (tx is not None and not tx["consumed"] and now < tx["expires_at"]
                        and ORDER.index(request.action.value) == ORDER.index(tx["state"]) + 1
                        and request.previous_receipt_sha256 == tx["last_receipt_sha256"]
                        and request.input_sha256 == tx["input_sha256"] and identity != tx["requester"]
                        and (request.action == A.ARCHIVE_WRITE or request.result_sha256 == tx["archive_sha256"])
                        and (request.action != A.CUSTODY_VERIFY or identity != tx["custodian"])
                        and (request.action != A.CUSTODY_COMMIT or (identity == tx["custodian"] and identity != tx["verifier"])))
                if not valid:
                    rejected = CustodyBlocked("HYBRID_TRANSACTION_ORDER_BINDING_OR_SEPARATION_DENIED")
                receipt = HybridAuthorityReceipt("npd.agent-hub.custody.hybrid-authority-receipt.v2",
                    actor.issuer, actor.subject, actor.capability, actor.kid, actor.fingerprint, actor.epoch, owner_mapping_sha256,
                    request.custody_id, request.action.value, datetime.now(timezone.utc).isoformat(), actor.payload_sha256,
                    request.input_sha256, request.result_sha256, request.previous_receipt_sha256,
                    "DENY" if rejected else "ALLOW", str(rejected) if rejected else "PASS", actor.token_id, actor.expires_at)
                snapshot["receipts"].append(asdict(receipt))
                snapshot["seen_token_ids"].append(actor.token_id)
                if not rejected:
                    if request.action == A.HOLD_REQUEST:
                        snapshot["transactions"][request.custody_id] = {"state": request.action.value,
                            "requester": [actor.issuer, actor.subject], "custodian": None, "verifier": None,
                            "input_sha256": request.input_sha256, "archive_sha256": None,
                            "expires_at": actor.expires_at, "consumed": False, "last_receipt_sha256": receipt.sha256}
                    else:
                        tx.update(state=request.action.value, expires_at=min(tx["expires_at"], actor.expires_at),
                                  last_receipt_sha256=receipt.sha256)
                        if request.action == A.ARCHIVE_WRITE:
                            tx.update(custodian=[actor.issuer, actor.subject], archive_sha256=request.result_sha256)
                        elif request.action == A.CUSTODY_VERIFY:
                            tx["verifier"] = [actor.issuer, actor.subject]
                self._restore(snapshot)
                if self.trust_store.snapshot().binding_sha256 != self._trust_sha256:
                    raise CustodyBlocked("CUSTODY_TRUST_CHANGED_HOLD_NO_RETRY")
        if rejected:
            raise rejected
        return receipt

    def consume_commit(self, custody_id, input_sha256, archive_sha256, commit_receipt_sha256):
        """Consume durably BEFORE retention writer CAS; conflicts never re-arm it."""
        owner_mapping_sha256 = self._owner_mapping_sha256()
        expires_at = [None]
        with self.trust_store.fence(self._trust_sha256):
            with self.journal.atomic(commit_fence=lambda: self._commit_fence(owner_mapping_sha256, expires_at[0])) as snapshot:
                self._restore(snapshot)
                tx = snapshot["transactions"].get(custody_id)
                if (tx is None or tx["state"] != A.CUSTODY_COMMIT.value or tx["consumed"]
                    or time.time() >= tx["expires_at"] or input_sha256 != tx["input_sha256"]
                    or archive_sha256 != tx["archive_sha256"] or commit_receipt_sha256 != tx["last_receipt_sha256"]):
                    raise CustodyBlocked("HYBRID_COMMIT_MISSING_EXPIRED_CONSUMED_OR_MISMATCH_HOLD")
                tx["consumed"] = True
                expires_at[0] = tx["expires_at"]
                self._restore(snapshot)
                if self.trust_store.snapshot().binding_sha256 != self._trust_sha256:
                    raise CustodyBlocked("CUSTODY_TRUST_CHANGED_HOLD_NO_RETRY")

    def _owner_mapping_sha256(self):
        # Current trusted business mapping is a fence, never a caller identity.
        return digest(b"npd.agent-hub.custody.owner-mapping.v2\0" + canonical({
            "owner_emails": sorted(self.authorizer.settings.owner_emails),
            "google_audience": self.authorizer.settings.google_client_id,
            "browser_mode": self.authorizer.settings.browser_auth_mode}))

    def _commit_fence(self, owner_mapping_sha256, expires_at):
        if (self.trust_store.snapshot().binding_sha256 != self._trust_sha256
            or self._owner_mapping_sha256() != owner_mapping_sha256):
            raise CustodyBlocked("CUSTODY_TRUST_OR_OWNER_MAPPING_CHANGED_HOLD_NO_RETRY")
        if expires_at is None or time.time() >= expires_at:
            raise CustodyBlocked("HYBRID_COMMIT_FENCE_EXPIRED_HOLD")
