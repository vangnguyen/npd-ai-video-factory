import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.testclient import TestClient

from npd_agent_hub.auth import authorizer
from npd_agent_hub.config import HubSettings
from npd_agent_hub.main import app
import npd_agent_hub.google_login as google_login


def oidc_settings() -> HubSettings:
    return HubSettings(
        auth_mode="static_token",
        viewer_token="viewer-secret",
        operator_token="operator-secret",
        owner_token="owner-secret",
        browser_auth_mode="google_oidc",
        public_base_url="https://mkt.ngocphuongdong.com",
        google_client_id="google-client-id",
        google_client_secret="google-client-secret",
        session_signing_key="session-key-" * 4,
        owner_emails=("nguyenvanvangct@gmail.com",),
    )


def test_google_login_creates_owner_session_and_command_center_access(monkeypatch):
    previous = authorizer.settings
    authorizer.settings = oidc_settings()
    client = TestClient(app, base_url="https://mkt.ngocphuongdong.com")
    monkeypatch.setattr(
        google_login,
        "exchange_google_code",
        lambda code, settings, nonce: "nguyenvanvangct@gmail.com",
    )
    try:
        command_center = client.get("/command-center", follow_redirects=False)
        assert command_center.status_code == 303
        assert command_center.headers["location"] == "/login"

        start = client.get("/auth/google/login", follow_redirects=False)
        assert start.status_code == 302
        query = parse_qs(urlparse(start.headers["location"]).query)
        assert query["client_id"] == ["google-client-id"]
        assert query["redirect_uri"] == [
            "https://mkt.ngocphuongdong.com/auth/google/callback"
        ]

        callback = client.get(
            "/auth/google/callback",
            params={"code": "authorization-code", "state": query["state"][0]},
            follow_redirects=False,
        )
        assert callback.status_code == 303
        assert callback.headers["location"] == "/command-center"

        whoami = client.get("/api/v1/whoami")
        assert whoami.status_code == 200
        assert whoami.json() == {
            "role": "owner",
            "subject": "nguyenvanvangct@gmail.com",
        }
        page = client.get("/command-center")
        assert page.status_code == 200
        assert "Đăng xuất" in page.text
        assert "Bearer token" not in page.text

        rejected = client.post(
            "/api/v1/agent-tasks",
            json={"objective": "Kiểm tra CRM và lead"},
        )
        assert rejected.status_code == 403
        accepted = client.post(
            "/api/v1/agent-tasks",
            headers={"Origin": "https://mkt.ngocphuongdong.com"},
            json={"objective": "Kiểm tra CRM và lead"},
        )
        assert accepted.status_code == 200
    finally:
        authorizer.settings = previous


def test_google_login_rejects_non_allowlisted_email(monkeypatch):
    previous = authorizer.settings
    authorizer.settings = oidc_settings()
    client = TestClient(app, base_url="https://mkt.ngocphuongdong.com")
    monkeypatch.setattr(
        google_login,
        "exchange_google_code",
        lambda code, settings, nonce: "intruder@example.com",
    )
    try:
        start = client.get("/auth/google/login", follow_redirects=False)
        state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
        callback = client.get(
            "/auth/google/callback",
            params={"code": "authorization-code", "state": state},
            follow_redirects=False,
        )
        assert callback.status_code == 403
        assert client.get("/api/v1/whoami").status_code == 401
    finally:
        authorizer.settings = previous


def test_google_id_token_requires_verified_email_and_matching_nonce(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(
        google_login.jwt,
        "PyJWKClient",
        lambda url: SimpleNamespace(
            get_signing_key_from_jwt=lambda token: SimpleNamespace(key=private_key.public_key())
        ),
    )
    now = int(time.time())

    def token(**overrides):
        claims = {
            "iss": "https://accounts.google.com",
            "aud": "google-client-id",
            "iat": now,
            "exp": now + 300,
            "email": "nguyenvanvangct@gmail.com",
            "email_verified": True,
            "nonce": "expected-nonce",
        }
        claims.update(overrides)
        return jwt.encode(claims, private_key, algorithm="RS256")

    settings = oidc_settings()
    assert google_login.verify_google_id_token(
        token(), settings, "expected-nonce"
    ) == "nguyenvanvangct@gmail.com"

    for invalid in (
        token(email_verified=False),
        token(nonce="wrong-nonce"),
        token(iss="https://example.com"),
    ):
        try:
            google_login.verify_google_id_token(invalid, settings, "expected-nonce")
            assert False, "invalid Google identity claims must be rejected"
        except HTTPException as exc:
            assert exc.status_code == 401
