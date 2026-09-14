"""Stable origin identity retained by verified login, never by email or role.

The trusted Owner pin is separate from the current business email allowlist.
Nothing here enrolls a subject, issues credentials or mounts a custody endpoint.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
import re
from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from .retention_custody import CustodyBlocked

GOOGLE_ISSUER = "https://accounts.google.com"
ORIGIN_DOMAIN = b"npd.agent-hub.custody.origin-principal.v1\0"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(",", ":")).encode("utf8", errors="strict")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def origin_principal(issuer: str, subject: str) -> str:
    if issuer != GOOGLE_ISSUER or not isinstance(subject, str) or not re.fullmatch(r"[\x21-\x7e]{1,255}", subject):
        raise CustodyBlocked("CUSTODY_ORIGIN_ISSUER_SUBJECT_INVALID_HOLD")
    return "pid:" + digest(ORIGIN_DOMAIN + canonical({"issuer": issuer, "subject": subject}))


class StableGoogleContext(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    version: int = 1
    issuer: str
    subject: str
    principal_id: str
    audience: str
    algorithm: str
    kid: str
    public_key_sha256: str
    verified_claims_sha256: str
    verified_at: int
    issued_at: int
    expires_at: int

    @field_validator("public_key_sha256", "verified_claims_sha256")
    @classmethod
    def exact_digest(cls, value):
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("invalid digest")
        return value

    @model_validator(mode="after")
    def validate_binding(self):
        if (self.version != 1 or self.algorithm != "RS256" or not self.audience
            or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", self.kid)
            or self.principal_id != origin_principal(self.issuer, self.subject)
            or not 0 < self.issued_at <= self.verified_at + 30 < self.expires_at + 30):
            raise ValueError("invalid stable context")
        return self


@dataclass(frozen=True)
class VerifiedGoogleIdentity:
    email: str
    stable_context: StableGoogleContext | None


@dataclass(frozen=True)
class OwnerOriginPin:
    """Trusted enrollment configuration, not a request body or display identity."""
    issuer: str
    subject: str
    audience: str

    def __post_init__(self):
        origin_principal(self.issuer, self.subject)
        if not self.audience:
            raise CustodyBlocked("CUSTODY_OWNER_AUDIENCE_UNBOUND_HOLD")

    @property
    def binding(self):
        return {"issuer": self.issuer, "subject": self.subject, "audience": self.audience,
                "principal_id": origin_principal(self.issuer, self.subject)}

    def accepts(self, context):
        return (isinstance(context, StableGoogleContext)
                and context.issuer == self.issuer and context.subject == self.subject
                and context.audience == self.audience)
