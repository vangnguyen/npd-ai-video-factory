"""Authenticated custody contract; unmounted, with no issuer or activation entry.

Existing role tokens/sessions are not custody credentials. A separately trusted
issuer must bind a stable subject, explicit capability, action and transaction.
Only public verification keys are accepted here. The journal is explicitly a
local model; durable replay/CAS storage and real identities remain unbound.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import re
from threading import RLock
from types import MappingProxyType
import time
from uuid import UUID

from cryptography.hazmat.primitives.serialization import load_pem_public_key
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
import jwt
from pydantic import BaseModel, ConfigDict, Field

from .auth import Role
from .retention_custody import CustodyBlocked


class CustodyCapability(str, Enum):
    HOLD_REQUEST = "custody.hold.request"
    ARCHIVE_WRITE = "custody.archive.write"
    ARCHIVE_VERIFY = "custody.archive.verify"
    COMMIT = "custody.commit"


class CustodyAction(str, Enum):
    HOLD_REQUEST = "HOLD_REQUEST"
    ARCHIVE_WRITE = "ARCHIVE_WRITE"
    CUSTODY_VERIFY = "CUSTODY_VERIFY"
    CUSTODY_COMMIT = "CUSTODY_COMMIT"
    HOLD_RELEASE = "HOLD_RELEASE"  # Recognized only to reject; no release/delete path.


ACTION_CAPABILITY = MappingProxyType({
    CustodyAction.HOLD_REQUEST: CustodyCapability.HOLD_REQUEST,
    CustodyAction.ARCHIVE_WRITE: CustodyCapability.ARCHIVE_WRITE,
    CustodyAction.CUSTODY_VERIFY: CustodyCapability.ARCHIVE_VERIFY,
    CustodyAction.CUSTODY_COMMIT: CustodyCapability.COMMIT,
})
TOKEN_TYPE = "npd-custody+jwt"
RECEIPT_DOMAIN = b"npd.agent-hub.custody.authority-receipt.v1\0"
DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}")


def encoded(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                      separators=(",", ":")).encode("utf8", errors="strict")


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def exact_uuid(value: str) -> str:
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError()
    except (ValueError, AttributeError) as error:
        raise CustodyBlocked("CUSTODY_TRANSACTION_ID_INVALID") from error
    return value


def exact_digest(value: str) -> str:
    if not isinstance(value, str) or DIGEST_PATTERN.fullmatch(value) is None:
        raise CustodyBlocked("CUSTODY_DIGEST_INVALID")
    return value


@dataclass(frozen=True)
class PrincipalBinding:
    subject: str
    kind: str  # human / service, from trusted configuration, not token role claims.
    capabilities: frozenset[CustodyCapability]
    role: Role | None = None


@dataclass(frozen=True)
class AuthenticatedCustodyActor:
    issuer: str
    subject: str
    kind: str
    role: Role | None
    capability: CustodyCapability | None
    token_id: str
    expires_at: int

    @property
    def identity(self) -> tuple[str, str]:
        return self.issuer, self.subject


class CustodyActionRequest(BaseModel):
    """No subject, role or capability field can be submitted as authority."""
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    custody_id: str
    action: CustodyAction = Field(strict=False)
    input_sha256: str
    result_sha256: str
    previous_receipt_sha256: str | None = None


class ScopedCustodyAuthenticator:
    """Fixed RS256/issuer/audience/type and explicitly pinned public keys only.

    No JWKS fetch, shared Owner token, private key, token minting or env alias.
    Effective capability is the intersection of signed scope and trusted binding.
    """
    def __init__(self, *, issuer: str, audience: str, public_keys: dict[str, bytes],
                 principals: tuple[PrincipalBinding, ...], max_token_seconds=900):
        if not issuer or not audience or not public_keys or not principals:
            raise CustodyBlocked("CUSTODY_TRUST_UNBOUND")
        if type(max_token_seconds) is not int or not 1 <= max_token_seconds <= 900:
            raise CustodyBlocked("CUSTODY_TOKEN_LIFETIME_INVALID")
        keys = {}
        for key_id, pem in public_keys.items():
            try:
                key = load_pem_public_key(pem)
            except (ValueError, TypeError) as error:
                raise CustodyBlocked("CUSTODY_PUBLIC_KEY_REQUIRED") from error
            if not key_id or not isinstance(key, RSAPublicKey) or key.key_size < 2048:
                raise CustodyBlocked("CUSTODY_PUBLIC_KEY_REQUIRED")
            keys[key_id] = key
        bindings = {}
        for principal in principals:
            if (not principal.subject or principal.subject.strip() != principal.subject
                or principal.subject.casefold() in {"owner", "operator", "viewer", "auth-disabled"}
                or principal.kind not in {"human", "service"}
                or not isinstance(principal.capabilities, frozenset)
                or any(not isinstance(c, CustodyCapability) for c in principal.capabilities)
                or (principal.kind == "human" and not isinstance(principal.role, Role))
                or (principal.kind == "service" and principal.role is not None)
                or principal.subject in bindings):
                raise CustodyBlocked("CUSTODY_PRINCIPAL_BINDING_INVALID")
            bindings[principal.subject] = principal
        self.issuer = issuer
        self.audience = audience
        self.keys = MappingProxyType(keys)
        self.principals = MappingProxyType(bindings)
        self.max_token_seconds = max_token_seconds

    def authenticate(self, authorization: str | None,
                     request: CustodyActionRequest) -> AuthenticatedCustodyActor:
        if request.action == CustodyAction.HOLD_RELEASE:
            raise CustodyBlocked("HOLD_RELEASE_DEFERRED")
        exact_uuid(request.custody_id)
        exact_digest(request.input_sha256)
        exact_digest(request.result_sha256)
        if request.previous_receipt_sha256 is not None:
            exact_digest(request.previous_receipt_sha256)
        if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
            raise CustodyBlocked("CUSTODY_AUTHENTICATION_REQUIRED")
        token = authorization[7:]
        if not token or token != token.strip() or len(token) > 8192:
            raise CustodyBlocked("CUSTODY_TOKEN_INVALID")
        try:
            header = jwt.get_unverified_header(token)
            if (set(header) != {"alg", "kid", "typ"} or header["alg"] != "RS256"
                or header["typ"] != TOKEN_TYPE or header["kid"] not in self.keys):
                raise ValueError()
            payload = jwt.decode(token, self.keys[header["kid"]], algorithms=["RS256"],
                issuer=self.issuer, audience=self.audience,
                options={"require": ["iss", "aud", "sub", "iat", "nbf", "exp", "jti",
                    "capabilities", "custody_id", "action", "input_sha256", "result_sha256"]})
        except (jwt.PyJWTError, ValueError, TypeError, KeyError) as error:
            raise CustodyBlocked("CUSTODY_TOKEN_INVALID_OR_EXPIRED") from error
        if set(payload) != {"iss", "aud", "sub", "iat", "nbf", "exp", "jti",
                           "capabilities", "custody_id", "action", "input_sha256", "result_sha256",
                           "previous_receipt_sha256"}:
            raise CustodyBlocked("CUSTODY_UNEXPECTED_TOKEN_CLAIM")
        if (any(type(payload[k]) is not int for k in ("iat", "nbf", "exp"))
            or not payload["iat"] <= payload["nbf"] < payload["exp"]
            or payload["exp"] - payload["iat"] > self.max_token_seconds):
            raise CustodyBlocked("CUSTODY_TOKEN_LIFETIME_INVALID")
        if (payload["custody_id"] != request.custody_id
            or payload["action"] != request.action.value
            or payload["input_sha256"] != request.input_sha256
            or payload["result_sha256"] != request.result_sha256
            or payload["previous_receipt_sha256"] != request.previous_receipt_sha256):
            raise CustodyBlocked("CUSTODY_TOKEN_TRANSACTION_MISMATCH")
        exact_uuid(payload["jti"])
        if not isinstance(payload["sub"], str) or payload["sub"] not in self.principals:
            raise CustodyBlocked("CUSTODY_PRINCIPAL_UNKNOWN")
        binding = self.principals[payload["sub"]]
        caps = payload["capabilities"]
        capability = ACTION_CAPABILITY[request.action]
        allowed = not (not isinstance(caps, list) or any(not isinstance(c, str) for c in caps)
            or len(caps) != len(set(caps)) or not set(caps) <= {c.value for c in binding.capabilities}
            or capability not in binding.capabilities or capability.value not in caps)
        return AuthenticatedCustodyActor(self.issuer, binding.subject, binding.kind,
            binding.role, capability if allowed else None, payload["jti"], payload["exp"])


@dataclass(frozen=True)
class AuthorityReceipt:
    actor_issuer: str | None
    actor_subject: str | None
    effective_capability: str | None
    custody_id: str | None
    action: str
    observed_utc: str
    input_sha256: str | None
    result_sha256: str | None
    previous_receipt_sha256: str | None
    authorization_decision: str
    reason: str

    @property
    def sha256(self) -> str:
        return sha(RECEIPT_DOMAIN + encoded(asdict(self)))


@dataclass
class _Transaction:
    input_sha256: str
    requester: tuple[str, str]
    expires_at: int
    last_receipt: AuthorityReceipt
    state: CustodyAction = CustodyAction.HOLD_REQUEST
    custodian: tuple[str, str] | None = None
    verifier: tuple[str, str] | None = None
    archive_sha256: str | None = None
    consumed: bool = False


class LocalCustodyAuthority:
    """Local atomic journal; production durable journal integration is NOT bound.

    No automatic retry, deletion, hold release or credential issuance. All public
    actions authenticate a credential again, never accept a supplied Actor object.
    """
    synthetic_local_only = True

    def __init__(self, authenticator: ScopedCustodyAuthenticator | None = None):
        self.authenticator = authenticator
        self._lock = RLock()
        self._transactions: dict[str, _Transaction] = {}
        self._seen_tokens: set[str] = set()
        self._receipts: list[AuthorityReceipt] = []

    @property
    def receipts(self) -> tuple[AuthorityReceipt, ...]:
        with self._lock:
            return tuple(self._receipts)

    def perform(self, authorization: str | None, request: CustodyActionRequest) -> AuthorityReceipt:
        with self._lock:
            actor = None
            try:
                if self.authenticator is None:
                    raise CustodyBlocked("CUSTODY_TRUST_UNBOUND")
                actor = self.authenticator.authenticate(authorization, request)
                if actor.token_id in self._seen_tokens:
                    raise CustodyBlocked("CUSTODY_RECEIPT_REPLAY_DENIED")
                # Every authenticated submission is single-use, including a denied one.
                self._seen_tokens.add(actor.token_id)
                if actor.capability is None:
                    raise CustodyBlocked("CUSTODY_CAPABILITY_DENIED")
                if actor.kind == "human" and actor.role != Role.OWNER:
                    raise CustodyBlocked("CUSTODY_HUMAN_ROLE_DENIED")
                tx = self._transactions.get(request.custody_id)
                if request.action == CustodyAction.HOLD_REQUEST:
                    if actor.kind != "human" or actor.role != Role.OWNER:
                        raise CustodyBlocked("CUSTODY_OWNER_REQUEST_REQUIRED")
                    if tx is not None:
                        raise CustodyBlocked("CUSTODY_TRANSACTION_REPLAY_DENIED")
                    if request.previous_receipt_sha256 is not None or request.result_sha256 != request.input_sha256:
                        raise CustodyBlocked("CUSTODY_REQUEST_BINDING_INVALID")
                else:
                    if tx is None or tx.consumed:
                        raise CustodyBlocked("CUSTODY_TRANSACTION_UNKNOWN_OR_CONSUMED")
                    if request.input_sha256 != tx.input_sha256:
                        raise CustodyBlocked("CUSTODY_INPUT_DIGEST_CHANGED")
                    if time.time() >= tx.expires_at:
                        raise CustodyBlocked("CUSTODY_TRANSACTION_EXPIRED")
                    if request.previous_receipt_sha256 != tx.last_receipt.sha256:
                        raise CustodyBlocked("CUSTODY_RECEIPT_CHAIN_MISMATCH")
                    if actor.identity == tx.requester:
                        raise CustodyBlocked("CUSTODY_SELF_VERIFICATION_OR_COMMIT_DENIED")
                    if actor.kind != "service":
                        raise CustodyBlocked("CUSTODY_SERVICE_PRINCIPAL_REQUIRED")
                    expected = {CustodyAction.ARCHIVE_WRITE: CustodyAction.HOLD_REQUEST,
                        CustodyAction.CUSTODY_VERIFY: CustodyAction.ARCHIVE_WRITE,
                        CustodyAction.CUSTODY_COMMIT: CustodyAction.CUSTODY_VERIFY}
                    if expected.get(request.action) != tx.state:
                        raise CustodyBlocked("CUSTODY_ACTION_ORDER_OR_REPLAY_DENIED")
                    if request.action == CustodyAction.CUSTODY_VERIFY and actor.identity == tx.custodian:
                        raise CustodyBlocked("CUSTODY_WRITER_SELF_VERIFICATION_DENIED")
                    if request.action == CustodyAction.CUSTODY_COMMIT and (
                        actor.identity != tx.custodian or actor.identity == tx.verifier):
                        raise CustodyBlocked("CUSTODY_CUSTODIAN_SEPARATION_REQUIRED")
                    if request.action != CustodyAction.ARCHIVE_WRITE and request.result_sha256 != tx.archive_sha256:
                        raise CustodyBlocked("CUSTODY_ARCHIVE_RESULT_DIGEST_CHANGED")
                receipt = self._receipt(actor, request, "ALLOW", "PASS")
                if request.action == CustodyAction.HOLD_REQUEST:
                    self._transactions[request.custody_id] = _Transaction(
                        request.input_sha256, actor.identity, actor.expires_at, receipt)
                else:
                    tx.expires_at = min(tx.expires_at, actor.expires_at)
                    tx.state = request.action
                    tx.last_receipt = receipt
                    if request.action == CustodyAction.ARCHIVE_WRITE:
                        tx.custodian = actor.identity
                        tx.archive_sha256 = request.result_sha256
                    elif request.action == CustodyAction.CUSTODY_VERIFY:
                        tx.verifier = actor.identity
                return receipt
            except CustodyBlocked as error:
                self._receipt(actor, request, "DENY", str(error))
                raise

    def _receipt(self, actor, request, decision, reason):
        # Invalid caller input is never copied as an audit identity/digest/token.
        try:
            custody_id = exact_uuid(request.custody_id)
        except CustodyBlocked:
            custody_id = None
        def safe_digest(value):
            return value if isinstance(value, str) and DIGEST_PATTERN.fullmatch(value) else None
        receipt = AuthorityReceipt(actor.issuer if actor else None, actor.subject if actor else None,
            actor.capability.value if actor and actor.capability else None, custody_id, request.action.value,
            datetime.now(timezone.utc).isoformat(), safe_digest(request.input_sha256), safe_digest(request.result_sha256),
            safe_digest(request.previous_receipt_sha256), decision, reason)
        self._receipts.append(receipt)
        return receipt

    def consume_commit(self, custody_id: str, input_sha256: str, archive_sha256: str,
                       commit_receipt_sha256: str):
        """Consume BEFORE ledger CAS; conflict cannot make this authorization reusable."""
        with self._lock:
            tx = self._transactions.get(custody_id)
            if tx is None or tx.consumed or tx.state != CustodyAction.CUSTODY_COMMIT:
                raise CustodyBlocked("CUSTODY_COMMIT_MISSING_OR_CONSUMED")
            if time.time() >= tx.expires_at:
                raise CustodyBlocked("CUSTODY_TRANSACTION_EXPIRED")
            if (input_sha256 != tx.input_sha256 or archive_sha256 != tx.archive_sha256
                or commit_receipt_sha256 != tx.last_receipt.sha256):
                raise CustodyBlocked("CUSTODY_COMMIT_BINDING_MISMATCH")
            tx.consumed = True


def custody_input_digest(policy, records) -> str:
    """Current policy + exact immutable raw AND linked digests, distinct from receipt."""
    return sha(b"npd.agent-hub.custody.writer-input.v1\0" + encoded({
        "policy": asdict(policy), "records": [
            {"source": row.source, "identifier": row.identifier, "raw_sha256": sha(row.raw),
             "links": [[k, sha(v)] for k, v in row.links]} for row in records]}))


def custody_archive_digest(receipts) -> str:
    return sha(b"npd.agent-hub.custody.archive-proof.v1\0" + encoded([asdict(r) for r in receipts]))


@dataclass(frozen=True)
class AuthenticatedCommitHook:
    authority: LocalCustodyAuthority
    custody_id: str
    commit_receipt_sha256: str

    def __call__(self, policy, records, archive_receipts):
        self.authority.consume_commit(self.custody_id, custody_input_digest(policy, records),
            custody_archive_digest(archive_receipts), self.commit_receipt_sha256)
