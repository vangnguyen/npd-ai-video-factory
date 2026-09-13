"""Real local HTTP authorization: client assertions cannot grant Analyze."""
import time
from unittest.mock import Mock, AsyncMock
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from npd_agent_hub.auth import (Capability, CAPABILITY_TTL_SECONDS, Principal, Role,
    StaticTokenAuthorizer, authorizer, principal_capabilities)
from npd_agent_hub.config import HubSettings
from npd_agent_hub.main import app
import npd_agent_hub.main as main

def config(**kw):
    return HubSettings(auth_mode="static_token", viewer_token="fixture-viewer", operator_token="fixture-operator",
                       owner_token="fixture-owner", **kw)

@pytest.mark.parametrize("role,expected", [(Role.VIEWER, []), (Role.OPERATOR, [Capability.ANALYZE_AGENT_TASK.value]),
    (Role.OWNER, [Capability.ANALYZE_AGENT_TASK.value])])
def test_capability_projection_matches_existing_rbac(role, expected):
    assert principal_capabilities(Principal(role, "fixture")) == expected

@pytest.mark.parametrize("unknown", ["admin", "viewer", 30, None])
def test_unknown_role_never_defaults_to_analyze(unknown):
    with pytest.raises(HTTPException) as failure:
        principal_capabilities(Principal(unknown, "fixture"))
    assert failure.value.status_code == 403

@pytest.mark.parametrize("role", ["viewer", "operator", "owner"])
def test_authenticated_bootstrap_projects_server_capability(monkeypatch, role):
    monkeypatch.setattr(authorizer, "settings", config())
    response = TestClient(app).get("/api/v1/whoami", headers={"Authorization": "Bearer fixture-" + role})
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    payload = response.json()
    assert payload["role"] == role and payload["subject"] == role
    assert payload["capability_version"] == 1 and payload["auth_method"] == "bearer"
    assert payload["capabilities"] == ([] if role == "viewer" else ["agent_tasks.analyze"])
    assert 0 < payload["expires_at"] - payload["issued_at"] <= CAPABILITY_TTL_SECONDS

@pytest.mark.parametrize("path,body", [("/api/v1/agent-tasks", {"objective": "Viewer forged Analyze test"}),
    ("/api/v1/agent-tasks/fixture-existing/analyze", None)])
def test_viewer_direct_api_denied_before_business_handler_even_with_forged_client(monkeypatch, path, body):
    monkeypatch.setattr(authorizer, "settings", config())
    service = Mock(); service.analyze = AsyncMock();monkeypatch.setattr(main, "hub", service)
    headers = {"Authorization": "Bearer fixture-viewer", "X-Role": "owner", "X-Capabilities": "agent_tasks.analyze"}
    if body is not None:
        body = dict(body, context={"role": "owner", "capabilities": ["agent_tasks.analyze"]})
    response = TestClient(app).post(path, headers=headers, json=body)
    assert response.status_code == 403 and response.json()["detail"] == "insufficient role"
    service.run.assert_not_called(); service.analyze.assert_not_called()

@pytest.mark.parametrize("role", ["operator", "owner"])
def test_operator_and_owner_use_same_analyze_dependency(monkeypatch, role):
    monkeypatch.setattr(authorizer, "settings", config())
    service=Mock();service.analyze=AsyncMock(side_effect=KeyError("fixture-not-found"));monkeypatch.setattr(main,"hub",service)
    response=TestClient(app).post("/api/v1/agent-tasks/fixture-not-found/analyze",
        headers={"Authorization":"Bearer fixture-"+role})
    assert response.status_code==404
    service.analyze.assert_awaited_once_with("fixture-not-found")

def session_config():
    return config(browser_auth_mode="google_oidc", public_base_url="https://fixture.invalid",
        google_client_id="fixture-client",google_client_secret="fixture-client-secret",
        session_signing_key="fixture-signing-key-with-at-least-32-characters",
        owner_emails=("owner@fixture.invalid",),operator_emails=("operator@fixture.invalid",),
        viewer_emails=("viewer@fixture.invalid",))

def test_capability_expiry_is_clipped_to_auth_session(monkeypatch):
    auth=StaticTokenAuthorizer(session_config());now=int(time.time())
    token=auth.sign_payload({"typ":"session","sub":"operator@fixture.invalid","role":"operator","exp":now+20})
    principal=auth.authenticate(None, token)
    assert auth.capability_payload(principal, token)["expires_at"]==now+20

@pytest.mark.parametrize("case", ["expired","expired-boundary","malformed","removed-role","forged-role"])
def test_invalid_session_cannot_authorize_analyze(monkeypatch, case):
    settings=session_config();monkeypatch.setattr(authorizer,"settings",settings)
    now=int(time.time());payload={"typ":"session","sub":"viewer@fixture.invalid","role":"viewer","exp":now+60}
    if case=="expired":payload["exp"]=now-1
    if case=="expired-boundary":payload["exp"]=now
    if case=="removed-role":payload["sub"]="removed@fixture.invalid"
    if case=="forged-role":payload["role"]="owner"
    token="malformed-session" if case=="malformed" else authorizer.sign_payload(payload)
    service=Mock();service.analyze=AsyncMock();monkeypatch.setattr(main,"hub",service)
    client=TestClient(app);client.cookies.set("npd_agent_session",token)
    response=client.post("/api/v1/agent-tasks/fixture-existing/analyze",headers={"Origin":"https://fixture.invalid"})
    assert response.status_code in {401,403};service.analyze.assert_not_called()

def test_cookie_viewer_direct_api_denied_and_operator_requires_origin(monkeypatch):
    monkeypatch.setattr(authorizer,"settings",session_config())
    service=Mock();service.analyze=AsyncMock();monkeypatch.setattr(main,"hub",service)
    client=TestClient(app)
    for role,origin in [("viewer","https://fixture.invalid"),("operator","https://forged.invalid")]:
        client.cookies.set("npd_agent_session",authorizer.create_session(role+"@fixture.invalid",Role[role.upper()]))
        response=client.post("/api/v1/agent-tasks/fixture-existing/analyze",headers={"Origin":origin})
        assert response.status_code==403
    service.analyze.assert_not_called()

def test_create_and_reanalyze_have_identical_capability_boundary():
    routes={route.path:route for route in app.routes if hasattr(route,"dependant")}
    create=routes["/api/v1/agent-tasks"].dependant.dependencies[0].call
    analyze=routes["/api/v1/agent-tasks/{task_id}/analyze"].dependant.dependencies[0].call
    assert create is analyze
