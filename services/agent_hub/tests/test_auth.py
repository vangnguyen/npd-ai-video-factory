from fastapi import HTTPException

from npd_agent_hub.auth import Role, StaticTokenAuthorizer
from npd_agent_hub.config import HubSettings


def auth_settings(**overrides):
    base = dict(
        auth_mode="static_token",
        viewer_token="viewer-secret",
        operator_token="operator-secret",
        owner_token="owner-secret",
    )
    base.update(overrides)
    return HubSettings(**base)


def test_static_tokens_resolve_roles():
    auth = StaticTokenAuthorizer(auth_settings())

    assert auth.authenticate("Bearer viewer-secret").role == Role.VIEWER
    assert auth.authenticate("Bearer operator-secret").role == Role.OPERATOR
    assert auth.authenticate("Bearer owner-secret").role == Role.OWNER


def test_viewer_cannot_use_operator_or_owner_capabilities():
    auth = StaticTokenAuthorizer(auth_settings())

    try:
        auth.require(Role.OPERATOR, "Bearer viewer-secret")
        assert False, "viewer must not satisfy operator role"
    except HTTPException as exc:
        assert exc.status_code == 403

    try:
        auth.require(Role.OWNER, "Bearer operator-secret")
        assert False, "operator must not satisfy owner role"
    except HTTPException as exc:
        assert exc.status_code == 403


def test_missing_or_invalid_token_is_unauthorized():
    auth = StaticTokenAuthorizer(auth_settings())

    for header in (None, "", "Basic abc", "Bearer wrong"):
        try:
            auth.authenticate(header)
            assert False, "invalid auth should fail"
        except HTTPException as exc:
            assert exc.status_code == 401


def test_static_auth_requires_owner_token_and_distinct_tokens():
    missing_owner = StaticTokenAuthorizer(auth_settings(owner_token=""))
    assert missing_owner.configuration_errors()

    duplicate = StaticTokenAuthorizer(auth_settings(owner_token="same", operator_token="same"))
    assert duplicate.configuration_errors()


def test_disabled_auth_is_explicit_owner_for_dev_only():
    auth = StaticTokenAuthorizer(HubSettings(auth_mode="disabled"))
    principal = auth.authenticate(None)
    assert principal.role == Role.OWNER
    assert principal.subject == "auth-disabled"
