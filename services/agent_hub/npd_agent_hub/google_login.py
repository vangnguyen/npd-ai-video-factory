from __future__ import annotations

import html
import secrets
import time
from urllib.parse import urlencode

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi import HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from .auth import OAUTH_STATE_COOKIE, SESSION_COOKIE, StaticTokenAuthorizer
from .config import HubSettings
from .custody_identity import (GOOGLE_ISSUER, StableGoogleContext, VerifiedGoogleIdentity,
                              canonical, digest, origin_principal)


GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_ENDPOINT = "https://www.googleapis.com/oauth2/v3/certs"


def login_page(*, enabled: bool, error: str = "") -> HTMLResponse:
    problem = f'<p class="error">{html.escape(error)}</p>' if error else ""
    action = (
        '<a class="button" href="/auth/google/login">Đăng nhập bằng Google</a>'
        if enabled
        else '<p class="error">Đăng nhập Google chưa được cấu hình.</p>'
    )
    content = f"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Đăng nhập · NPD AI Command Center</title>
<style>:root{{font-family:Inter,system-ui,sans-serif;color:#172033;background:#f5f7fb}}body{{margin:0;min-height:100vh;display:grid;place-items:center;padding:20px}}main{{width:min(430px,100%);background:#fff;border:1px solid #e5e7eb;border-radius:16px;padding:32px;box-shadow:0 16px 45px #10182814}}h1{{font-size:24px;margin:0 0 10px}}p{{color:#667085;line-height:1.55}}.button{{display:block;text-align:center;text-decoration:none;background:#2563eb;color:#fff;padding:12px 16px;border-radius:9px;font-weight:650;margin-top:24px}}.error{{color:#b42318;background:#fef3f2;padding:10px 12px;border-radius:8px}}</style></head>
<body><main><h1>NPD AI Command Center</h1><p>Đăng nhập bằng tài khoản Google đã được cấp quyền để tiếp tục.</p>{problem}{action}</main></body></html>"""
    return HTMLResponse(
        content,
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'",
        },
    )


def begin_google_login(authorizer: StaticTokenAuthorizer) -> RedirectResponse:
    if not authorizer.browser_login_enabled or authorizer.configuration_errors():
        raise HTTPException(status_code=503, detail="Google login is not configured")
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    state_cookie = authorizer.sign_payload(
        {
            "typ": "oauth_state",
            "state": state,
            "nonce": nonce,
            "exp": int(time.time()) + 600,
        }
    )
    settings = authorizer.settings
    query = urlencode(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": f"{settings.public_base_url}/auth/google/callback",
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "prompt": "select_account",
        }
    )
    response = RedirectResponse(f"{GOOGLE_AUTHORIZATION_ENDPOINT}?{query}", status_code=302)
    response.set_cookie(
        OAUTH_STATE_COOKIE,
        state_cookie,
        max_age=600,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/auth/google",
    )
    return response


def verify_google_identity(id_token: str, settings: HubSettings, nonce: str) -> VerifiedGoogleIdentity:
    try:
        signing_key = jwt.PyJWKClient(GOOGLE_JWKS_ENDPOINT).get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.google_client_id,
            leeway=30,
            options={
                "require": ["exp", "iat", "aud", "iss", "email", "email_verified", "nonce"]
            },
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Google identity verification failed") from exc
    if claims.get("iss") not in {"https://accounts.google.com", "accounts.google.com"}:
        raise HTTPException(status_code=401, detail="Google identity verification failed")
    email_verified = claims.get("email_verified") is True or claims.get("email_verified") == "true"
    if not email_verified or not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise HTTPException(status_code=401, detail="Google identity verification failed")
    email = str(claims.get("email", "")).strip().lower()
    if not email:
        raise HTTPException(status_code=401, detail="Google identity verification failed")
    stable = None
    # Legacy business sessions work; missing sub never confers custody authority.
    if "sub" in claims:
        try:
            header = jwt.get_unverified_header(id_token)
            key = signing_key.key
            if not isinstance(key, RSAPublicKey) or key.key_size < 2048:
                raise ValueError("weak key")
            stable = StableGoogleContext(
                issuer=GOOGLE_ISSUER, subject=claims["sub"],
                principal_id=origin_principal(GOOGLE_ISSUER, claims["sub"]),
                audience=claims["aud"], algorithm="RS256", kid=header["kid"],
                public_key_sha256=digest(key.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)),
                verified_claims_sha256=digest(canonical(claims)), verified_at=int(time.time()),
                issued_at=claims["iat"], expires_at=claims["exp"])
        except (ValueError, TypeError, KeyError) as exc:
            raise HTTPException(status_code=401, detail="Google stable identity verification failed") from exc
    return VerifiedGoogleIdentity(email, stable)


def verify_google_id_token(id_token: str, settings: HubSettings, nonce: str) -> str:
    """Backward-compatible email projection; callback uses complete identity."""
    return verify_google_identity(id_token, settings, nonce).email


def exchange_google_code(code: str, settings: HubSettings, nonce: str) -> VerifiedGoogleIdentity:
    try:
        response = httpx.post(
            GOOGLE_TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": f"{settings.public_base_url}/auth/google/callback",
                "grant_type": "authorization_code",
            },
            timeout=15,
        )
        response.raise_for_status()
        id_token = response.json().get("id_token", "")
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Google login could not be completed") from exc
    if not id_token:
        raise HTTPException(status_code=502, detail="Google login did not return an identity")
    return verify_google_identity(id_token, settings, nonce)


def complete_google_login(
    authorizer: StaticTokenAuthorizer,
    *,
    code: str,
    state: str,
    state_cookie: str,
) -> RedirectResponse:
    payload = authorizer.verify_payload(state_cookie)
    if payload.get("typ") != "oauth_state" or not secrets.compare_digest(
        str(payload.get("state", "")), state
    ):
        raise HTTPException(status_code=401, detail="invalid login state")
    identity = exchange_google_code(code, authorizer.settings, str(payload.get("nonce", "")))
    # Older isolated email-only callers can create only a legacy business session.
    email = identity.email if isinstance(identity, VerifiedGoogleIdentity) else identity
    role = authorizer.role_for_email(email)
    if role is None:
        raise HTTPException(status_code=403, detail="account is not authorized")
    session = authorizer.create_session(email, role, stable_context=(
        identity.stable_context if isinstance(identity, VerifiedGoogleIdentity) else None))
    response = RedirectResponse("/command-center", status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        session,
        max_age=authorizer.settings.session_ttl_seconds,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    response.delete_cookie(OAUTH_STATE_COOKIE, path="/auth/google")
    return response


def logout_response() -> RedirectResponse:
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(OAUTH_STATE_COOKIE, path="/auth/google")
    return response
