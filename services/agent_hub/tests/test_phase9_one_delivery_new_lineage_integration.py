"""Bind the offline new-lineage readback contract to current Agent Hub stores."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "ops" / "agent_hub_phase9"))
import one_delivery_new_lineage as lineage

from npd_agent_hub.phase9_delivery_runtime import validate_delivery, verify_delivery_fence
from test_phase9_internal_audit_lane import CID, rig


def readback(store, service, binding, *, runtime_mode="phase9_delivery"):
    lead_id = binding.cohort.subject_ref.removeprefix("lead:")
    # This integration is intentionally bound to MemoryHubStore internals so the
    # evidence is an exact cardinality, never a capped list-view approximation.
    touchpoints = [
        row for row in store.touchpoints.values() if row.lead_id == lead_id
    ]
    source_matches = [
        row for row in touchpoints
        if row.metadata.get("source_event_id") == binding.source_event_id
    ]
    receipts = [
        row for row in store.attribution_delivery_receipts.values()
        if row.delivery_id == binding.delivery_id
    ]
    dead_letters = [
        row for row in store.attribution_dead_letters.values()
        if row.delivery_id == binding.delivery_id
    ]
    audits = list(store.campaign_audit.get(CID, []))
    latest_types = [row.event_type for row in audits[-2:]] if len(audits) >= 2 else []
    return {
        "schema": lineage.READBACK_SCHEMA,
        "lineage": lineage.LINEAGE,
        "campaign_id": CID,
        "delivery_id": binding.delivery_id,
        "source_event_id": binding.source_event_id,
        "subject_touchpoint_count": len(touchpoints),
        "source_event_match_count": len(source_matches),
        "delivery_receipt_match_count": len(receipts),
        "campaign_audit_count": len(audits),
        "latest_campaign_audit_types": latest_types,
        "dead_letter_match_count": len(dead_letters),
        "counts_are_exact": True,
        "query_limit_applied": False,
        "internal_audit_cap": 2000,
        "runtime_mode": runtime_mode,
        "scheduler_enabled": False,
    }


def test_new_lineage_readback_matches_current_delivery_fence_and_store(tmp_path):
    store, _, _, envelope, binding, service = rig(tmp_path)
    settings = replace(
        service.settings,
        runtime_mode="phase9_delivery",
        provider_health_scheduler_enabled=False,
    )
    assert verify_delivery_fence(settings) == binding
    validated = validate_delivery(settings, envelope.model_dump(mode="json"))
    before = readback(store, service, binding)
    receipt = service.ingest(validated, actor="LOCAL-NEW-LINEAGE-FAKE-TRANSPORT")
    after = readback(store, service, binding)
    verified = {
        "bindings": {
            "campaign_id": binding.cohort.canonical_campaign_id,
            "delivery_id": binding.delivery_id,
            "source_event_id": binding.source_event_id,
        },
        "delivery_binding": binding.model_dump(mode="json"),
        "delivery_envelope": validated.model_dump(mode="json"),
        "readback_contract": {
            "touchpoint_delta": 1,
            "source_event_match_delta": 1,
            "delivery_receipt_delta": 1,
            "campaign_audit_delta": 2,
            "dead_letter_delta": 0,
        },
    }
    result = lineage.verify_readback(
        before,
        after,
        receipt.model_dump(mode="json"),
        service.verify(receipt).model_dump(mode="json"),
        {receipt.key_id: service.settings.attribution_receipt_signing_key},
        verified,
    )
    assert result["status"] == "PASS"
    assert after["latest_campaign_audit_types"] == lineage.AUDIT_TYPES
    assert after["campaign_audit_count"] == before["campaign_audit_count"] + 2
    assert len(store.list_touchpoints(lead_id=envelope.events[0].lead_id)) == 1
