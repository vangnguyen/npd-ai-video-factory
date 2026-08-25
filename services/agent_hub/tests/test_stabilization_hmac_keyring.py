from __future__ import annotations

import json
from datetime import datetime, timezone

from npd_agent_hub.attribution import AttributionService
from npd_agent_hub.attribution_models import (
    IdentitySource,
    SourceTouchpointEvent,
    TouchpointType,
)
from npd_agent_hub.config import HubSettings
from npd_agent_hub.delivery_models import (
    AttributionDeliveryEnvelope,
    AttributionProducerHeartbeat,
)
from npd_agent_hub.delivery_observability import AttributionDeliveryService
from npd_agent_hub.store import MemoryHubStore


UTC = timezone.utc
V1_KEY = "historical-v1-verification-key-00000000000000000000"
V2_KEY = "active-v2-signing-key-0000000000000000000000000"


def delivery_service(
    *,
    key_id: str,
    signing_key: str,
    verification_keys_file: str = "",
    now: datetime | None = None,
) -> AttributionDeliveryService:
    store = MemoryHubStore()
    return AttributionDeliveryService(
        store,
        AttributionService(store),
        HubSettings(
            attribution_receipt_key_id=key_id,
            attribution_receipt_signing_key=signing_key,
            attribution_verification_keys_file=verification_keys_file,
        ),
        clock=lambda: now or datetime(2026, 8, 22, 16, 0, tzinfo=UTC),
    )


def envelope(delivery_id: str) -> AttributionDeliveryEnvelope:
    occurred_at = datetime(2026, 8, 22, 16, 0, tzinfo=UTC)
    return AttributionDeliveryEnvelope(
        delivery_id=delivery_id,
        producer="n8n_lead_intake",
        source_system=IdentitySource.META_ADS,
        sent_at=occurred_at,
        events=[
            SourceTouchpointEvent(
                source_event_id=f"event-{delivery_id}",
                source_system=IdentitySource.META_ADS,
                event_type=TouchpointType.LEAD_CREATED,
                occurred_at=occurred_at,
                channel="paid_social",
                source_campaign_id="source-campaign-keyring",
                lead_id=f"lead-{delivery_id}",
            )
        ],
    )


def heartbeat(sequence: int) -> AttributionProducerHeartbeat:
    now = datetime(2026, 8, 22, 16, 0, tzinfo=UTC)
    return AttributionProducerHeartbeat(
        heartbeat_id=f"heartbeat:n8n-lead-intake:{sequence}",
        producer="n8n_lead_intake",
        emitted_at=now,
        sequence=sequence,
        metadata={"workflow": "lead_intake"},
    )


def write_keyring(path, payload: dict[str, str]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_active_key_signs_and_verifies_new_delivery_receipts():
    service = delivery_service(key_id="v2-active", signing_key=V2_KEY)

    receipt = service.ingest(envelope("delivery:keyring:v2"), actor="n8n")

    assert receipt.key_id == "v2-active"
    assert service.verify(receipt).valid is True
    assert V2_KEY not in receipt.model_dump_json()
    assert V2_KEY not in repr(service.settings)
    assert V2_KEY not in service.status().model_dump_json()
    audit_json = json.dumps(
        [item.model_dump(mode="json") for item in service.store.list_attribution_audit()],
        sort_keys=True,
    )
    assert V2_KEY not in audit_json
    assert V2_KEY not in repr(service.store)


def test_historical_v1_receipt_verifies_after_v2_rotation(tmp_path):
    v1 = delivery_service(key_id="v1-history", signing_key=V1_KEY)
    old_receipt = v1.ingest(envelope("delivery:keyring:v1"), actor="n8n")
    keyring = tmp_path / "verification-keys.json"
    write_keyring(keyring, {"v1-history": V1_KEY})
    v2 = delivery_service(
        key_id="v2-active",
        signing_key=V2_KEY,
        verification_keys_file=str(keyring),
    )

    new_receipt = v2.ingest(envelope("delivery:keyring:v2-new"), actor="n8n")

    assert v2.verify(old_receipt).valid is True
    assert new_receipt.key_id == "v2-active"
    assert old_receipt.key_id != new_receipt.key_id


def test_unknown_key_and_tampered_signature_or_payload_are_invalid(tmp_path):
    keyring = tmp_path / "verification-keys.json"
    write_keyring(keyring, {"v1-history": V1_KEY})
    service = delivery_service(
        key_id="v2-active",
        signing_key=V2_KEY,
        verification_keys_file=str(keyring),
    )
    receipt = service.ingest(envelope("delivery:keyring:tamper"), actor="n8n")
    changed_signature = receipt.signature[:-1] + (
        "0" if receipt.signature[-1] != "0" else "1"
    )

    unknown = service.verify(receipt.model_copy(update={"key_id": "v9-unknown"}))
    signature = service.verify(
        receipt.model_copy(update={"signature": changed_signature})
    )
    payload = service.verify(receipt.model_copy(update={"inserted": receipt.inserted + 1}))

    assert unknown.valid is False
    assert unknown.detail == "Receipt key_id is unknown."
    assert signature.valid is False
    assert payload.valid is False


def test_key_removal_takes_effect_after_restart_config_reload(tmp_path):
    v1 = delivery_service(key_id="v1-history", signing_key=V1_KEY)
    old_receipt = v1.ingest(envelope("delivery:keyring:removal"), actor="n8n")
    keyring = tmp_path / "verification-keys.json"
    write_keyring(keyring, {"v1-history": V1_KEY})
    before_restart = delivery_service(
        key_id="v2-active",
        signing_key=V2_KEY,
        verification_keys_file=str(keyring),
    )
    assert before_restart.verify(old_receipt).valid is True

    write_keyring(keyring, {})
    after_restart = delivery_service(
        key_id="v2-active",
        signing_key=V2_KEY,
        verification_keys_file=str(keyring),
    )

    assert before_restart.verify(old_receipt).valid is True
    assert after_restart.verify(old_receipt).valid is False


def test_historical_heartbeat_receipt_verifies_after_rotation(tmp_path):
    v1 = delivery_service(
        key_id="v1-history",
        signing_key=V1_KEY,
        now=datetime(2026, 8, 22, 16, 0, tzinfo=UTC),
    )
    old_receipt = v1.ingest_heartbeat(heartbeat(1787400000001), actor="n8n")
    keyring = tmp_path / "verification-keys.json"
    write_keyring(keyring, {"v1-history": V1_KEY})
    v2 = delivery_service(
        key_id="v2-active",
        signing_key=V2_KEY,
        verification_keys_file=str(keyring),
        now=datetime(2026, 8, 22, 16, 0, tzinfo=UTC),
    )

    assert v2.verify_heartbeat(old_receipt).valid is True
    assert v2.ingest_heartbeat(heartbeat(1787400000002), actor="n8n").key_id == "v2-active"


def test_legacy_environment_contract_remains_backward_compatible(monkeypatch):
    monkeypatch.delenv("AGENT_ATTRIBUTION_ACTIVE_KEY_ID", raising=False)
    monkeypatch.delenv("AGENT_ATTRIBUTION_ACTIVE_SIGNING_KEY", raising=False)
    monkeypatch.setenv("AGENT_ATTRIBUTION_RECEIPT_KEY_ID", "legacy-v1")
    monkeypatch.setenv("AGENT_ATTRIBUTION_RECEIPT_SIGNING_KEY", V1_KEY)

    loaded = HubSettings.from_env()

    assert loaded.attribution_receipt_key_id == "legacy-v1"
    assert loaded.attribution_receipt_signing_key == V1_KEY
    assert V1_KEY not in repr(loaded)


def test_new_active_environment_contract_takes_precedence(monkeypatch):
    monkeypatch.setenv("AGENT_ATTRIBUTION_RECEIPT_KEY_ID", "legacy-v1")
    monkeypatch.setenv("AGENT_ATTRIBUTION_RECEIPT_SIGNING_KEY", V1_KEY)
    monkeypatch.setenv("AGENT_ATTRIBUTION_ACTIVE_KEY_ID", "v2-active")
    monkeypatch.setenv("AGENT_ATTRIBUTION_ACTIVE_SIGNING_KEY", V2_KEY)
    monkeypatch.setenv(
        "AGENT_ATTRIBUTION_VERIFICATION_KEYS_FILE", "/run/secrets/verification-keys.json"
    )

    loaded = HubSettings.from_env()

    assert loaded.attribution_receipt_key_id == "v2-active"
    assert loaded.attribution_receipt_signing_key == V2_KEY
    assert loaded.attribution_verification_keys_file.endswith("verification-keys.json")
    assert V1_KEY not in repr(loaded)
    assert V2_KEY not in repr(loaded)
