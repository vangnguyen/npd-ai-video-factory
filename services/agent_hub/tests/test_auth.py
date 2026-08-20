from fastapi import HTTPException
from fastapi.testclient import TestClient

from npd_agent_hub.auth import Role, StaticTokenAuthorizer, authorizer
from npd_agent_hub.config import HubSettings
from npd_agent_hub.main import app


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


def test_google_session_maps_allowlisted_email_to_owner_and_enforces_origin():
    settings = auth_settings(
        browser_auth_mode="google_oidc",
        public_base_url="https://mkt.ngocphuongdong.com",
        google_client_id="client-id",
        google_client_secret="client-secret",
        session_signing_key="s" * 48,
        owner_emails=("nguyenvanvangct@gmail.com",),
    )
    auth = StaticTokenAuthorizer(settings)
    session = auth.create_session("nguyenvanvangct@gmail.com", Role.OWNER, now=2_000_000_000)

    principal = auth.authenticate_session(session)
    assert principal.role == Role.OWNER
    assert principal.subject == "nguyenvanvangct@gmail.com"
    assert principal.auth_method == "session"

    try:
        auth.require(Role.OWNER, None, session, method="POST", origin=None)
        assert False, "cookie-authenticated writes must require the configured origin"
    except HTTPException as exc:
        assert exc.status_code == 403

    assert auth.require(
        Role.OWNER,
        None,
        session,
        method="POST",
        origin="https://mkt.ngocphuongdong.com",
    ).role == Role.OWNER


def test_google_session_is_revoked_when_email_leaves_allowlist():
    enabled = auth_settings(
        browser_auth_mode="google_oidc",
        public_base_url="https://mkt.ngocphuongdong.com",
        google_client_id="client-id",
        google_client_secret="client-secret",
        session_signing_key="s" * 48,
        owner_emails=("nguyenvanvangct@gmail.com",),
    )
    session = StaticTokenAuthorizer(enabled).create_session(
        "nguyenvanvangct@gmail.com", Role.OWNER, now=2_000_000_000
    )
    revoked = StaticTokenAuthorizer(HubSettings(**{**enabled.__dict__, "owner_emails": ("other@example.com",)}))
    try:
        revoked.authenticate_session(session)
        assert False, "email allowlist removal must revoke existing sessions"
    except HTTPException as exc:
        assert exc.status_code == 403


def test_google_login_configuration_is_fail_closed():
    auth = StaticTokenAuthorizer(auth_settings(browser_auth_mode="google_oidc"))
    errors = auth.configuration_errors()
    assert any("AGENT_GOOGLE_CLIENT_ID" in error for error in errors)
    assert any("AGENT_OWNER_EMAILS" in error for error in errors)


def test_http_rbac_enforces_viewer_operator_owner_boundaries():
    previous = authorizer.settings
    authorizer.settings = auth_settings()
    client = TestClient(app)
    try:
        assert client.get("/api/v1/command-center").status_code == 401

        viewer_headers = {"Authorization": "Bearer viewer-secret"}
        operator_headers = {"Authorization": "Bearer operator-secret"}
        owner_headers = {"Authorization": "Bearer owner-secret"}

        assert client.get("/api/v1/whoami", headers=viewer_headers).json()["role"] == "viewer"
        assert client.get("/api/v1/command-center", headers=viewer_headers).status_code == 200
        assert client.post(
            "/api/v1/agent-tasks",
            headers=viewer_headers,
            json={"objective": "Kiểm tra CRM và lead"},
        ).status_code == 403

        created = client.post(
            "/api/v1/agent-tasks",
            headers=operator_headers,
            json={"objective": "Quản lý công việc toàn bộ hệ thống"},
        )
        assert created.status_code == 200
        report = created.json()
        pending = report["approvals_required"][0]
        decision_url = (
            f"/api/v1/agent-tasks/{report['task_id']}"
            f"/actions/{pending['action_id']}/decision"
        )
        assert client.post(
            decision_url,
            headers=operator_headers,
            json={"approved": True},
        ).status_code == 403
        assert client.post(
            decision_url,
            headers=owner_headers,
            json={"approved": True},
        ).status_code == 200
    finally:
        authorizer.settings = previous
