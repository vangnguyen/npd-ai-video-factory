"""Offline-only coverage for the one-delivery Phase 9 runtime fence."""
from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

import npd_agent_hub.main as main
import npd_agent_hub.routers.delivery as delivery_router
from npd_agent_hub.auth import authorizer
from npd_agent_hub.config import HubSettings
from npd_agent_hub.orchestrator import AgentHub
from npd_agent_hub.phase9_delivery_runtime import (
    Phase9DeliveryDenied,
    validate_delivery,
    verify_delivery_fence,
)
from npd_agent_hub.tools import ToolExecutor
from test_phase9_internal_audit_lane import CID, rig, state


OPERATOR = "LOCAL-DELIVERY-OPERATOR-NOT-PRODUCTION"
VIEWER = "LOCAL-DELIVERY-VIEWER-NOT-PRODUCTION"
OWNER = "LOCAL-DELIVERY-OWNER-NOT-PRODUCTION"


def fenced_app(monkeypatch, tmp_path):
    store, _, _, envelope, binding, service = rig(tmp_path)
    settings = replace(
        service.settings,
        runtime_mode="phase9_delivery",
        provider_health_scheduler_enabled=False,
        auth_mode="static_token",
        operator_token=OPERATOR,
        viewer_token=VIEWER,
        owner_token=OWNER,
    )
    local = AgentHub(store=store, executor=ToolExecutor(settings=settings))
    monkeypatch.setattr(main, "hub", local)
    monkeypatch.setattr(delivery_router, "hub", local)
    monkeypatch.setattr(authorizer, "settings", settings)
    return local, store, envelope, binding, settings


def test_exact_delivery_and_exact_receipt_verification_are_the_only_posts(
    monkeypatch, tmp_path
):
    local, store, envelope, binding, settings = fenced_app(monkeypatch, tmp_path)
    with TestClient(main.app) as client:
        headers = {"Authorization": f"Bearer {OPERATOR}"}
        response = client.post(
            "/api/v1/attribution/deliveries",
            headers=headers,
            json=envelope.model_dump(mode="json"),
        )
        assert response.status_code == 200
        receipt = response.json()
        assert receipt["delivery_id"] == binding.delivery_id
        assert receipt["payload_digest"] == binding.delivery_payload_sha256
        verified = client.post(
            "/api/v1/attribution/deliveries/receipts/verify",
            headers=headers,
            json={"receipt": receipt},
        )
        assert verified.status_code == 200 and verified.json()["valid"] is True
        assert client.get("/health").status_code == 200
        assert client.get("/readyz").status_code == 200
        assert client.get(f"/api/v1/campaigns/{CID}", headers=headers).status_code == 200
        assert client.get(f"/api/v1/campaigns/{CID}/audit", headers=headers).status_code == 200
    assert len(store.list_touchpoints(lead_id=envelope.events[0].lead_id)) == 1
    assert len(store.list_campaign_audit(CID)) == 3
    assert local.provider_health_scheduler._task is None


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/api/v1/agent-tasks"),
        ("POST", "/api/v1/attribution/deliveries/heartbeats"),
        ("POST", "/api/v1/attribution/deliveries/failures"),
        ("POST", "/api/v1/provider-health/evaluate"),
        ("POST", "/api/v1/campaigns"),
        ("PATCH", f"/api/v1/campaigns/{CID}"),
        ("GET", "/api/v1/command-center"),
        ("GET", "/auth/google/login"),
    ],
)
def test_unrelated_read_write_scheduler_and_login_routes_deny_before_handler(
    monkeypatch, tmp_path, method, path
):
    _, store, _, _, _ = fenced_app(monkeypatch, tmp_path)
    before = state(store)
    with TestClient(main.app) as client:
        response = client.request(
            method,
            path,
            headers={"Authorization": f"Bearer {OPERATOR}"},
            json={},
        )
    assert response.status_code == 403
    assert response.json()["detail"] == "PHASE9_DELIVERY_ROUTE_DENIED"
    assert state(store) == before


@pytest.mark.parametrize(
    "defect",
    ["wrong_delivery", "wrong_event", "wrong_clock", "retry", "extra_field"],
)
def test_wrong_or_ambiguous_payload_denied_before_business_write(
    monkeypatch, tmp_path, defect
):
    _, store, envelope, _, _ = fenced_app(monkeypatch, tmp_path)
    body = envelope.model_dump(mode="json")
    if defect == "wrong_delivery":
        body["delivery_id"] = "LOCAL-WRONG-DELIVERY"
    elif defect == "wrong_event":
        body["events"][0]["source_event_id"] = "LOCAL-WRONG-EVENT"
    elif defect == "wrong_clock":
        body["events"][0]["occurred_at"] = "2026-09-14T12:00:01Z"
    elif defect == "retry":
        body["attempt_number"] = body["max_attempts"] = 2
    else:
        body["execute"] = True
    before = state(store)
    with TestClient(main.app) as client:
        response = client.post(
            "/api/v1/attribution/deliveries",
            headers={"Authorization": f"Bearer {OPERATOR}"},
            json=body,
        )
    assert response.status_code == 403
    assert response.json()["detail"] == "PHASE9_DELIVERY_REQUEST_DENIED"
    assert state(store) == before


def test_replay_is_denied_by_existing_atomic_store_without_second_write(
    monkeypatch, tmp_path
):
    _, store, envelope, _, _ = fenced_app(monkeypatch, tmp_path)
    headers = {"Authorization": f"Bearer {OPERATOR}"}
    with TestClient(main.app) as client:
        assert client.post(
            "/api/v1/attribution/deliveries",
            headers=headers,
            json=envelope.model_dump(mode="json"),
        ).status_code == 200
        after_first = state(store)
        replay = client.post(
            "/api/v1/attribution/deliveries",
            headers=headers,
            json=envelope.model_dump(mode="json"),
        )
    assert replay.status_code == 422
    assert state(store) == after_first


def test_scheduler_never_initializes_or_runs_in_delivery_mode(monkeypatch, tmp_path):
    local, store, _, _, settings = fenced_app(monkeypatch, tmp_path)

    async def check():
        await local.provider_health_scheduler.start()
        assert local.provider_health_scheduler._task is None
        assert store.get_provider_health_scheduler_status() is None
        for force in (False, True):
            with pytest.raises(ValueError, match="BOUNDED_RUNTIME_SCHEDULER_DENIED"):
                await local.provider_health_scheduler.run_once(force=force)
        await local.provider_health_scheduler.stop()

    asyncio.run(check())
    assert verify_delivery_fence(settings).delivery_id


def test_missing_or_invalid_binding_fails_closed(monkeypatch, tmp_path):
    _, _, _, _, settings = fenced_app(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="binding file"):
        replace(settings, phase9_internal_cohort_binding_file="")
    invalid_path = tmp_path / "invalid-binding.json"
    invalid_path.write_text("{}", encoding="utf-8")
    invalid = replace(settings, phase9_internal_cohort_binding_file=str(invalid_path))
    with pytest.raises(Phase9DeliveryDenied, match="BINDING_INVALID"):
        verify_delivery_fence(invalid)


def test_delivery_env_requires_explicit_scheduler_false(monkeypatch, tmp_path):
    binding = tmp_path / "binding.json"
    binding.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("AGENT_RUNTIME_MODE", "phase9_delivery")
    monkeypatch.setenv("AGENT_PHASE9_INTERNAL_COHORT_BINDING_FILE", str(binding))
    monkeypatch.delenv("AGENT_PROVIDER_HEALTH_SCHEDULER_ENABLED", raising=False)
    with pytest.raises(ValueError, match="explicit scheduler false"):
        HubSettings.from_env()


def test_direct_validator_rejects_extra_nested_event_field(monkeypatch, tmp_path):
    _, _, envelope, _, settings = fenced_app(monkeypatch, tmp_path)
    body = envelope.model_dump(mode="json")
    body["events"][0]["untrusted_extra"] = True
    with pytest.raises(Phase9DeliveryDenied, match="EXTRA_FIELD_DENIED"):
        validate_delivery(settings, body)
