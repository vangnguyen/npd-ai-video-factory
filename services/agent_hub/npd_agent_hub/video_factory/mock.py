from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Mapping

from pydantic import ValidationError

from .auth import (
    BoundaryAuthError,
    ServiceIdentity,
    ServiceRequestVerifier,
    canonical_json_bytes,
    sha256_hex,
    sign_webhook,
)
from .client import (
    BridgeTransportRequest,
    BridgeTransportResponse,
    VideoFactoryTransport,
)
from .models import (
    BRIDGE_CONTRACT_VERSION,
    BridgeContractRead,
    BridgeProjectCreatedResponse,
    BridgeProjectDraftRequest,
    BridgeProjectRead,
    BridgeProjectRequestRead,
    BridgeProjectSummary,
    BridgeProjectVersionRead,
    EventType,
    IDEMPOTENCY_KEY_PATTERN,
    RESERVED_OUTBOUND_EVENTS,
    VideoFactoryEventEnvelope,
    VideoProjectCreatedPayload,
)
from .store import MemoryVideoFactoryBoundaryStore


@dataclass(frozen=True)
class MockWebhookDelivery:
    body: bytes = field(repr=False)
    headers: Mapping[str, str] = field(repr=False)


class MockVideoFactoryTransport(VideoFactoryTransport):
    """Serialized in-process transport with no socket, DNS or HTTP activity."""

    network_enabled = False

    def __init__(self, server: "MockVideoFactoryBridgeServer") -> None:
        self.server = server
        self.call_count = 0
        self.calls: list[tuple[str, str, str]] = []

    async def send(self, request: BridgeTransportRequest) -> BridgeTransportResponse:
        self.call_count += 1
        self.calls.append((request.method, request.path, request.query))
        return self.server.handle(request)


class MockVideoFactoryBridgeServer:
    """Independent V2-11 contract double; it imports no Video Factory package."""

    def __init__(
        self,
        *,
        service_id: str,
        service_key_id: str,
        service_key: bytes,
        webhook_key_id: str,
        webhook_key: bytes,
        now: Callable[[], float],
    ) -> None:
        self.now = now
        self.__webhook_key_id = webhook_key_id
        self.__webhook_key = bytes(webhook_key)
        self._auth_store = MemoryVideoFactoryBoundaryStore(now=now)
        self._verifier = ServiceRequestVerifier(
            identities={
                service_id: ServiceIdentity(
                    service_id=service_id,
                    roles=("service",),
                    keys={service_key_id: service_key},
                )
            },
            replay_registry=self._auth_store,
            now=now,
        )
        self._counter = 0
        self._idempotency: dict[str, tuple[str, BridgeProjectCreatedResponse]] = {}
        self._requests: dict[str, BridgeProjectRequestRead] = {}
        self._projects: dict[str, BridgeProjectCreatedResponse] = {}
        self._events: list[VideoFactoryEventEnvelope] = []
        self._undelivered_event_ids: list[str] = []
        self.handled_requests: list[tuple[str, str, str]] = []

    def __repr__(self) -> str:
        return "MockVideoFactoryBridgeServer(keys=<redacted>, network=false)"

    def handle(self, request: BridgeTransportRequest) -> BridgeTransportResponse:
        try:
            identity = self._verifier.verify(
                method=request.method,
                path=request.path,
                query=request.query,
                body=request.body,
                headers=request.headers,
            )
        except BoundaryAuthError as exc:
            return _error(401, exc.code, str(exc))
        self.handled_requests.append((request.method, request.path, request.query))

        if request.method == "GET" and request.path == "/api/v1/bridge/contract":
            return _json_response(
                200,
                BridgeContractRead(
                    inbound_actions=["project.create_draft"],
                    outbound_events=list(RESERVED_OUTBOUND_EVENTS),
                    roles=["owner", "editor", "reviewer", "viewer", "service"],
                    production_deployed=False,
                ),
            )
        if request.method == "POST" and request.path == "/api/v1/bridge/project-requests":
            return self._create_project(
                request, service_id=identity.service_id
            )
        request_match = re.fullmatch(
            r"/api/v1/bridge/project-requests/([A-Za-z][A-Za-z0-9_.:-]{2,119})",
            request.path,
        )
        if request.method == "GET" and request_match:
            current = self._requests.get(request_match.group(1))
            return _json_response(200, current) if current else _not_found()
        summary_match = re.fullmatch(
            r"/api/v1/bridge/projects/([A-Za-z][A-Za-z0-9_.:-]{2,119})/summary",
            request.path,
        )
        if request.method == "GET" and summary_match:
            created = self._projects.get(summary_match.group(1))
            if created is None:
                return _not_found()
            return _json_response(
                200,
                BridgeProjectSummary(
                    project=created.project,
                    versions=1,
                    assets=0,
                    estimated_cost_vnd="0",
                    actual_cost_vnd="0",
                    publications=0,
                    analytics_snapshots=0,
                ),
            )
        return _error(404, "NOT_FOUND", "Bridge route not found")

    def drain_webhooks(self) -> list[MockWebhookDelivery]:
        deliveries: list[MockWebhookDelivery] = []
        event_by_id = {event.event_id: event for event in self._events}
        while self._undelivered_event_ids:
            event_id = self._undelivered_event_ids.pop(0)
            event = event_by_id[event_id]
            body = canonical_json_bytes(event.model_dump(mode="json"))
            headers = sign_webhook(
                key=self.__webhook_key,
                key_id=self.__webhook_key_id,
                body=body,
                event_id=event.event_id,
                timestamp=int(self.now()),
            )
            deliveries.append(MockWebhookDelivery(body=body, headers=headers))
        return deliveries

    def _create_project(
        self, request: BridgeTransportRequest, *, service_id: str
    ) -> BridgeTransportResponse:
        idempotency_key = _header(request.headers, "Idempotency-Key")
        if not re.fullmatch(IDEMPOTENCY_KEY_PATTERN, idempotency_key):
            return _error(
                422,
                "IDEMPOTENCY_KEY_REQUIRED",
                "Idempotency-Key must contain 16-200 characters",
            )
        try:
            payload = BridgeProjectDraftRequest.model_validate_json(request.body)
        except ValidationError:
            return _error(422, "REQUEST_INVALID", "Project request is invalid")
        scoped_hash = hashlib.sha256(
            f"{service_id}\n{idempotency_key}".encode("utf-8")
        ).hexdigest()
        body_hash = sha256_hex(request.body)
        existing = self._idempotency.get(scoped_hash)
        if existing is not None:
            existing_hash, existing_response = existing
            if existing_hash != body_hash:
                return _error(
                    409,
                    "IDEMPOTENCY_CONFLICT",
                    "Idempotency-Key is already bound to a different request",
                )
            replay = existing_response.model_copy(
                update={"idempotent_replay": True}, deep=True
            )
            return _json_response(
                201, replay, headers={"X-Idempotent-Replay": "true"}
            )

        self._counter += 1
        ordinal = self._counter
        now = datetime.fromtimestamp(self.now(), tz=timezone.utc)
        request_id = f"breq_{ordinal:08d}"
        project_id = f"prj_{ordinal:08d}"
        project_version_id = f"pver_{ordinal:08d}"
        workspace_id = payload.workspace_id or "wsp_mock01"
        request_payload = payload.model_dump(mode="json")
        result = {
            "project_id": project_id,
            "project_version_id": project_version_id,
        }
        bridge_request = BridgeProjectRequestRead(
            request_id=request_id,
            service_id=service_id,
            workspace_id=workspace_id,
            project_id=project_id,
            project_version_id=project_version_id,
            status="succeeded",
            request=request_payload,
            result=result,
            failure_code=None,
            failure_reason=None,
            execution_started=False,
            external_action=False,
            created_at=now,
            updated_at=now,
        )
        project = BridgeProjectRead(
            project_id=project_id,
            workspace_id=workspace_id,
            slug=payload.slug,
            name=payload.name,
            niche=payload.niche,
            status="draft",
            current_version_id=project_version_id,
            version=1,
            provenance={
                "source": BRIDGE_CONTRACT_VERSION,
                "bridge_request_id": request_id,
                "source_campaign_id": payload.source_campaign_id,
                "draft_only": True,
            },
            created_at=now,
            updated_at=now,
        )
        version = BridgeProjectVersionRead(
            project_version_id=project_version_id,
            workspace_id=workspace_id,
            project_id=project_id,
            ordinal=1,
            label="agent-hub-draft",
            snapshot={"execution_mode": "draft_only"},
            source_job_id=None,
            version=1,
            provenance={
                "source": BRIDGE_CONTRACT_VERSION,
                "bridge_request_id": request_id,
            },
            created_at=now,
            updated_at=now,
        )
        created = BridgeProjectCreatedResponse(
            bridge_request=bridge_request,
            project=project,
            project_version=version,
            idempotent_replay=False,
        )
        self._requests[request_id] = bridge_request
        self._projects[project_id] = created
        self._idempotency[scoped_hash] = (body_hash, created)
        event = VideoFactoryEventEnvelope(
            event_id=f"bevt_{ordinal:08d}",
            event_type=EventType.VIDEO_PROJECT_CREATED,
            occurred_at=now,
            payload=VideoProjectCreatedPayload(
                project_id=project_id,
                project_version_id=project_version_id,
                workspace_id=workspace_id,
                source_campaign_id=payload.source_campaign_id,
            ).model_dump(mode="json"),
        )
        self._events.append(event)
        self._undelivered_event_ids.append(event.event_id)
        return _json_response(
            201, created, headers={"X-Idempotent-Replay": "false"}
        )


def _json_response(
    status_code: int,
    payload: object,
    *,
    headers: Mapping[str, str] | None = None,
) -> BridgeTransportResponse:
    if isinstance(payload, BridgeContractRead | BridgeProjectCreatedResponse | BridgeProjectRequestRead | BridgeProjectSummary):
        serialized = payload.model_dump(mode="json")
    elif isinstance(payload, dict):
        serialized = payload
    else:
        raise TypeError("mock response payload is unsupported")
    return BridgeTransportResponse(
        status_code=status_code,
        body=canonical_json_bytes(serialized),
        headers=headers or {},
    )


def _error(status_code: int, code: str, message: str) -> BridgeTransportResponse:
    return BridgeTransportResponse(
        status_code=status_code,
        body=canonical_json_bytes({"error": {"code": code, "message": message}}),
    )


def _not_found() -> BridgeTransportResponse:
    return _error(404, "NOT_FOUND", "Bridge resource not found")


def _header(headers: Mapping[str, str], name: str) -> str:
    target = name.lower()
    for key, value in headers.items():
        if str(key).lower() == target:
            return str(value)
    return ""
