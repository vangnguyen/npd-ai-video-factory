from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from .auth import ReplayRegistry, ServiceRequestSigner, canonical_json_bytes
from .models import (
    BRIDGE_BASE_PATH,
    BoundaryMode,
    BridgeContractRead,
    BridgeProjectCreatedResponse,
    BridgeProjectDraftRequest,
    BridgeProjectRequestRead,
    BridgeProjectSummary,
    IDEMPOTENCY_KEY_PATTERN,
    VideoFactoryAnalyticsQueryDTO,
    VideoFactoryAnalysisRequestDTO,
    VideoFactoryApprovalDecisionDTO,
    VideoFactoryApprovalRequestDTO,
    VideoFactoryGenerationRequestDTO,
    VideoFactoryIntegrationStatus,
    VideoFactoryPreviewRequestDTO,
    VideoFactoryProjectDTO,
    VideoFactoryPublicationQueryDTO,
    VideoFactoryPublicationRequestDTO,
    VideoFactoryRenderRequestDTO,
    VideoFactoryStatusDTO,
)


class VideoFactoryBoundaryError(RuntimeError):
    code = "VIDEO_FACTORY_BOUNDARY_ERROR"


class IntegrationDisabled(VideoFactoryBoundaryError):
    code = "VIDEO_FACTORY_INTEGRATION_DISABLED"


class IntegrationNotConfigured(VideoFactoryBoundaryError):
    code = "VIDEO_FACTORY_INTEGRATION_NOT_CONFIGURED"


class UnsupportedCapability(VideoFactoryBoundaryError):
    code = "VIDEO_FACTORY_CAPABILITY_UNSUPPORTED"

    def __init__(self, capability: str):
        self.capability = capability
        super().__init__(
            f"{capability} is not available in the pinned agent-hub-bridge.v1 contract"
        )


class BridgeContractError(VideoFactoryBoundaryError):
    code = "VIDEO_FACTORY_CONTRACT_INVALID"


class BridgeResponseError(VideoFactoryBoundaryError):
    def __init__(self, *, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class BridgeTransportRequest:
    method: str
    path: str
    query: str = ""
    body: bytes = field(default=b"", repr=False)
    headers: Mapping[str, str] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if self.method not in {"GET", "POST"}:
            raise ValueError("bridge transport supports GET and POST only")
        if not self.path.startswith(f"{BRIDGE_BASE_PATH}/"):
            raise ValueError("non-bridge routes are prohibited")
        if "?" in self.path:
            raise ValueError("path and exact encoded query must remain separate")


@dataclass(frozen=True)
class BridgeTransportResponse:
    status_code: int
    body: bytes = field(repr=False)
    headers: Mapping[str, str] = field(default_factory=dict, repr=False)


class VideoFactoryTransport(Protocol):
    network_enabled: bool

    async def send(self, request: BridgeTransportRequest) -> BridgeTransportResponse: ...


ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


class VideoFactoryClient:
    """Narrow V2/V3 bridge client. This AH-02 implementation has no HTTP transport."""

    def __init__(
        self,
        *,
        mode: BoundaryMode = BoundaryMode.DISABLED,
        transport: VideoFactoryTransport | None = None,
        signer: ServiceRequestSigner | None = None,
        nonce_registry: ReplayRegistry | None = None,
        nonce_factory: Callable[[], str] | None = None,
        nonce_ttl_seconds: int = 600,
    ) -> None:
        if mode == BoundaryMode.MOCK and (
            transport is None or signer is None or nonce_registry is None
        ):
            raise ValueError("mock mode requires transport, signer and nonce registry")
        if mode == BoundaryMode.MOCK and getattr(transport, "network_enabled", True):
            raise ValueError("AH-02 mock transport must be explicitly no-network")
        if mode != BoundaryMode.MOCK and any(
            value is not None for value in (transport, signer, nonce_registry)
        ):
            raise ValueError("disabled/not_configured clients cannot carry transports or keys")
        if nonce_ttl_seconds < 300:
            raise ValueError("nonce TTL must be at least 300 seconds")
        self.mode = mode
        self.__transport = transport
        self.__signer = signer
        self.__nonce_registry = nonce_registry
        self.__nonce_factory = nonce_factory or (
            lambda: f"ah-{secrets.token_urlsafe(24)}"
        )
        self.nonce_ttl_seconds = nonce_ttl_seconds

    def __repr__(self) -> str:
        return f"VideoFactoryClient(mode={self.mode.value!r}, credentials=<redacted>)"

    def status(self) -> VideoFactoryIntegrationStatus:
        return VideoFactoryIntegrationStatus(
            mode=self.mode,
            configured=self.mode == BoundaryMode.MOCK,
        )

    async def get_contract(self) -> BridgeContractRead:
        response = await self._send(method="GET", path=f"{BRIDGE_BASE_PATH}/contract")
        return self._parse(response, BridgeContractRead)

    async def create_draft_project(
        self,
        request: BridgeProjectDraftRequest,
        *,
        idempotency_key: str,
    ) -> BridgeProjectCreatedResponse:
        if not re.fullmatch(IDEMPOTENCY_KEY_PATTERN, idempotency_key):
            raise ValueError("idempotency key must contain 16-200 safe characters")
        body = canonical_json_bytes(request.model_dump(mode="json"))
        response = await self._send(
            method="POST",
            path=f"{BRIDGE_BASE_PATH}/project-requests",
            body=body,
            extra_headers={
                "Content-Type": "application/json",
                "Idempotency-Key": idempotency_key,
            },
        )
        return self._parse(response, BridgeProjectCreatedResponse)

    async def create_project(
        self,
        request: BridgeProjectDraftRequest,
        *,
        idempotency_key: str,
    ) -> BridgeProjectCreatedResponse:
        """Live bridge alias; project creation remains draft-only."""

        return await self.create_draft_project(
            request, idempotency_key=idempotency_key
        )

    async def get_project_request(
        self, request_id: str
    ) -> BridgeProjectRequestRead:
        _require_resource_id(request_id, "request_id")
        response = await self._send(
            method="GET", path=f"{BRIDGE_BASE_PATH}/project-requests/{request_id}"
        )
        return self._parse(response, BridgeProjectRequestRead)

    async def get_project_summary(self, project_id: str) -> BridgeProjectSummary:
        _require_resource_id(project_id, "project_id")
        response = await self._send(
            method="GET", path=f"{BRIDGE_BASE_PATH}/projects/{project_id}/summary"
        )
        return self._parse(response, BridgeProjectSummary)

    async def get_project(self, project_id: str) -> VideoFactoryProjectDTO:
        summary = await self.get_project_summary(project_id)
        current_version_id = summary.project.current_version_id
        if current_version_id is None:
            raise BridgeContractError("draft project is missing current_version_id")
        campaign_ref = summary.project.provenance.get("source_campaign_id")
        return VideoFactoryProjectDTO(
            project_id=summary.project.project_id,
            workspace_id=summary.project.workspace_id,
            project_version_id=current_version_id,
            source_campaign_id=(
                str(campaign_ref) if campaign_ref is not None else None
            ),
            name=summary.project.name,
            slug=summary.project.slug,
            status="draft",
        )

    async def get_status(self, request_id: str) -> VideoFactoryStatusDTO:
        current = await self.get_project_request(request_id)
        return VideoFactoryStatusDTO(
            request_id=current.request_id,
            status=current.status,
            project_id=current.project_id,
            project_version_id=current.project_version_id,
            failure_code=current.failure_code,
            failure_reason=current.failure_reason,
            execution_started=current.execution_started,
            external_action=current.external_action,
            updated_at=current.updated_at,
        )

    @staticmethod
    def project_dto(created: BridgeProjectCreatedResponse) -> VideoFactoryProjectDTO:
        source_campaign_id = created.bridge_request.request.get("source_campaign_id")
        return VideoFactoryProjectDTO(
            project_id=created.project.project_id,
            workspace_id=created.project.workspace_id,
            project_version_id=created.project_version.project_version_id,
            source_campaign_id=(
                str(source_campaign_id) if source_campaign_id is not None else None
            ),
            name=created.project.name,
            slug=created.project.slug,
            status="draft",
            execution_started=created.bridge_request.execution_started,
            external_action=created.bridge_request.external_action,
        )

    async def request_generation(
        self, request: VideoFactoryGenerationRequestDTO
    ) -> None:
        del request
        raise UnsupportedCapability("video.generation.request")

    async def request_analysis(self, request: VideoFactoryAnalysisRequestDTO) -> None:
        del request
        raise UnsupportedCapability("video.analysis.request")

    async def request_preview(self, request: VideoFactoryPreviewRequestDTO) -> None:
        del request
        raise UnsupportedCapability("video.preview.request")

    async def request_approval(self, request: VideoFactoryApprovalRequestDTO) -> None:
        del request
        raise UnsupportedCapability("video.approval.request")

    async def submit_approval(
        self, decision: VideoFactoryApprovalDecisionDTO
    ) -> None:
        del decision
        raise UnsupportedCapability("video.approval.submit")

    async def request_render(self, request: VideoFactoryRenderRequestDTO) -> None:
        del request
        raise UnsupportedCapability("video.render.request")

    async def request_publication(
        self, request: VideoFactoryPublicationRequestDTO
    ) -> None:
        del request
        raise UnsupportedCapability("video.publication.request")

    async def get_publications(
        self, query: VideoFactoryPublicationQueryDTO
    ) -> None:
        del query
        raise UnsupportedCapability("video.publication.read")

    async def get_analytics(self, query: VideoFactoryAnalyticsQueryDTO) -> None:
        del query
        raise UnsupportedCapability("video.analytics.read")

    async def _send(
        self,
        *,
        method: str,
        path: str,
        query: str = "",
        body: bytes = b"",
        extra_headers: Mapping[str, str] | None = None,
    ) -> BridgeTransportResponse:
        self._ensure_callable()
        _ensure_allowed_route(method=method, path=path)
        assert self.__transport is not None
        assert self.__signer is not None
        assert self.__nonce_registry is not None
        nonce = self.__nonce_factory()
        if not self.__nonce_registry.claim_replay(
            f"outbound:{self.__signer.service_id}:{self.__signer.key_id}",
            nonce,
            ttl_seconds=self.nonce_ttl_seconds,
        ):
            raise BridgeContractError("generated request nonce has already been used")
        headers = self.__signer.sign(
            method=method,
            path=path,
            query=query,
            body=body,
            nonce=nonce,
        )
        headers.update(extra_headers or {})
        return await self.__transport.send(
            BridgeTransportRequest(
                method=method,
                path=path,
                query=query,
                body=body,
                headers=headers,
            )
        )

    def _ensure_callable(self) -> None:
        if self.mode == BoundaryMode.DISABLED:
            raise IntegrationDisabled("Video Factory integration is disabled")
        if self.mode == BoundaryMode.NOT_CONFIGURED:
            raise IntegrationNotConfigured("Video Factory integration is not configured")
        if self.mode != BoundaryMode.MOCK:
            raise IntegrationDisabled("unsupported Video Factory integration mode")

    @staticmethod
    def _parse(
        response: BridgeTransportResponse, model: type[ResponseModel]
    ) -> ResponseModel:
        if response.status_code < 200 or response.status_code >= 300:
            payload = _safe_json(response.body)
            error = payload.get("error") if isinstance(payload, dict) else None
            code = (
                str(error.get("code"))
                if isinstance(error, dict) and error.get("code")
                else "VIDEO_FACTORY_BRIDGE_ERROR"
            )
            message = (
                str(error.get("message"))
                if isinstance(error, dict) and error.get("message")
                else "Video Factory bridge request failed"
            )
            raise BridgeResponseError(
                status_code=response.status_code, code=code, message=message
            )
        try:
            return model.model_validate_json(response.body)
        except ValidationError as exc:
            raise BridgeContractError(
                "Video Factory response violated the pinned bridge contract"
            ) from exc


_RESOURCE_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{2,119}$")
_ALLOWED_ROUTES = (
    ("GET", re.compile(r"^/api/v1/bridge/contract$")),
    ("POST", re.compile(r"^/api/v1/bridge/project-requests$")),
    ("GET", re.compile(r"^/api/v1/bridge/project-requests/[A-Za-z][A-Za-z0-9_.:-]{2,119}$")),
    ("GET", re.compile(r"^/api/v1/bridge/projects/[A-Za-z][A-Za-z0-9_.:-]{2,119}/summary$")),
)


def _ensure_allowed_route(*, method: str, path: str) -> None:
    if not any(
        method == allowed_method and pattern.fullmatch(path)
        for allowed_method, pattern in _ALLOWED_ROUTES
    ):
        raise UnsupportedCapability(f"{method} {path}")


def _require_resource_id(value: str, field_name: str) -> None:
    if not _RESOURCE_ID_PATTERN.fullmatch(value):
        raise ValueError(f"{field_name} is invalid")


def _safe_json(body: bytes) -> dict[str, Any]:
    import json

    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
