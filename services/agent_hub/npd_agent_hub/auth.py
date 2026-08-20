from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from enum import IntEnum
from typing import Annotated, Callable
from urllib.parse import urlparse

from fastapi import Header, HTTPException, Request, status

from .config import HubSettings, settings as default_settings


SESSION_COOKIE = "npd_agent_session"
OAUTH_STATE_COOKIE = "npd_agent_oauth_state"


class Role(IntEnum):
    VIEWER = 10
    OPERATOR = 20
    OWNER = 30


@dataclass(frozen=True)
class Principal:
    role: Role
    subject: str
    auth_method: str = "bearer"


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class StaticTokenAuthorizer:
    """RBAC boundary supporting automation tokens and optional Google sessions."""

    def __init__(self, settings: HubSettings | None = None) -> None:
        self.settings = settings or default_settings

    @property
    def browser_login_enabled(self) -> bool:
        return self.settings.browser_auth_mode == "google_oidc"

    def configuration_errors(self) -> list[str]:
        errors: list[str] = []
        if self.settings.auth_mode not in ("disabled", "static_token"):
            errors.append(f"unsupported AGENT_AUTH_MODE={self.settings.auth_mode}")
        elif self.settings.auth_mode == "static_token":
            if not self.settings.owner_token:
                errors.append("AGENT_OWNER_TOKEN is required when static-token auth is enabled")
            configured = [
                token
                for token in (
                    self.settings.viewer_token,
                    self.settings.operator_token,
                    self.settings.owner_token,
                )
                if token
            ]
            if len(set(configured)) != len(configured):
                errors.append("Agent Hub role tokens must be distinct")

        if self.settings.browser_auth_mode not in ("disabled", "google_oidc"):
            errors.append(
                f"unsupported AGENT_BROWSER_AUTH_MODE={self.settings.browser_auth_mode}"
            )
        elif self.browser_login_enabled:
            required = {
                "AGENT_PUBLIC_BASE_URL": self.settings.public_base_url,
                "AGENT_GOOGLE_CLIENT_ID": self.settings.google_client_id,
                "AGENT_GOOGLE_CLIENT_SECRET": self.settings.google_client_secret,
                "AGENT_SESSION_SIGNING_KEY": self.settings.session_signing_key,
                "AGENT_OWNER_EMAILS": self.settings.owner_emails,
            }
            errors.extend(
                f"{name} is required for Google login"
                for name, value in required.items()
                if not value
            )
            parsed = urlparse(self.settings.public_base_url)
            if self.settings.public_base_url and (
                parsed.scheme != "https" or not parsed.netloc or parsed.path not in ("", "/")
            ):
                errors.append("AGENT_PUBLIC_BASE_URL must be an HTTPS origin without a path")
            if self.settings.session_signing_key and len(self.settings.session_signing_key) < 32:
                errors.append("AGENT_SESSION_SIGNING_KEY must be at least 32 characters")
            if self.settings.session_ttl_seconds < 300:
                errors.append("AGENT_SESSION_TTL_SECONDS must be at least 300")

            email_roles: dict[str, str] = {}
            for role_name, emails in (
                ("owner", self.settings.owner_emails),
                ("operator", self.settings.operator_emails),
                ("viewer", self.settings.viewer_emails),
            ):
                for email in emails:
                    if "@" not in email or email != email.strip().lower():
                        errors.append(f"invalid {role_name} email allowlist entry")
                    previous = email_roles.setdefault(email, role_name)
                    if previous != role_name:
                        errors.append(f"email appears in multiple role allowlists: {email}")
        return errors

    def role_for_email(self, email: str) -> Role | None:
        normalized = email.strip().lower()
        if normalized in self.settings.owner_emails:
            return Role.OWNER
        if normalized in self.settings.operator_emails:
            return Role.OPERATOR
        if normalized in self.settings.viewer_emails:
            return Role.VIEWER
        return None

    def sign_payload(self, payload: dict[str, object]) -> str:
        body = _b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
        signature = hmac.new(
            self.settings.session_signing_key.encode(), body.encode(), hashlib.sha256
        ).digest()
        return f"{body}.{_b64encode(signature)}"

    def verify_payload(self, token: str) -> dict[str, object]:
        try:
            body, supplied_signature = token.split(".", 1)
            expected_signature = hmac.new(
                self.settings.session_signing_key.encode(), body.encode(), hashlib.sha256
            ).digest()
            if not hmac.compare_digest(_b64decode(supplied_signature), expected_signature):
                raise ValueError("signature mismatch")
            payload = json.loads(_b64decode(body))
            if not isinstance(payload, dict) or int(payload.get("exp", 0)) < int(time.time()):
                raise ValueError("expired payload")
            return payload
        except (
            ValueError,
            TypeError,
            binascii.Error,
            json.JSONDecodeError,
            UnicodeDecodeError,
        ) as exc:
            raise HTTPException(status_code=401, detail="invalid or expired session") from exc

    def create_session(self, email: str, role: Role, *, now: int | None = None) -> str:
        issued_at = int(time.time()) if now is None else now
        return self.sign_payload(
            {
                "typ": "session",
                "sub": email.strip().lower(),
                "role": role.name.lower(),
                "iat": issued_at,
                "exp": issued_at + self.settings.session_ttl_seconds,
            }
        )

    def authenticate_session(self, session_cookie: str) -> Principal:
        if not self.browser_login_enabled:
            raise HTTPException(status_code=401, detail="browser login is disabled")
        payload = self.verify_payload(session_cookie)
        if payload.get("typ") != "session":
            raise HTTPException(status_code=401, detail="invalid or expired session")
        email = str(payload.get("sub", "")).strip().lower()
        allowed_role = self.role_for_email(email)
        if allowed_role is None or payload.get("role") != allowed_role.name.lower():
            raise HTTPException(status_code=403, detail="account is not authorized")
        return Principal(role=allowed_role, subject=email, auth_method="session")

    def authenticate(
        self,
        authorization: str | None,
        session_cookie: str | None = None,
    ) -> Principal:
        if self.settings.auth_mode == "disabled" and not self.browser_login_enabled:
            return Principal(role=Role.OWNER, subject="auth-disabled", auth_method="disabled")

        if self.configuration_errors():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="agent hub authentication is not configured",
            )

        if authorization:
            if not authorization.startswith("Bearer "):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="bearer token required",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            supplied = authorization[7:].strip()
            candidates = (
                (self.settings.owner_token, Role.OWNER, "owner"),
                (self.settings.operator_token, Role.OPERATOR, "operator"),
                (self.settings.viewer_token, Role.VIEWER, "viewer"),
            )
            for expected, role, subject in candidates:
                if expected and supplied and hmac.compare_digest(supplied, expected):
                    return Principal(role=role, subject=subject, auth_method="bearer")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if session_cookie:
            return self.authenticate_session(session_cookie)

        detail = "login required" if self.browser_login_enabled else "bearer token required"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )

    def require(
        self,
        minimum_role: Role,
        authorization: str | None,
        session_cookie: str | None = None,
        *,
        method: str = "GET",
        origin: str | None = None,
    ) -> Principal:
        principal = self.authenticate(authorization, session_cookie)
        if principal.auth_method == "session" and method.upper() not in {"GET", "HEAD", "OPTIONS"}:
            if origin != self.settings.public_base_url:
                raise HTTPException(status_code=403, detail="same-origin request required")
        if principal.role < minimum_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="insufficient role",
            )
        return principal


def role_dependency(
    minimum_role: Role,
    *,
    authorizer: StaticTokenAuthorizer | None = None,
) -> Callable[..., Principal]:
    auth = authorizer or StaticTokenAuthorizer()

    def dependency(
        request: Request,
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    ) -> Principal:
        return auth.require(
            minimum_role,
            authorization,
            request.cookies.get(SESSION_COOKIE),
            method=request.method,
            origin=request.headers.get("Origin"),
        )

    return dependency


authorizer = StaticTokenAuthorizer()
require_viewer = role_dependency(Role.VIEWER, authorizer=authorizer)
require_operator = role_dependency(Role.OPERATOR, authorizer=authorizer)
require_owner = role_dependency(Role.OWNER, authorizer=authorizer)
