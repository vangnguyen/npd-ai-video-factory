import asyncio

import httpx

from npd_agent_hub.config import HubSettings
from npd_agent_hub.espocrm_schema import EspoSchemaReader


def test_reads_entity_fields_from_metadata_endpoint():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["api_key"] = request.headers.get("X-Api-Key")
        return httpx.Response(
            200,
            json={
                "fields": {
                    "name": {"type": "varchar", "required": True},
                    "status": {
                        "type": "enum",
                        "options": ["New", "Assigned"],
                    },
                    "customScore": {
                        "type": "int",
                        "readOnly": True,
                    },
                }
            },
        )

    reader = EspoSchemaReader(
        HubSettings(
            espocrm_url="https://crm.example.com",
            espocrm_api_key="read-only-key",
        ),
        transport=httpx.MockTransport(handler),
    )

    schema = asyncio.run(reader.read_entity("Lead"))

    assert schema.entity_type == "Lead"
    assert schema.field_count == 3
    assert next(field for field in schema.fields if field.name == "name").required is True
    assert next(field for field in schema.fields if field.name == "status").options == [
        "New",
        "Assigned",
    ]
    assert "key=entityDefs.Lead" in seen["url"]
    assert seen["api_key"] == "read-only-key"


def test_rejects_invalid_entity_type_before_network_call():
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    reader = EspoSchemaReader(
        HubSettings(
            espocrm_url="https://crm.example.com",
            espocrm_api_key="read-only-key",
        ),
        transport=httpx.MockTransport(handler),
    )

    try:
        asyncio.run(reader.read_entity("Lead;drop"))
        assert False, "invalid entity type should fail"
    except Exception as exc:
        assert "invalid EspoCRM entity type" in str(exc)

    assert called is False
