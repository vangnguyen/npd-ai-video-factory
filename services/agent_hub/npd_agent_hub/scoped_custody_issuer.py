"""Public scoped-service trust contract. No issuer process or credential minting.

Public keys are controlled pins, never supplied by a token. The local store is
an explicitly synthetic acceptance backend; production trust fencing is unbound.
"""
from __future__ import annotations
from contextlib import contextmanager
from dataclasses import dataclass
import base64
import json
import re
from threading import RLock
import time
from typing import Protocol
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, load_pem_public_key
import jwt

from .custody_authority import ACTION_CAPABILITY, CustodyAction, exact_digest, exact_uuid
from .custody_identity import canonical, digest
from .retention_custody import CustodyBlocked

PROPOSED_ISSUER = "urn:npd:agent-hub:custody:phase9"  # Proposal, not a deployed issuer.
AUDIENCE = "npd-agent-hub-custody-p9"
TOKEN_TYPE = "npd-custody-service+jwt"
VERIFIER = "npd-agent-hub-custody-verifier-p9"
CUSTODIAN = "npd-agent-hub-custody-custodian-p9"
CAPABILITIES = {VERIFIER: frozenset({"custody.archive.verify"}),
                CUSTODIAN: frozenset({"custody.archive.write", "custody.commit"})}


@dataclass(frozen=True)
class PublicServiceKey:
    subject: str
    kid: str
    public_pem: bytes
    valid_from: int
    verify_until: int | None = None  # exclusive, previous keys only
    status: str = "active"
    overlap_from: int | None = None

    def public_key(self):
        try:
            key = load_pem_public_key(self.public_pem)
            if (self.subject not in CAPABILITIES or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", self.kid)
                or not isinstance(key, RSAPublicKey) or key.key_size < 2048
                or type(self.valid_from) is not int or self.valid_from <= 0
                or self.status not in {"active", "revoked"}
                or ((self.verify_until is None) != (self.overlap_from is None))
                or (self.verify_until is not None and (type(self.verify_until) is not int
                    or type(self.overlap_from) is not int or self.overlap_from < self.valid_from
                    or not self.overlap_from < self.verify_until <= self.overlap_from + 900))):
                raise ValueError()
            return key
        except (TypeError, ValueError) as error:
            raise CustodyBlocked("SCOPED_CUSTODY_PUBLIC_KEY_BINDING_INVALID_HOLD") from error

    @property
    def fingerprint(self):
        return digest(self.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo))


@dataclass(frozen=True)
class CustodyTrustBundle:
    issuer: str
    audience: str
    epoch: int
    keys: tuple[PublicServiceKey, ...]
    revoked_subjects: frozenset[str] = frozenset()
    revoked_jtis: frozenset[str] = frozenset()
    revoked_kids: frozenset[str] = frozenset()

    def __post_init__(self):
        if (self.issuer != PROPOSED_ISSUER or self.audience != AUDIENCE
            or type(self.epoch) is not int or self.epoch < 1 or type(self.keys) is not tuple
            or not isinstance(self.revoked_subjects, frozenset) or not self.revoked_subjects <= set(CAPABILITIES)
            or not isinstance(self.revoked_jtis, frozenset) or not isinstance(self.revoked_kids, frozenset)
            or any(not isinstance(kid, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", kid) for kid in self.revoked_kids)):
            raise CustodyBlocked("SCOPED_CUSTODY_TRUST_CONFIG_INVALID_HOLD")
        for token_id in self.revoked_jtis:
            exact_uuid(token_id)
        kids, fingerprints, current = set(), {}, set()
        for key in self.keys:
            if not isinstance(key, PublicServiceKey):
                raise CustodyBlocked("SCOPED_CUSTODY_TRUST_KEY_INVALID_HOLD")
            fingerprint = key.fingerprint
            if key.kid in kids or fingerprint in fingerprints:
                raise CustodyBlocked("SHARED_CUSTODY_CREDENTIAL_FORBIDDEN")
            kids.add(key.kid)
            fingerprints[fingerprint] = key.subject
            if key.verify_until is None:
                if key.subject in current:
                    raise CustodyBlocked("AMBIGUOUS_ACTIVE_CUSTODY_KEY_HOLD")
                current.add(key.subject)
        if current != set(CAPABILITIES) or len(self.keys) > 4:
            raise CustodyBlocked("TWO_INDEPENDENT_SERVICE_KEY_BINDINGS_REQUIRED")

    @property
    def binding_sha256(self):
        return digest(b"npd.agent-hub.custody.scoped-trust.v2\0" + canonical({
            "issuer": self.issuer, "audience": self.audience, "epoch": self.epoch,
            "token_type": TOKEN_TYPE, "max_token_seconds": 900,
            "keys": [{"subject": k.subject, "kid": k.kid, "fingerprint": k.fingerprint,
                "capabilities": sorted(CAPABILITIES[k.subject]), "status": k.status,
                "valid_from": k.valid_from, "overlap_from": k.overlap_from, "verify_until": k.verify_until}
                for k in sorted(self.keys, key=lambda k: k.kid)],
            "revoked_subjects": sorted(self.revoked_subjects), "revoked_jtis": sorted(self.revoked_jtis),
            "revoked_kids": sorted(self.revoked_kids)}))

    def public_document(self):
        """Public JWKS plus subject pins; never a private/credential export."""
        keys = []
        for key in sorted(self.keys, key=lambda k: k.kid):
            exported = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
            jwk = {name: exported[name] for name in ("kty", "n", "e")}
            jwk.update(kid=key.kid, alg="RS256", use="sig")
            keys.append({"subject": key.subject, "capabilities": sorted(CAPABILITIES[key.subject]),
                "jwk": jwk, "fingerprint": key.fingerprint, "status": key.status,
                "valid_from": key.valid_from, "overlap_from": key.overlap_from, "verify_until": key.verify_until})
        return {"schema": "npd.agent-hub.custody.scoped-public-trust.v2", "issuer": self.issuer,
            "audience": self.audience, "epoch": self.epoch, "token_type": TOKEN_TYPE, "keys": keys,
            "revoked_subjects": sorted(self.revoked_subjects), "revoked_kids": sorted(self.revoked_kids),
            "revoked_jtis": sorted(self.revoked_jtis)}

    @classmethod
    def from_public_bytes(cls, raw, *, expected_sha256):
        # A separately controlled manifest pins exact bytes before configuration.
        try:
            from .authority_journal import strict_json
            if type(raw) is not bytes or digest(raw) != exact_digest(expected_sha256):
                raise ValueError()
            value = strict_json(raw)
            if (set(value) != {"schema", "issuer", "audience", "epoch", "token_type", "keys",
                              "revoked_subjects", "revoked_kids", "revoked_jtis"}
                or value["schema"] != "npd.agent-hub.custody.scoped-public-trust.v2"
                or value["token_type"] != TOKEN_TYPE or type(value["keys"]) is not list):
                raise ValueError()
            keys = []
            for row in value["keys"]:
                jwk = row["jwk"]
                if (set(row) != {"subject", "capabilities", "jwk", "fingerprint", "status",
                    "valid_from", "overlap_from", "verify_until"}
                    or set(jwk) != {"kty", "n", "e", "kid", "alg", "use"}
                    or jwk["kty"] != "RSA" or jwk["alg"] != "RS256" or jwk["use"] != "sig"
                    or row["capabilities"] != sorted(CAPABILITIES[row["subject"]])):
                    raise ValueError()
                public = jwt.algorithms.RSAAlgorithm.from_jwk(jwk)
                key = PublicServiceKey(row["subject"], jwk["kid"], public.public_bytes(
                    Encoding.PEM, PublicFormat.SubjectPublicKeyInfo), row["valid_from"],
                    row["verify_until"], row["status"], row["overlap_from"])
                if key.fingerprint != row["fingerprint"]:
                    raise ValueError()
                keys.append(key)
            result = cls(value["issuer"], value["audience"], value["epoch"], tuple(keys),
                frozenset(value["revoked_subjects"]), frozenset(value["revoked_jtis"]), frozenset(value["revoked_kids"]))
            if canonical(result.public_document()) != raw:
                raise ValueError()
            return result
        except (ValueError, TypeError, KeyError, AttributeError, jwt.PyJWTError) as error:
            raise CustodyBlocked("SCOPED_PUBLIC_TRUST_MANIFEST_OR_DIGEST_INVALID_HOLD") from error


class CustodyTrustStore(Protocol):
    def snapshot(self) -> CustodyTrustBundle: ...
    def fence(self, expected_sha256: str): ...


class LocalFixtureTrustStore:
    """Create-only initial public bundle, CAS epoch updates, local fencing only."""
    synthetic_local_only = True

    def __init__(self, bundle, *, production_mode=False):
        if production_mode or not isinstance(bundle, CustodyTrustBundle):
            raise CustodyBlocked("PRODUCTION_CUSTODY_TRUST_STORE_NOT_ACCEPTED_HOLD")
        self._bundle = bundle
        self._lock = RLock()
        self.unavailable = False

    def snapshot(self):
        with self._lock:
            if self.unavailable or not isinstance(self._bundle, CustodyTrustBundle):
                raise CustodyBlocked("CUSTODY_TRUST_UNAVAILABLE_OR_UNKNOWN_HOLD")
            return self._bundle

    def replace_fixture(self, bundle, *, expected_sha256):
        with self._lock:
            old = self.snapshot()
            if (old.binding_sha256 != expected_sha256 or not isinstance(bundle, CustodyTrustBundle)
                or bundle.epoch != old.epoch + 1
                or not old.revoked_subjects <= bundle.revoked_subjects
                or not old.revoked_jtis <= bundle.revoked_jtis
                or not old.revoked_kids <= bundle.revoked_kids
                or any(k.status == "revoked" and k.kid not in bundle.revoked_kids and not any(
                    n.kid == k.kid and n.status == "revoked" and n.fingerprint == k.fingerprint for n in bundle.keys) for k in old.keys)
                or any(n.kid == k.kid and (n.subject != k.subject or n.fingerprint != k.fingerprint)
                       for n in bundle.keys for k in old.keys)):
                raise CustodyBlocked("CUSTODY_TRUST_CAS_OR_REVOCATION_ROLLBACK_HOLD_NO_RETRY")
            self._bundle = bundle

    @contextmanager
    def fence(self, expected_sha256):
        with self._lock:
            if self.snapshot().binding_sha256 != expected_sha256:
                raise CustodyBlocked("CUSTODY_TRUST_CHANGED_HOLD_NO_RETRY")
            yield self.snapshot()
            if self.snapshot().binding_sha256 != expected_sha256:
                raise CustodyBlocked("CUSTODY_TRUST_CHANGED_HOLD_NO_RETRY")


@dataclass(frozen=True)
class VerifiedServiceActor:
    issuer: str
    subject: str
    capability: str
    kid: str
    fingerprint: str
    epoch: int
    token_id: str
    payload_sha256: str
    expires_at: int


def _unique_json_segment(segment):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON claim")
            value[key] = item
        return value
    raw = base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
    return json.loads(raw.decode("utf8", errors="strict"), object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))


def verify_service_token(authorization, request, bundle):
    """Real RS256 verification; signed claims and exact actor key are mandatory."""
    if request.action == CustodyAction.HOLD_RELEASE:
        raise CustodyBlocked("HOLD_RELEASE_DEFERRED")
    exact_uuid(request.custody_id)
    exact_digest(request.input_sha256)
    exact_digest(request.result_sha256)
    if request.previous_receipt_sha256 is not None:
        exact_digest(request.previous_receipt_sha256)
    if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
        raise CustodyBlocked("SCOPED_SERVICE_CREDENTIAL_REQUIRED")
    token = authorization[7:]
    try:
        if not token or token != token.strip() or len(token) > 8192:
            raise ValueError()
        segments = token.split(".")
        if len(segments) != 3:
            raise ValueError()
        header = _unique_json_segment(segments[0])
        _unique_json_segment(segments[1])
        if set(header) != {"alg", "kid", "typ"} or header["alg"] != "RS256" or header["typ"] != TOKEN_TYPE:
            raise ValueError()
        key = next(k for k in bundle.keys if k.kid == header["kid"])
        now = int(time.time())
        if (key.status != "active" or key.kid in bundle.revoked_kids or now < key.valid_from
            or (key.verify_until is not None and now >= key.verify_until)):
            raise ValueError()
        claims = jwt.decode(token, key.public_key(), algorithms=["RS256"],
            issuer=bundle.issuer, audience=bundle.audience, options={"require": [
                "iss", "aud", "sub", "iat", "nbf", "exp", "jti", "capabilities", "trust_epoch"]})
        required = {"iss", "aud", "sub", "iat", "nbf", "exp", "jti", "capabilities", "trust_epoch",
                    "custody_id", "action", "input_sha256", "result_sha256", "previous_receipt_sha256"}
        capability = ACTION_CAPABILITY[request.action].value
        if (set(claims) != required or claims["aud"] != bundle.audience or claims["sub"] != key.subject
            or key.subject in bundle.revoked_subjects or claims["jti"] in bundle.revoked_jtis
            or any(type(claims[k]) is not int for k in ("iat", "nbf", "exp", "trust_epoch"))
            or claims["trust_epoch"] != bundle.epoch
            or not 0 < claims["iat"] <= claims["nbf"] <= now < claims["exp"]
            or not 0 < claims["exp"] - claims["iat"] <= 900
            or claims["iat"] < key.valid_from
            or (key.overlap_from is not None and claims["iat"] >= key.overlap_from)
            or claims["capabilities"] != [capability] or capability not in CAPABILITIES[key.subject]
            or any(claims[k] != v for k, v in {
                "custody_id": request.custody_id, "action": request.action.value,
                "input_sha256": request.input_sha256, "result_sha256": request.result_sha256,
                "previous_receipt_sha256": request.previous_receipt_sha256}.items())):
            raise ValueError()
        exact_uuid(claims["jti"])
    except (ValueError, TypeError, KeyError, StopIteration, UnicodeError, jwt.PyJWTError) as error:
        raise CustodyBlocked("SCOPED_CUSTODY_TOKEN_INVALID_OR_UNAUTHORIZED") from error
    return VerifiedServiceActor(bundle.issuer, key.subject, capability, key.kid, key.fingerprint,
        bundle.epoch, claims["jti"], digest(canonical(claims)),
        min(claims["exp"], key.verify_until) if key.verify_until is not None else claims["exp"])
