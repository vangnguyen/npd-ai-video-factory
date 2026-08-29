from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import fakeredis
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from npd_agent_hub.main import app
from npd_agent_hub.video_factory.auth import (
    BoundaryAuthError,
    ServiceIdentity,
    ServiceRequestSigner,
    ServiceRequestVerifier,
    WebhookVerifier,
    canonical_json_bytes,
    sign_webhook,
)
from npd_agent_hub.video_factory.client import (
    BridgeResponseError,
    BridgeContractError,
    IntegrationDisabled,
    IntegrationNotConfigured,
    UnsupportedCapability,
    VideoFactoryClient,
)
from npd_agent_hub.video_factory.mock import (
    MockVideoFactoryBridgeServer,
    MockVideoFactoryTransport,
)
from npd_agent_hub.video_factory.models import (
    BoundaryMode,
    BridgeProjectDraftRequest,
    EventType,
    LIVE_OUTBOUND_EVENTS,
    VideoFactoryAnalyticsQueryDTO,
    VideoFactoryAnalysisRequestDTO,
    VideoFactoryApprovalDecisionDTO,
    VideoFactoryApprovalRequestDTO,
    VideoFactoryEventEnvelope,
    VideoFactoryGenerationRequestDTO,
    VideoFactoryPreviewRequestDTO,
    VideoFactoryPublicationQueryDTO,
    VideoFactoryPublicationRequestDTO,
    VideoFactoryRenderRequestDTO,
)
from npd_agent_hub.video_factory.receiver import (
    VideoFactoryBoundary,
    VideoFactoryWebhookReceiver,
    WebhookBoundaryError,
)
from npd_agent_hub.video_factory.store import (
    MemoryVideoFactoryBoundaryStore,
    RedisVideoFactoryBoundaryStore,
)


NOW = 1_788_000_000
SERVICE_KEY = b"agent-hub-mock-service-key-material-0001"
WEBHOOK_KEY = b"video-factory-mock-webhook-key-00001"


def draft_request(**overrides: object) -> BridgeProjectDraftRequest:
    values: dict[str, object] = {
        "slug": "vinh-tien-draft",
        "name": "Vịnh Tiên Draft",
        "niche": "real_estate",
        "source_campaign_id": "CMP-VGP-20260829",
        "brief": {"objective": "lead_generation", "language": "vi"},
    }
    values.update(overrides)
    return BridgeProjectDraftRequest(**values)


def mock_stack(
    *, nonce_factory=None
) -> tuple[VideoFactoryClient, MockVideoFactoryTransport, MockVideoFactoryBridgeServer]:
    server = MockVideoFactoryBridgeServer(
        service_id="agent-hub",
        service_key_id="inbound-v1",
        service_key=SERVICE_KEY,
        webhook_key_id="outbound-v1",
        webhook_key=WEBHOOK_KEY,
        now=lambda: NOW,
    )
    transport = MockVideoFactoryTransport(server)
    client = VideoFactoryClient(
        mode=BoundaryMode.MOCK,
        transport=transport,
        signer=ServiceRequestSigner(
            service_id="agent-hub",
            key_id="inbound-v1",
            key=SERVICE_KEY,
            now=lambda: NOW,
        ),
        nonce_registry=MemoryVideoFactoryBoundaryStore(now=lambda: NOW),
        nonce_factory=nonce_factory,
    )
    return client, transport, server


def configured_boundary() -> tuple[
    VideoFactoryBoundary,
    VideoFactoryClient,
    MockVideoFactoryBridgeServer,
    MemoryVideoFactoryBoundaryStore,
]:
    client, _transport, server = mock_stack()
    store = MemoryVideoFactoryBoundaryStore(now=lambda: NOW)
    receiver = VideoFactoryWebhookReceiver(
        verifier=WebhookVerifier(
            keys={"outbound-v1": WEBHOOK_KEY}, now=lambda: NOW
        ),
        store=store,
    )
    return (
        VideoFactoryBoundary(client=client, store=store, receiver=receiver),
        client,
        server,
        store,
    )


def test_versioned_dtos_forbid_unknown_fields_and_unsafe_values() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        BridgeProjectDraftRequest(
            **draft_request().model_dump(), undocumented_execution=True
        )


def test_agent_hub_schema_records_pinned_live_boundary() -> None:
    schema_path = (
        Path(__file__).resolve().parents[3]
        / "packages"
        / "contracts"
        / "agent-hub-video-factory-boundary.v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["x-pinned-video-factory-commit"] == (
        "8fa96409b0db6ec6d4dc3c04f6e3aaab2f3201ee"
    )
    assert schema["x-live-inbound-actions"] == ["project.create_draft"]
    assert schema["x-live-outbound-events"] == ["video.project.created"]
    assert schema["x-network-transport"] == "not_implemented"
    assert "video.analysis.completed" in schema["properties"]["event_type"]["enum"]
    with pytest.raises(ValidationError):
        draft_request(start_pipeline=True)
    with pytest.raises(ValidationError, match="secret-like"):
        draft_request(brief={"access_token": "do-not-store"})
    with pytest.raises(ValidationError, match="timezone"):
        VideoFactoryEventEnvelope(
            event_id="bevt_0001",
            event_type=EventType.VIDEO_PROJECT_CREATED,
            occurred_at=datetime(2026, 8, 29),
            payload={
                "project_id": "prj_0001",
                "project_version_id": "pver_0001",
                "workspace_id": "wsp_0001",
                "status": "draft",
                "execution_started": False,
                "external_action": False,
            },
        )


def test_signer_and_verifier_bind_raw_body_path_and_encoded_query() -> None:
    signer = ServiceRequestSigner(
        service_id="agent-hub",
        key_id="inbound-v1",
        key=SERVICE_KEY,
        now=lambda: NOW,
    )
    store = MemoryVideoFactoryBoundaryStore(now=lambda: NOW)
    verifier = ServiceRequestVerifier(
        identities={
            "agent-hub": ServiceIdentity(
                "agent-hub", ("service",), {"inbound-v1": SERVICE_KEY}
            )
        },
        replay_registry=store,
        now=lambda: NOW,
    )
    body = canonical_json_bytes({"safe": True})
    encoded_query = "project_id=prj_1%2F2&label=warm+voice"
    headers = signer.sign(
        method="GET",
        path="/api/v1/bridge/events",
        query=encoded_query,
        body=body,
        nonce="nonce-query-00000001",
    )
    verified = verifier.verify(
        method="GET",
        path="/api/v1/bridge/events",
        query=encoded_query,
        body=body,
        headers=headers,
    )
    assert verified.service_id == "agent-hub"

    altered = signer.sign(
        method="GET",
        path="/api/v1/bridge/events",
        query=encoded_query,
        body=body,
        nonce="nonce-query-00000002",
    )
    with pytest.raises(BoundaryAuthError) as exc_info:
        verifier.verify(
            method="GET",
            path="/api/v1/bridge/events",
            query="project_id=prj_1/2&label=warm voice",
            body=body,
            headers=altered,
        )
    assert exc_info.value.code == "SERVICE_AUTH_INVALID"


def test_service_auth_fails_closed_for_body_clock_key_and_nonce_replay() -> None:
    signer = ServiceRequestSigner(
        service_id="agent-hub",
        key_id="inbound-v1",
        key=SERVICE_KEY,
        now=lambda: NOW,
    )
    verifier = ServiceRequestVerifier(
        identities={
            "agent-hub": ServiceIdentity(
                "agent-hub", ("service",), {"inbound-v1": SERVICE_KEY}
            )
        },
        replay_registry=MemoryVideoFactoryBoundaryStore(now=lambda: NOW),
        now=lambda: NOW,
    )
    body = b'{"safe":true}'
    headers = signer.sign(
        method="POST",
        path="/api/v1/bridge/project-requests",
        body=body,
        nonce="nonce-auth-000000001",
    )
    verifier.verify(
        method="POST",
        path="/api/v1/bridge/project-requests",
        query="",
        body=body,
        headers=headers,
    )
    with pytest.raises(BoundaryAuthError) as replay:
        verifier.verify(
            method="POST",
            path="/api/v1/bridge/project-requests",
            query="",
            body=body,
            headers=headers,
        )
    assert replay.value.code == "SERVICE_AUTH_REPLAY"

    changed_headers = signer.sign(
        method="POST",
        path="/api/v1/bridge/project-requests",
        body=body,
        nonce="nonce-auth-000000002",
    )
    with pytest.raises(BoundaryAuthError) as changed:
        verifier.verify(
            method="POST",
            path="/api/v1/bridge/project-requests",
            query="",
            body=b'{"safe":false}',
            headers=changed_headers,
        )
    assert changed.value.code == "SERVICE_AUTH_INVALID"

    expired_headers = signer.sign(
        method="GET",
        path="/api/v1/bridge/contract",
        timestamp=NOW - 301,
        nonce="nonce-auth-000000003",
    )
    with pytest.raises(BoundaryAuthError) as expired:
        verifier.verify(
            method="GET",
            path="/api/v1/bridge/contract",
            query="",
            body=b"",
            headers=expired_headers,
        )
    assert expired.value.code == "SERVICE_AUTH_EXPIRED"

    unknown_key = dict(
        signer.sign(
            method="GET",
            path="/api/v1/bridge/contract",
            nonce="nonce-auth-000000004",
        )
    )
    unknown_key["X-NPD-Key-Id"] = "unknown-v1"
    with pytest.raises(BoundaryAuthError) as unknown:
        verifier.verify(
            method="GET",
            path="/api/v1/bridge/contract",
            query="",
            body=b"",
            headers=unknown_key,
        )
    assert unknown.value.code == "SERVICE_AUTH_INVALID"


def test_credentials_are_redacted_from_representations() -> None:
    signer = ServiceRequestSigner(
        service_id="agent-hub", key_id="inbound-v1", key=SERVICE_KEY
    )
    assert SERVICE_KEY.decode() not in repr(signer)
    assert "redacted" in repr(signer)
    client = VideoFactoryClient()
    assert "credentials=<redacted>" in repr(client)

    class NetworkTransport:
        network_enabled = True

        async def send(self, _request):  # pragma: no cover - constructor rejects it
            raise AssertionError("must not be called")

    with pytest.raises(ValueError, match="no-network"):
        VideoFactoryClient(
            mode=BoundaryMode.MOCK,
            transport=NetworkTransport(),
            signer=signer,
            nonce_registry=MemoryVideoFactoryBoundaryStore(),
        )


def test_identity_keyring_is_copied_and_frozen() -> None:
    mutable_keys = {"inbound-v1": SERVICE_KEY}
    identity = ServiceIdentity(
        "agent-hub", ("service",), mutable_keys
    )
    mutable_keys["inbound-v1"] = b"changed-key-material-that-is-long-enough"
    assert identity.keys["inbound-v1"] == SERVICE_KEY
    with pytest.raises(TypeError):
        identity.keys["inbound-v1"] = WEBHOOK_KEY  # type: ignore[index]
    verifier = ServiceRequestVerifier(
        identities={"agent-hub": identity},
        replay_registry=MemoryVideoFactoryBoundaryStore(),
    )
    with pytest.raises(TypeError):
        verifier.identities["other"] = identity  # type: ignore[index]
    with pytest.raises(ValueError, match="service_id"):
        ServiceIdentity("unsafe service", ("service",), {"inbound-v1": SERVICE_KEY})


def test_webhook_verifier_keeps_historical_key_copy_for_rotation() -> None:
    old_key = b"historical-webhook-key-material-000001"
    mutable_keys = {"outbound-v0": old_key, "outbound-v1": WEBHOOK_KEY}
    verifier = WebhookVerifier(keys=mutable_keys, now=lambda: NOW)
    mutable_keys["outbound-v0"] = WEBHOOK_KEY
    body = canonical_json_bytes({"safe": True})
    headers = sign_webhook(
        key=old_key,
        key_id="outbound-v0",
        body=body,
        event_id="bevt_rotation01",
        timestamp=NOW,
    )
    verified = verifier.verify(body=body, headers=headers)
    assert verified.key_id == "outbound-v0"
    assert old_key.decode() not in repr(verifier)


def test_client_defaults_fail_closed_without_a_transport() -> None:
    disabled = VideoFactoryClient()
    with pytest.raises(IntegrationDisabled):
        asyncio.run(disabled.get_contract())
    not_configured = VideoFactoryClient(mode=BoundaryMode.NOT_CONFIGURED)
    with pytest.raises(IntegrationNotConfigured):
        asyncio.run(not_configured.get_contract())
    assert disabled.status().configured is False
    assert disabled.status().network_calls_enabled is False


def test_mock_client_contract_draft_status_summary_and_idempotency() -> None:
    client, transport, server = mock_stack()
    contract = asyncio.run(client.get_contract())
    assert contract.inbound_actions == ["project.create_draft"]
    assert client.status().live_outbound_events == LIVE_OUTBOUND_EVENTS
    assert client.status().network_calls_enabled is False

    created = asyncio.run(
        client.create_draft_project(
            draft_request(), idempotency_key="ah02-draft-project-0001"
        )
    )
    assert created.project.status == "draft"
    assert created.bridge_request.execution_started is False
    assert created.bridge_request.external_action is False
    assert client.project_dto(created).status == "draft"

    replay = asyncio.run(
        client.create_draft_project(
            draft_request(), idempotency_key="ah02-draft-project-0001"
        )
    )
    assert replay.idempotent_replay is True
    assert replay.project.project_id == created.project.project_id
    status = asyncio.run(client.get_status(created.bridge_request.request_id))
    summary = asyncio.run(client.get_project_summary(created.project.project_id))
    project = asyncio.run(client.get_project(created.project.project_id))
    assert status.status == "succeeded"
    assert status.execution_started is False
    assert summary.execution_controlled_by_video_factory is True
    assert summary.external_action is False
    assert float(summary.actual_cost_vnd) == 0
    assert project.project_version_id == created.project_version.project_version_id
    assert transport.call_count == 6
    assert len(server.drain_webhooks()) == 1
    assert server.drain_webhooks() == []


def test_mock_rejects_changed_idempotent_payload() -> None:
    client, _transport, _server = mock_stack()
    asyncio.run(
        client.create_draft_project(
            draft_request(), idempotency_key="ah02-idempotency-conflict"
        )
    )
    with pytest.raises(BridgeResponseError) as exc_info:
        asyncio.run(
            client.create_draft_project(
                draft_request(name="Changed"),
                idempotency_key="ah02-idempotency-conflict",
            )
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "IDEMPOTENCY_CONFLICT"


def test_idempotency_header_rejects_control_characters_before_transport() -> None:
    client, transport, _server = mock_stack()
    with pytest.raises(ValueError, match="safe characters"):
        asyncio.run(
            client.create_draft_project(
                draft_request(), idempotency_key="ah02-safe-key-0001\r\nInjected"
            )
        )
    assert transport.call_count == 0


def test_reserved_capabilities_fail_before_transport() -> None:
    client, transport, _server = mock_stack()
    calls_before = transport.call_count
    invocations = (
        lambda: client.request_generation(
            VideoFactoryGenerationRequestDTO(
                project_id="prj_0001",
                project_version_id="pver_0001",
                objective="create draft",
            )
        ),
        lambda: client.request_analysis(
            VideoFactoryAnalysisRequestDTO(
                project_id="prj_0001",
                source_asset_ref="asset_0001",
                idempotency_key_ref="ah02-analysis-0001",
            )
        ),
        lambda: client.request_preview(
            VideoFactoryPreviewRequestDTO(
                project_id="prj_0001",
                timeline_version=1,
                idempotency_key_ref="ah02-preview-0001",
            )
        ),
        lambda: client.request_approval(
            VideoFactoryApprovalRequestDTO(
                project_id="prj_0001",
                render_id="rnd_0001",
                expected_project_version_id="pver_0001",
            )
        ),
        lambda: client.submit_approval(
            VideoFactoryApprovalDecisionDTO(
                project_id="prj_0001",
                approval_id="apr_0001",
                decision="approved",
                reviewer_ref="owner-01",
            )
        ),
        lambda: client.request_render(
            VideoFactoryRenderRequestDTO(
                project_id="prj_0001",
                project_version_id="pver_0001",
                approval_id="apr_0001",
                profile="final",
                idempotency_key_ref="ah02-render-00001",
            )
        ),
        lambda: client.request_publication(
            VideoFactoryPublicationRequestDTO(
                project_id="prj_0001",
                render_id="rnd_0001",
                platform="facebook",
                idempotency_key_ref="ah02-publish-00001",
            )
        ),
        lambda: client.get_publications(
            VideoFactoryPublicationQueryDTO(project_id="prj_0001")
        ),
        lambda: client.get_analytics(
            VideoFactoryAnalyticsQueryDTO(project_id="prj_0001")
        ),
    )
    for invoke in invocations:
        with pytest.raises(UnsupportedCapability):
            asyncio.run(invoke())
    assert transport.call_count == calls_before


def test_duplicate_generated_nonce_stops_before_second_transport_call() -> None:
    client, transport, _server = mock_stack(
        nonce_factory=lambda: "duplicate-nonce-000001"
    )
    asyncio.run(client.get_contract())
    with pytest.raises(BridgeContractError, match="nonce"):
        asyncio.run(client.get_contract())
    assert transport.call_count == 1


def test_app_defaults_video_factory_boundary_to_disabled() -> None:
    previous = app.state.video_factory_boundary
    try:
        app.state.video_factory_boundary = VideoFactoryBoundary.disabled()
        with TestClient(app) as api:
            status_response = api.get(
                "/api/v1/integrations/video-factory/status"
            )
            webhook_response = api.post(
                "/agent-hub/events/v1", content=b"{}"
            )
        assert status_response.status_code == 200
        assert status_response.json()["mode"] == "disabled"
        assert status_response.json()["configured"] is False
        assert status_response.json()["network_calls_enabled"] is False
        assert webhook_response.status_code == 503
        assert (
            webhook_response.json()["detail"]["error"]["code"]
            == "VIDEO_FACTORY_INTEGRATION_DISABLED"
        )
    finally:
        app.state.video_factory_boundary = previous


def test_signed_webhook_route_persists_and_idempotently_replays() -> None:
    boundary, client, server, store = configured_boundary()
    created = asyncio.run(
        client.create_project(
            draft_request(), idempotency_key="ah02-webhook-project-0001"
        )
    )
    delivery = server.drain_webhooks()[0]
    previous = app.state.video_factory_boundary
    try:
        app.state.video_factory_boundary = boundary
        with TestClient(app) as api:
            first = api.post(
                "/agent-hub/events/v1",
                content=delivery.body,
                headers=dict(delivery.headers),
            )
            replay = api.post(
                "/agent-hub/events/v1",
                content=delivery.body,
                headers=dict(delivery.headers),
            )
            events = api.get("/api/v1/integrations/video-factory/events")
            audit = api.get("/api/v1/integrations/video-factory/audit")
    finally:
        app.state.video_factory_boundary = previous

    assert first.status_code == 202
    assert first.json()["event_id"] == f"bevt_{1:08d}"
    assert first.headers["X-Idempotent-Replay"] == "false"
    assert first.headers["Cache-Control"] == "no-store"
    assert replay.status_code == 202
    assert replay.json()["status"] == "idempotent_replay"
    assert replay.headers["X-Idempotent-Replay"] == "true"
    assert len(events.json()) == 1
    assert events.json()[0]["event"]["payload"]["project_id"] == created.project.project_id
    assert [item["outcome"] for item in audit.json()] == [
        "idempotent_replay",
        "accepted",
    ]
    serialized = " ".join(
        record.model_dump_json() for record in store.list_events()
    )
    assert SERVICE_KEY.decode() not in serialized
    assert WEBHOOK_KEY.decode() not in serialized
    assert "X-NPD-Signature" not in serialized


def test_webhook_rejects_changed_body_event_id_mismatch_and_reserved_event() -> None:
    boundary, client, server, store = configured_boundary()
    asyncio.run(
        client.create_draft_project(
            draft_request(), idempotency_key="ah02-webhook-conflict-0001"
        )
    )
    delivery = server.drain_webhooks()[0]
    first = boundary.receiver.receive(
        body=delivery.body, headers=delivery.headers
    )
    assert first.status == "accepted"

    changed_payload = {
        **VideoFactoryEventEnvelope.model_validate_json(delivery.body).model_dump(
            mode="json"
        )
    }
    changed_payload["payload"] = {
        **changed_payload["payload"],
        "source_campaign_id": "CMP-CHANGED",
    }
    changed_body = canonical_json_bytes(changed_payload)
    changed_headers = sign_webhook(
        key=WEBHOOK_KEY,
        key_id="outbound-v1",
        body=changed_body,
        event_id=changed_payload["event_id"],
        timestamp=NOW,
    )
    mismatch_headers = sign_webhook(
        key=WEBHOOK_KEY,
        key_id="outbound-v1",
        body=delivery.body,
        event_id="bevt_mismatch01",
        timestamp=NOW,
    )
    reserved_body = canonical_json_bytes(
        {
            "contract_version": "agent-hub-bridge.v1",
            "event_id": "bevt_reserved01",
            "event_type": "video.analysis.completed",
            "occurred_at": datetime.fromtimestamp(
                NOW, tz=timezone.utc
            ).isoformat(),
            "payload": {"project_id": "prj_0001"},
        }
    )
    reserved_headers = sign_webhook(
        key=WEBHOOK_KEY,
        key_id="outbound-v1",
        body=reserved_body,
        event_id="bevt_reserved01",
        timestamp=NOW,
    )
    previous = app.state.video_factory_boundary
    try:
        app.state.video_factory_boundary = boundary
        with TestClient(app) as api:
            conflict = api.post(
                "/agent-hub/events/v1",
                content=changed_body,
                headers=changed_headers,
            )
            mismatch = api.post(
                "/agent-hub/events/v1",
                content=delivery.body,
                headers=mismatch_headers,
            )
            reserved = api.post(
                "/agent-hub/events/v1",
                content=reserved_body,
                headers=reserved_headers,
            )
    finally:
        app.state.video_factory_boundary = previous
    assert conflict.status_code == 409
    assert (
        conflict.json()["detail"]["error"]["code"]
        == "VIDEO_FACTORY_EVENT_IDEMPOTENCY_CONFLICT"
    )
    assert mismatch.status_code == 409
    assert (
        mismatch.json()["detail"]["error"]["code"]
        == "VIDEO_FACTORY_EVENT_ID_MISMATCH"
    )
    assert reserved.status_code == 409
    assert (
        reserved.json()["detail"]["error"]["code"]
        == "VIDEO_FACTORY_EVENT_NOT_LIVE"
    )
    assert len(store.list_events()) == 1


def test_webhook_auth_and_payload_fail_before_persistence() -> None:
    boundary, client, server, store = configured_boundary()
    asyncio.run(
        client.create_draft_project(
            draft_request(), idempotency_key="ah02-webhook-auth-00001"
        )
    )
    delivery = server.drain_webhooks()[0]
    expired = sign_webhook(
        key=WEBHOOK_KEY,
        key_id="outbound-v1",
        body=delivery.body,
        event_id="bevt_00000001",
        timestamp=NOW - 301,
    )
    unknown = sign_webhook(
        key=WEBHOOK_KEY,
        key_id="outbound-v2",
        body=delivery.body,
        event_id="bevt_00000001",
        timestamp=NOW,
    )
    bad_signature = dict(delivery.headers)
    bad_signature["X-NPD-Signature"] = "0" * 64
    secret_body = canonical_json_bytes(
        {
            "contract_version": "agent-hub-bridge.v1",
            "event_id": "bevt_secret01",
            "event_type": "video.project.created",
            "occurred_at": datetime.fromtimestamp(
                NOW, tz=timezone.utc
            ).isoformat(),
            "payload": {
                "project_id": "prj_0001",
                "project_version_id": "pver_0001",
                "workspace_id": "wsp_0001",
                "status": "draft",
                "execution_started": False,
                "external_action": False,
                "access_token": "not-allowed",
            },
        }
    )
    secret_headers = sign_webhook(
        key=WEBHOOK_KEY,
        key_id="outbound-v1",
        body=secret_body,
        event_id="bevt_secret01",
        timestamp=NOW,
    )
    previous = app.state.video_factory_boundary
    try:
        app.state.video_factory_boundary = boundary
        with TestClient(app) as api:
            expired_response = api.post(
                "/agent-hub/events/v1", content=delivery.body, headers=expired
            )
            bad_hash_response = api.post(
                "/agent-hub/events/v1",
                content=delivery.body + b" ",
                headers=dict(delivery.headers),
            )
            unknown_response = api.post(
                "/agent-hub/events/v1", content=delivery.body, headers=unknown
            )
            bad_signature_response = api.post(
                "/agent-hub/events/v1",
                content=delivery.body,
                headers=bad_signature,
            )
            secret_response = api.post(
                "/agent-hub/events/v1",
                content=secret_body,
                headers=secret_headers,
            )
    finally:
        app.state.video_factory_boundary = previous
    assert expired_response.status_code == 401
    assert bad_hash_response.status_code == 401
    assert unknown_response.status_code == 401
    assert bad_signature_response.status_code == 401
    assert secret_response.status_code == 422
    assert store.list_events() == []
    assert store.list_audit() == []


def test_webhook_body_limit_fails_before_auth_or_persistence() -> None:
    store = MemoryVideoFactoryBoundaryStore(now=lambda: NOW)
    receiver = VideoFactoryWebhookReceiver(
        verifier=WebhookVerifier(
            keys={"outbound-v1": WEBHOOK_KEY}, now=lambda: NOW
        ),
        store=store,
        max_body_bytes=1024,
    )
    with pytest.raises(WebhookBoundaryError) as exc_info:
        receiver.receive(body=b"x" * 1025, headers={})
    assert exc_info.value.status_code == 413
    assert store.list_events() == []
    assert store.list_audit() == []


def test_redis_event_store_survives_recreation_and_repairs_missing_index() -> None:
    redis_client = fakeredis.FakeRedis(decode_responses=True)
    with pytest.raises(ValueError, match="Agent Hub-owned"):
        RedisVideoFactoryBoundaryStore(
            client=redis_client,
            namespace="npd:video-factory:v2:bridge",
        )
    store = RedisVideoFactoryBoundaryStore(
        client=redis_client,
        namespace="npd:agent-hub:test:video-factory-boundary",
    )
    event = VideoFactoryEventEnvelope(
        event_id="bevt_store01",
        event_type="video.project.created",
        occurred_at=datetime.fromtimestamp(NOW, tz=timezone.utc),
        payload={
            "project_id": "prj_0001",
            "project_version_id": "pver_0001",
            "workspace_id": "wsp_0001",
            "status": "draft",
            "execution_started": False,
            "external_action": False,
        },
    )
    body = canonical_json_bytes(event.model_dump(mode="json"))
    headers = sign_webhook(
        key=WEBHOOK_KEY,
        key_id="outbound-v1",
        body=body,
        event_id=event.event_id,
        timestamp=NOW,
    )
    verified = WebhookVerifier(
        keys={"outbound-v1": WEBHOOK_KEY}, now=lambda: NOW
    ).verify(body=body, headers=headers)
    from npd_agent_hub.video_factory.models import WebhookVerificationReceipt

    receipt = WebhookVerificationReceipt(
        key_id=verified.key_id,
        signed_at_unix=verified.timestamp,
        body_sha256=verified.body_sha256,
    )
    _record, replay = store.save_event(event=event, verification=receipt)
    assert replay is False
    redis_client.delete("npd:agent-hub:test:video-factory-boundary:events")
    _existing, replay = store.save_event(event=event, verification=receipt)
    assert replay is True
    restarted = RedisVideoFactoryBoundaryStore(
        client=redis_client,
        namespace="npd:agent-hub:test:video-factory-boundary",
    )
    assert [item.event.event_id for item in restarted.list_events()] == [
        "bevt_store01"
    ]
