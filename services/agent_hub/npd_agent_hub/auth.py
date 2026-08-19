from __future__ import annotations

import hmac
from dataclasses import dataclass
from enum import IntEnum
from typing import Annotated, Callable

from fastapi import Header, HTTPException, status

from .config import HubSettings, settings as default_settings


class Role(IntEnum):
    VIEWER = 10
    OPERATOR = 20
    OWNER = 30


@dataclass(frozen=True)
class Principal:
    role: Role
    subject: str


class StaticTokenAuthorizer:
    """Small self-hosted RBAC boundary for the Agent Hub.

    Tokens are supplied only through environment variables. They are never
    persisted in Agent Hub storage or audit metadata.
    """

    def __init__(self, settings: HubSettings | None = None) -> None:
        self.settings = settings or default_settings

    def configuration_errors(self) -> list[str]:
        if self.settings.auth_mode == "disabled":
            return []
        if self.settings.auth_mode != "static_token":
            return [f"unsupported AGENT_AUTH_MODE={self.settings.auth_mode}"]
        if not self.settings.owner_token:
            return ["AGENT_OWNER_TOKEN is required when static-token auth is enabled"]
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
            return ["Agent Hub role tokens must be distinct"]
        return []

    def authenticate(self, authorization: str | None) -> Principal:
        if self.settings.auth_mode == "disabled":
            return Principal(role=Role.OWNER, subject="auth-disabled")

        errors = self.configuration_errors()
        if errors:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="agent hub authentication is not configured",
            )

        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="bearer token required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        supplied = authorization[7:].strip()
        if not supplied:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="bearer token required",
                headers={"WWW-Authenticate": "Bearer"},
            )

        candidates = (
            (self.settings.owner_token, Role.OWNER, "owner"),
            (self.settings.operator_token, Role.OPERATOR, "operator"),
            (self.settings.viewer_token, Role.VIEWER, "viewer"),
        )
        for expected, role, subject in candidates:
            if expected and hmac.compare_digest(supplied, expected):
                return Principal(role=role, subject=subject)

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    def require(self, minimum_role: Role, authorization: str | None) -> Principal:
        principal = self.authenticate(authorization)
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
) -> Callable[[str | None], Principal]:
    auth = authorizer or StaticTokenAuthorizer()

    def dependency(
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    ) -> Principal:
        return auth.require(minimum_role, authorization)

    return dependency


authorizer = StaticTokenAuthorizer()
require_viewer = role_dependency(Role.VIEWER, authorizer=authorizer)
require_operator = role_dependency(Role.OPERATOR, authorizer=authorizer)
require_owner = role_dependency(Role.OWNER, authorizer=authorizer)
