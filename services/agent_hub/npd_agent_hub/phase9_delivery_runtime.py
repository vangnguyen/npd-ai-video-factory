"""One-delivery HTTP boundary for the approved Phase 9 internal cohort."""
from __future__ import annotations

import hashlib
import json

from .attribution_models import SourceTouchpointEvent
from .config import HubSettings
from .delivery_models import (
    AttributionDeliveryEnvelope,
    AttributionDeliveryReceipt,
    AttributionReceiptVerificationRequest,
)
from .phase9_cohort_models import Phase9InternalDeliveryBinding
from .phase9_internal_audit import load_binding


class Phase9DeliveryDenied(ValueError):
    pass


def verify_delivery_fence(settings: HubSettings) -> Phase9InternalDeliveryBinding:
    if (
        settings.runtime_mode != "phase9_delivery"
        or settings.provider_health_scheduler_enabled is not False
    ):
        raise Phase9DeliveryDenied("PHASE9_DELIVERY_FENCE_INVALID")
    try:
        binding = load_binding(settings)
    except ValueError as exc:
        raise Phase9DeliveryDenied("PHASE9_DELIVERY_BINDING_INVALID") from exc
    if binding is None:
        raise Phase9DeliveryDenied("PHASE9_DELIVERY_BINDING_MISSING")
    return binding


def allows_read(settings: HubSettings, method: str, path: str) -> bool:
    if method != "GET":
        return False
    binding = verify_delivery_fence(settings)
    campaign_id = binding.cohort.canonical_campaign_id
    return path in {
        "/health",
        "/readyz",
        "/api/v1/whoami",
        "/api/v1/tools/capabilities",
        "/api/v1/provider-health/status",
        "/api/v1/provider-health/scheduler",
        "/api/v1/attribution/deliveries/status",
        f"/api/v1/campaigns/{campaign_id}",
        f"/api/v1/campaigns/{campaign_id}/audit",
    }


def _deny_extra_fields(payload: dict, model_fields: object) -> None:
    if set(payload) - set(model_fields):
        raise Phase9DeliveryDenied("PHASE9_DELIVERY_EXTRA_FIELD_DENIED")


def _model_digest(envelope: AttributionDeliveryEnvelope) -> str:
    canonical = json.dumps(
        envelope.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def validate_delivery(
    settings: HubSettings, payload: object
) -> AttributionDeliveryEnvelope:
    binding = verify_delivery_fence(settings)
    if not isinstance(payload, dict):
        raise Phase9DeliveryDenied("PHASE9_DELIVERY_REQUEST_DENIED")
    _deny_extra_fields(payload, AttributionDeliveryEnvelope.model_fields)
    raw_events = payload.get("events")
    if not isinstance(raw_events, list) or len(raw_events) != 1:
        raise Phase9DeliveryDenied("PHASE9_DELIVERY_REQUEST_DENIED")
    if not isinstance(raw_events[0], dict):
        raise Phase9DeliveryDenied("PHASE9_DELIVERY_REQUEST_DENIED")
    _deny_extra_fields(raw_events[0], SourceTouchpointEvent.model_fields)
    envelope = AttributionDeliveryEnvelope.model_validate(payload)
    event = envelope.events[0]
    if (
        envelope.delivery_id != binding.delivery_id
        or envelope.attempt_number != 1
        or envelope.max_attempts != 1
        or event.source_event_id != binding.source_event_id
        or event.occurred_at != binding.occurred_at
        or event.canonical_campaign_id != binding.cohort.canonical_campaign_id
        or f"lead:{event.lead_id}" != binding.cohort.subject_ref
        or _model_digest(envelope) != binding.delivery_payload_sha256
    ):
        raise Phase9DeliveryDenied("PHASE9_DELIVERY_BINDING_DENIED")
    return envelope


def validate_receipt_verification(
    settings: HubSettings, payload: object
) -> AttributionReceiptVerificationRequest:
    binding = verify_delivery_fence(settings)
    if not isinstance(payload, dict) or set(payload) != {"receipt"}:
        raise Phase9DeliveryDenied("PHASE9_DELIVERY_RECEIPT_REQUEST_DENIED")
    raw_receipt = payload.get("receipt")
    if not isinstance(raw_receipt, dict):
        raise Phase9DeliveryDenied("PHASE9_DELIVERY_RECEIPT_REQUEST_DENIED")
    _deny_extra_fields(raw_receipt, AttributionDeliveryReceipt.model_fields)
    request = AttributionReceiptVerificationRequest.model_validate(payload)
    receipt = request.receipt
    if (
        receipt.delivery_id != binding.delivery_id
        or receipt.attempt_number != 1
        or receipt.max_attempts != 1
        or receipt.payload_digest != binding.delivery_payload_sha256
    ):
        raise Phase9DeliveryDenied("PHASE9_DELIVERY_RECEIPT_BINDING_DENIED")
    return request
