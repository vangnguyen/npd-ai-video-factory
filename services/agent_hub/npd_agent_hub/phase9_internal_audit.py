"""Bounded internal storage lane. Production enrollment is deliberately absent."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from .attribution_models import (
    AttributionAuditEvent, AttributionDataQualitySnapshot, IdentitySource,
    CampaignIdentityMapping, SourceTouchpointIngestRequest, TouchpointEvent, TouchpointType,
)
from .campaign_models import Campaign, CampaignAuditEvent, CampaignStatus
from .delivery_models import AttributionDeliveryReceipt
from .phase9_cohort_models import Phase9InternalDeliveryBinding


INTERNAL_AUDIT_CAP = 2000  # Existing per-Campaign capacity, never enlarged.
INTERNAL_AUDIT_BUDGET = 2
AUDIT_TYPES = ("source_touchpoints_ingested", "signed_delivery_received")


class Phase9AuditDenied(ValueError):
    """A denied internal delivery cannot fall back to the global lane."""


def _deny(reason: str) -> None:
    raise Phase9AuditDenied(f"PHASE9_INTERNAL_AUDIT:{reason}")


def content_sha256(model) -> str:
    """Semantic model digest; never advertised as a raw transport digest."""
    raw = json.dumps(model.model_dump(mode="json"), sort_keys=True,
                     separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def load_binding(settings) -> Phase9InternalDeliveryBinding | None:
    path = settings.phase9_internal_cohort_binding_file
    if not path:
        return None
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                _deny("AMBIGUOUS_BINDING")
            result[key] = value
        return result
    try:
        payload = json.loads(Path(path).read_bytes().decode("utf-8", errors="strict"),
                             object_pairs_hook=unique_pairs)
        return Phase9InternalDeliveryBinding.model_validate(payload)
    except Phase9AuditDenied:
        raise
    except (OSError, ValueError, TypeError):
        _deny("BINDING_UNAVAILABLE_OR_INVALID")


def has_internal_marker(metadata) -> bool:
    if isinstance(metadata, dict):
        if any(key in metadata for key in ("phase9_internal_cohort", "internal_cohort")):
            return True
        return any(has_internal_marker(value) for value in metadata.values())
    if isinstance(metadata, list):
        return any(has_internal_marker(value) for value in metadata)
    return False


def internal_attempt(store, events, metadata, binding) -> bool:
    if has_internal_marker(metadata):
        return True
    for event in events:
        if has_internal_marker(event.metadata):
            return True
        if binding is not None and (
            event.canonical_campaign_id == binding.cohort.canonical_campaign_id
            or f"lead:{event.lead_id}" == binding.cohort.subject_ref
        ):
            return True
        campaign = store.get_campaign(event.canonical_campaign_id) if event.canonical_campaign_id else None
        if campaign is not None and campaign.internal_cohort is not None:
            return True
        # Alternative identity resolution cannot bypass the signed, exact lane.
        # Reuse the product resolver rather than duplicate its matching rules.
        from .attribution import AttributionService
        resolved, _, _ = AttributionService(store)._resolve_source_event(event)
        if any((candidate := store.get_campaign(cid)) is not None
               and candidate.internal_cohort is not None for cid in resolved):
            return True
    return False


def commercial_event(store, event) -> bool:
    campaign = store.get_campaign(event.campaign_id)
    return not has_internal_marker(event.metadata) and (
        campaign is None or campaign.internal_cohort is None
    )


@dataclass(frozen=True)
class InternalDeliveryCommit:
    campaign: Campaign
    binding: Phase9InternalDeliveryBinding
    touchpoint: TouchpointEvent
    snapshot: AttributionDataQualitySnapshot
    receipt: AttributionDeliveryReceipt
    audits: tuple[CampaignAuditEvent, CampaignAuditEvent]
    identity_mappings: tuple[CampaignIdentityMapping, ...] = ()

    def validate(self) -> None:
        cohort = self.binding.cohort
        if (self.campaign.internal_cohort != cohort
                or self.campaign.campaign_id != cohort.canonical_campaign_id
                or self.campaign.audit_metadata.owner != cohort.owner_id
                or self.campaign.budget.amount != 0
                or self.campaign.sales_handoff.first_response_sla_minutes != 15
                or self.campaign.status not in {CampaignStatus.DRAFT, CampaignStatus.APPROVED}
                or self.campaign.channel_plans or self.campaign.email_sequence_refs
                or self.campaign.zalo_zbs_sequence_refs or self.campaign.landing_pages):
            _deny("CAMPAIGN_BINDING_INVALID")
        if (self.touchpoint.campaign_id != cohort.canonical_campaign_id
                or f"lead:{self.touchpoint.lead_id}" != cohort.subject_ref
                or self.touchpoint.opportunity_id is not None
                or self.touchpoint.event_type != TouchpointType.LEAD_CREATED
                or self.touchpoint.source_system != IdentitySource.ESPOCRM.value
                or self.touchpoint.occurred_at != self.binding.occurred_at
                or self.receipt.delivery_id != self.binding.delivery_id
                or self.receipt.payload_digest != self.binding.delivery_payload_sha256
                or self.receipt.attempt_number != 1 or self.receipt.max_attempts != 1
                or self.receipt.snapshot_id != self.snapshot.snapshot_id
                or (self.snapshot.received, self.snapshot.resolved, self.snapshot.inserted,
                    self.snapshot.duplicates, self.snapshot.unknown, self.snapshot.conflicts) != (1, 1, 1, 0, 0, 0)
                or len(self.audits) != INTERNAL_AUDIT_BUDGET
                or tuple(item.event_type for item in self.audits) != AUDIT_TYPES):
            _deny("COMMIT_BINDING_INVALID")
        for audit in self.audits:
            verify_audit(audit, self.binding, self.receipt)
        if any(mapping.source_system == IdentitySource.ESPOCRM and all(
            getattr(mapping, field) is None for field in (
                "source_account_id", "source_campaign_id", "source_adset_id",
                "source_ad_group_id", "source_ad_id", "utm_campaign",
            )) for mapping in self.identity_mappings):
            _deny("AMBIGUOUS_CAMPAIGN")


def wrap_audit(original, binding, receipt) -> CampaignAuditEvent:
    raw = original.model_dump_json()
    return CampaignAuditEvent(
        event_id=original.event_id, event_type=original.event_type,
        campaign_id=binding.cohort.canonical_campaign_id, actor=original.actor,
        detail=original.detail, scope=binding.cohort.scope, created_at=original.created_at,
        metadata={
            "original_attribution_audit_json": raw,
            "raw_attribution_audit_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            "internal_delivery_binding_sha256": content_sha256(binding),
            "subject_ref": binding.cohort.subject_ref,
            "canonical_campaign_id": binding.cohort.canonical_campaign_id,
            "source_occurred_at": binding.occurred_at.isoformat(),
            "delivery_id": receipt.delivery_id, "receipt_id": receipt.receipt_id,
            "snapshot_id": receipt.snapshot_id, "delivery_payload_sha256": receipt.payload_digest,
            "owner_approval_sha256": binding.cohort.owner_approval_sha256,
            "non_customer_proof_sha256": binding.cohort.non_customer_proof_sha256,
            "source_record_sha256": binding.source_record_sha256,
            "source_audit_sha256": binding.source_audit_sha256,
        },
    )


def verify_audit(audit, binding, receipt) -> AttributionAuditEvent:
    try:
        raw = audit.metadata["original_attribution_audit_json"]
        original = AttributionAuditEvent.model_validate_json(raw)
        expected = wrap_audit(original, binding, receipt)
        if audit != expected or original.event_type not in AUDIT_TYPES:
            _deny("AUDIT_READBACK_MISMATCH")
        return original
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, Phase9AuditDenied):
            raise
        _deny("AUDIT_READBACK_INVALID")


def ingest_internal(service, envelope, *, actor, binding):
    """Prepare via existing producers in isolated memory, then one guarded commit."""
    from .attribution import AttributionService
    from .delivery_observability import AttributionDeliveryService
    from .store import MemoryHubStore

    if binding is None:
        _deny("NO_APPROVED_ALLOWLIST")
    if len(envelope.events) != 1 or envelope.attempt_number != 1 or envelope.max_attempts != 1:
        _deny("ONE_DELIVERY_ONLY")
    event = envelope.events[0]
    cohort = binding.cohort
    try:
        campaign = service.store.get_campaign(cohort.canonical_campaign_id)
    except ValueError:
        _deny("CAMPAIGN_BINDING_INVALID")
    if (campaign is None or campaign.internal_cohort != cohort
            or envelope.delivery_id != binding.delivery_id
            or envelope.source_system != IdentitySource.ESPOCRM
            or event.canonical_campaign_id != cohort.canonical_campaign_id
            or f"lead:{event.lead_id}" != cohort.subject_ref
            or event.opportunity_id is not None
            or event.event_type != TouchpointType.LEAD_CREATED
            or event.source_event_id != binding.source_event_id
            or event.occurred_at.tzinfo is None
            or event.occurred_at != binding.occurred_at
            or event.metadata.get("phase9_internal_cohort") != cohort.model_dump(mode="json")
            or event.metadata.get("source_record_sha256") != binding.source_record_sha256
            or event.metadata.get("source_audit_sha256") != binding.source_audit_sha256
            or service._digest_model(envelope) != binding.delivery_payload_sha256):
        _deny("DELIVERY_BINDING_INVALID")
    # This one native export uses canonical binding only. Alternative identities
    # are not guessed or resolved against an unobserved registry during preparation.
    if any(getattr(event, key) is not None for key in (
        "source_account_id", "source_campaign_id", "source_adset_id", "source_ad_group_id",
        "source_ad_id", "utm_source", "utm_medium", "utm_campaign", "utm_content", "landing_page",
    )):
        _deny("AMBIGUOUS_CAMPAIGN")
    resolved, methods, mappings = service.attribution._resolve_source_event(event)
    if resolved != [cohort.canonical_campaign_id] or mappings or methods != ["canonical_campaign_id"]:
        _deny("AMBIGUOUS_CAMPAIGN")

    local = MemoryHubStore()
    local.save_campaign(campaign)
    producer = AttributionService(local)
    snapshot = producer._ingest_source_touchpoints(
        SourceTouchpointIngestRequest(events=envelope.events), actor=actor
    )
    delivery = AttributionDeliveryService(local, producer, service.settings, clock=service.clock)
    receipt = delivery._receipt_for_snapshot(envelope, snapshot)
    local.save_attribution_delivery_receipt(receipt)
    delivery._audit_received(envelope, receipt, snapshot, actor=actor)
    bundle = InternalDeliveryCommit(
        campaign, binding, next(iter(local.touchpoints.values())), snapshot, receipt,
        tuple(wrap_audit(original, binding, receipt) for original in local.attribution_audit),
        tuple(service.store.list_identity_mappings(limit=5000)),
    )
    bundle.validate()
    if not delivery.verify(receipt).valid:
        _deny("RECEIPT_SIGNATURE_INVALID")
    commit = getattr(service.store, "commit_phase9_internal_delivery", None)
    if commit is None:
        _deny("ATOMIC_STORE_UNAVAILABLE")
    if load_binding(service.settings) != binding:
        _deny("ALLOWLIST_CHANGED")
    commit(bundle)
    return receipt
