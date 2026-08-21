from __future__ import annotations

import re

import httpx
from pydantic import BaseModel, Field

from .config import HubSettings, settings as default_settings


ENTITY_TYPE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,79}$")


class EspoSchemaError(RuntimeError):
    pass


class EspoSchemaNotConfigured(EspoSchemaError):
    pass


class EspoFieldSchema(BaseModel):
    name: str
    type: str | None = None
    required: bool = False
    read_only: bool = False
    not_storable: bool = False
    options: list[str] = Field(default_factory=list)


class EspoEntitySchema(BaseModel):
    entity_type: str
    field_count: int
    fields: list[EspoFieldSchema]


class EspoSchemaReader:
    """Read a safe field-level schema view from EspoCRM Metadata.

    This adapter never reads CRM records. It exposes only entity field definitions
    needed to map custom fields before enabling production workflows.
    """

    def __init__(
        self,
        settings: HubSettings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings or default_settings
        self.transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self.settings.request_timeout_seconds,
            transport=self.transport,
        )

    async def read_entity(self, entity_type: str) -> EspoEntitySchema:
        if not ENTITY_TYPE_PATTERN.fullmatch(entity_type):
            raise EspoSchemaError("invalid EspoCRM entity type")
        if not self.settings.espocrm_url or not self.settings.espocrm_api_key:
            raise EspoSchemaNotConfigured(
                "ESPOCRM_URL and ESPOCRM_API_KEY are required for schema discovery"
            )

        headers = {"X-Api-Key": self.settings.espocrm_api_key}
        params = {"key": f"entityDefs.{entity_type}"}
        async with self._client() as client:
            try:
                response = await client.get(
                    f"{self.settings.espocrm_url}/api/v1/Metadata",
                    params=params,
                    headers=headers,
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise EspoSchemaError(f"EspoCRM metadata request failed: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise EspoSchemaError("EspoCRM metadata returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise EspoSchemaError("EspoCRM metadata returned a non-object response")

        if isinstance(payload.get("entityDefs"), dict):
            payload = payload["entityDefs"].get(entity_type) or {}
        if not isinstance(payload, dict):
            raise EspoSchemaError("EspoCRM entity metadata is unavailable")

        field_defs = payload.get("fields")
        if not isinstance(field_defs, dict):
            raise EspoSchemaError("EspoCRM entity metadata does not contain fields")

        fields: list[EspoFieldSchema] = []
        for field_name, raw_defs in sorted(field_defs.items(), key=lambda item: str(item[0])):
            if not isinstance(field_name, str) or not isinstance(raw_defs, dict):
                continue
            raw_options = raw_defs.get("options")
            options = (
                [str(item) for item in raw_options[:100] if isinstance(item, (str, int, float, bool))]
                if isinstance(raw_options, list)
                else []
            )
            raw_type = raw_defs.get("type")
            fields.append(
                EspoFieldSchema(
                    name=field_name,
                    type=str(raw_type) if raw_type is not None else None,
                    required=bool(raw_defs.get("required", False)),
                    read_only=bool(raw_defs.get("readOnly", False)),
                    not_storable=bool(raw_defs.get("notStorable", False)),
                    options=options,
                )
            )

        return EspoEntitySchema(
            entity_type=entity_type,
            field_count=len(fields),
            fields=fields,
        )
