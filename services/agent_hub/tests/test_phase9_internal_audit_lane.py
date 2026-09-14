"""Synthetic LOCAL sources only. No native Lead or production evidence is created."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import secrets
from threading import Barrier
from pathlib import Path

import fakeredis
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from npd_agent_hub.attribution import AttributionService
from npd_agent_hub.attribution_models import (
    AttributionAuditEvent, CampaignIdentityMapping, IdentitySource,
    AttributionAcceptanceRequest, AttributionModel, OpportunityObservation, ReconciliationRequest,
    SourceTouchpointEvent, SourceTouchpointIngestRequest, TouchpointBackfillRequest,
)
from npd_agent_hub.auth import authorizer
from npd_agent_hub.campaign_models import (CampaignAuditEvent, CampaignBudget, CampaignCreate,
    CampaignDraftUpdate, CampaignApprovalDecision, CampaignStatus, KPITarget)
from npd_agent_hub.campaigns import CampaignService
from npd_agent_hub.config import HubSettings
from npd_agent_hub.delivery_models import AttributionDeliveryEnvelope, AttributionDeliveryFailure
from npd_agent_hub.delivery_observability import AttributionDeliveryService
from npd_agent_hub.phase9_cohort_models import Phase9InternalCohort, Phase9InternalDeliveryBinding
from npd_agent_hub.phase9_internal_audit import Phase9AuditDenied, content_sha256, verify_audit
from npd_agent_hub.sales_intelligence import SalesIntelligenceService
from npd_agent_hub.sales_intelligence_models import SalesIntelligencePreviewRequest
from npd_agent_hub.sales_sla_contract import report_sla_fields, validate_first_response_sla
from npd_agent_hub.store import MemoryHubStore, RedisHubStore


CID = "CMP-AHINTERNAL-P9SLACOHORT-202609-01"
LEAD = "LOCAL-SYNTHETIC-NOT-NATIVE-LEAD-01"
T0 = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)


def sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def rig(tmp_path, backend="memory"):
    store = (MemoryHubStore() if backend == "memory" else
             RedisHubStore(client=fakeredis.FakeRedis(decode_responses=True), namespace="LOCAL-P9"))
    cohort = Phase9InternalCohort(
        classification="phase9_internal_non_customer", canonical_campaign_id=CID,
        subject_ref=f"lead:{LEAD}", owner_id="LOCAL-UNBOUND-INTERNAL-OWNER",
        owner_approval_sha256=sha("SYNTHETIC local Owner disposition"),
        non_customer_proof_sha256=sha("SYNTHETIC local business proof"),
        scope="phase9_one_internal_task_report_audit_one_nba_review",
    )
    request = CampaignCreate(
        name="P9 SLA Cohort", project="Local static acceptance", project_code="AHINTERNAL",
        objective="Dedicated non-customer local acceptance", audience=["Internal only"],
        budget=CampaignBudget(amount=0), start_date=date(2026, 9, 1), end_date=date(2026, 9, 30),
        kpi_targets=[KPITarget(name="Internal SLA acceptance", target=1, unit="case", funnel_stage="lead")],
        owner=cohort.owner_id, internal_cohort=cohort,
    )
    campaign = CampaignService(store).create(request, actor="LOCAL-OWNER", owner_authorized=True)
    event = SourceTouchpointEvent(
        source_event_id="LOCAL-SYNTHETIC-CREATED-EVENT-01", source_system="espocrm",
        event_type="lead_created", occurred_at=T0, channel="internal",
        canonical_campaign_id=CID, lead_id=LEAD,
        metadata={"phase9_internal_cohort": cohort.model_dump(mode="json"),
                  "source_record_sha256": sha("SYNTHETIC native-shaped record"),
                  "source_audit_sha256": sha("SYNTHETIC native-shaped audit")},
    )
    envelope = AttributionDeliveryEnvelope(
        delivery_id="LOCAL-ONE-INTERNAL-DELIVERY-01", producer="local_static_native_export",
        source_system="espocrm", attempt_number=1, max_attempts=1, sent_at=T0, events=[event],
    )
    binding = Phase9InternalDeliveryBinding(
        cohort=cohort, delivery_id=envelope.delivery_id, source_event_id=event.source_event_id,
        occurred_at=T0, source_record_sha256=event.metadata["source_record_sha256"],
        source_audit_sha256=event.metadata["source_audit_sha256"],
        delivery_payload_sha256=AttributionDeliveryService._digest_model(envelope),
    )
    path = tmp_path / "LOCAL-NOT-PRODUCTION-allowlist.json"
    path.write_text(binding.model_dump_json(), encoding="utf-8")
    settings = HubSettings(attribution_receipt_signing_key=secrets.token_hex(32),
                           phase9_internal_cohort_binding_file=str(path))
    service = AttributionDeliveryService(store, AttributionService(store), settings, clock=lambda: T0)
    return store, campaign, cohort, envelope, binding, service


def state(store):
    if isinstance(store, RedisHubStore):
        return {key: store.redis.dump(key) for key in sorted(store.redis.scan_iter())}
    return {
        "campaigns": [c.model_dump_json() for c in store.campaigns.values()],
        "touchpoints": [e.model_dump_json() for e in store.touchpoints.values()],
        "snapshots": [s.model_dump_json() for s in store.attribution_quality_snapshots.values()],
        "receipts": [r.model_dump_json() for r in store.attribution_delivery_receipts.values()],
        "audit": [a.model_dump_json() for a in store.attribution_audit],
        "campaign_audit": {k: [a.model_dump_json() for a in v] for k, v in store.campaign_audit.items()},
    }


def seed_global_at_cap(store):
    records = [AttributionAuditEvent(event_id=f"LOCAL-HISTORY-{i}", event_type="local_fixture",
                                     actor="local", detail="Synthetic existing history") for i in range(5000)]
    if isinstance(store, MemoryHubStore):
        store.attribution_audit = records
    else:
        store.redis.rpush(store._key("attribution-os", "audit"), *(a.model_dump_json() for a in records))
    return [a.model_dump_json() for a in records]


@pytest.mark.parametrize("backend", ["memory", "redis"])
def test_preserves_both_original_audits_and_global_5000_bytes(tmp_path, backend):
    store, campaign, cohort, envelope, binding, service = rig(tmp_path, backend)
    old = seed_global_at_cap(store)
    receipt = service.ingest(envelope, actor="LOCAL-OPERATOR")
    assert receipt.inserted == 1 and receipt.max_attempts == 1 and service.verify(receipt).valid
    history = store.list_campaign_audit(CID, limit=1000)
    assert [a.event_type for a in reversed(history[:2])] == ["source_touchpoints_ingested", "signed_delivery_received"]
    assert store.list_campaign_audit(CID, limit=1000) == history
    for audit in history[:2]:
        original = verify_audit(audit, binding, receipt)
        assert audit.actor == original.actor and audit.created_at == original.created_at
        assert audit.event_id == original.event_id and audit.detail == original.detail
        assert audit.metadata["source_occurred_at"] == T0.isoformat()
        assert audit.metadata["subject_ref"] == cohort.subject_ref
        assert audit.metadata["receipt_id"] == receipt.receipt_id
    if isinstance(store, MemoryHubStore):
        assert [a.model_dump_json() for a in store.attribution_audit] == old
    else:
        assert store.redis.lrange(store._key("attribution-os", "audit"), 0, -1) == old
    assert len(store.list_touchpoints(lead_id=LEAD, limit=10)) == 1
    assert service.attribution.status().touchpoint_count == 0
    assert service.attribution.identity_status().touchpoint_count == 0
    assert service.attribution.list_touchpoints(campaign_id=CID) == []
    assert len(service.attribution.list_touchpoints(lead_id=LEAD)) == 1


@pytest.mark.parametrize("backend", ["memory", "redis"])
@pytest.mark.parametrize("minutes,expected", [(0, "pending"), (15, "pending"), (16, "overdue_missing_evidence")])
def test_internal_authentic_shaped_clock_keeps_exact_sla_semantics(tmp_path, backend, minutes, expected):
    store, _, cohort, envelope, _, service = rig(tmp_path, backend)
    service.ingest(envelope, actor="LOCAL-OPERATOR")
    result = SalesIntelligenceService(store).preview(SalesIntelligencePreviewRequest(
        subject_ref=cohort.subject_ref, as_of=T0 + timedelta(minutes=minutes)))
    assert result.first_response_sla.deadline_at == T0 + timedelta(minutes=15)
    assert result.first_response_sla.status.value == expected
    fields = {**report_sla_fields(result), "completeness_verified": result.completeness_verified}
    assert validate_first_response_sla(fields, report_as_of=result.as_of.isoformat())["truthful"]


@pytest.mark.parametrize("backend", ["memory", "redis"])
@pytest.mark.parametrize("defect", [
    "customer", "wrong_campaign", "missing_classification", "missing_marker", "forged_marker",
    "nonzero_budget", "ambiguous_campaign", "wrong_delivery", "wrong_event", "wrong_proof",
    "backdate", "naive_clock", "retry", "multiple_events", "missing_allowlist", "bad_allowlist",
])
def test_internal_denial_is_before_any_business_write_and_never_falls_back(tmp_path, backend, defect):
    store, campaign, cohort, envelope, binding, service = rig(tmp_path, backend)
    event = envelope.events[0]
    if defect == "customer":
        event = event.model_copy(update={"lead_id": "LOCAL-CUSTOMER-REJECTED"})
    elif defect == "wrong_campaign":
        event = event.model_copy(update={"canonical_campaign_id": "CMP-OTHER-WRONG-202609-01"})
    elif defect == "missing_classification":
        store.save_campaign(campaign.model_copy(update={"internal_cohort": None}))
    elif defect in {"missing_marker", "forged_marker", "wrong_proof"}:
        metadata = dict(event.metadata)
        if defect == "missing_marker": metadata.pop("phase9_internal_cohort")
        elif defect == "forged_marker": metadata["phase9_internal_cohort"] = {"classification": "customer"}
        else: metadata["source_audit_sha256"] = "0" * 64
        event = event.model_copy(update={"metadata": metadata})
    elif defect == "nonzero_budget":
        store.save_campaign(campaign.model_copy(update={"budget": CampaignBudget(amount=1)}))
    elif defect == "ambiguous_campaign":
        event = event.model_copy(update={"utm_campaign": "ambiguous-alternative"})
    elif defect == "wrong_event": event = event.model_copy(update={"source_event_id": "LOCAL-WRONG-EVENT"})
    elif defect == "backdate": event = event.model_copy(update={"occurred_at": T0 - timedelta(days=1)})
    elif defect == "naive_clock": event = event.model_copy(update={"occurred_at": T0.replace(tzinfo=None)})
    elif defect == "missing_allowlist": object.__setattr__(service.settings, "phase9_internal_cohort_binding_file", "")
    elif defect == "bad_allowlist":
        Path(service.settings.phase9_internal_cohort_binding_file).write_text("{}", encoding="utf-8")
    changes = {"events": [event]}
    if defect == "wrong_delivery": changes["delivery_id"] = "LOCAL-WRONG-DELIVERY"
    if defect == "retry": changes.update(attempt_number=2, max_attempts=2)
    if defect == "multiple_events": changes["events"] = [event, event]
    envelope = envelope.model_copy(update=changes)
    before = state(store)
    with pytest.raises(Phase9AuditDenied):
        service.ingest(envelope, actor="LOCAL-OPERATOR")
    assert state(store) == before


@pytest.mark.parametrize("backend", ["memory", "redis"])
@pytest.mark.parametrize("existing,passes", [(0, True), (1998, True), (1999, False), (2000, False)])
def test_exact_capacity_boundary_never_trims(tmp_path, backend, existing, passes):
    store, _, _, envelope, _, service = rig(tmp_path, backend)
    records = [CampaignAuditEvent(event_id=f"LOCAL-CUSTODY-{i}", campaign_id=CID,
                                 event_type="local_fixture", actor="local") for i in range(existing)]
    if isinstance(store, MemoryHubStore): store.campaign_audit[CID] = records
    else:
        store.redis.delete(store._key("campaign-os", "audit", CID))  # local fixture setup only
        if records: store.redis.rpush(store._key("campaign-os", "audit", CID), *(a.model_dump_json() for a in records))
    before = state(store)
    if passes:
        service.ingest(envelope, actor="LOCAL-OPERATOR")
        if isinstance(store, MemoryHubStore): raws = [a.model_dump_json() for a in store.campaign_audit[CID]]
        else: raws = store.redis.lrange(store._key("campaign-os", "audit", CID), 0, -1)
        assert raws[:existing] == [a.model_dump_json() for a in records]
        assert len(raws) == existing + 2
    else:
        with pytest.raises(Phase9AuditDenied, match="CAPACITY"):
            service.ingest(envelope, actor="LOCAL-OPERATOR")
        assert state(store) == before


@pytest.mark.parametrize("backend", ["memory", "redis"])
def test_consumed_delivery_and_alternative_raw_paths_reject_without_writes(tmp_path, backend):
    store, _, _, envelope, _, service = rig(tmp_path, backend)
    service.ingest(envelope, actor="LOCAL-OPERATOR")
    before = state(store)
    with pytest.raises(Phase9AuditDenied, match="REPLAY"):
        service.ingest(envelope, actor="LOCAL-OPERATOR")
    with pytest.raises(Phase9AuditDenied, match="SIGNED_DELIVERY_REQUIRED"):
        service.attribution.ingest_source_touchpoints(SourceTouchpointIngestRequest(events=envelope.events), actor="local")
    with pytest.raises(Phase9AuditDenied, match="BACKFILL"):
        service.attribution.backfill(TouchpointBackfillRequest(touchpoints=store.list_touchpoints(lead_id=LEAD)), actor="local")
    with pytest.raises(Phase9AuditDenied, match="NO_FAILURE_FALLBACK"):
        service.record_failure(AttributionDeliveryFailure(
            delivery_id=envelope.delivery_id, producer=envelope.producer, source_system="espocrm",
            attempt_number=1, max_attempts=1, occurred_at=T0, error_code="unknown"), actor="local")
    assert state(store) == before


@pytest.mark.parametrize("field", ["raw_attribution_audit_sha256", "delivery_payload_sha256", "receipt_id", "subject_ref", "owner_approval_sha256"])
def test_audit_readback_tamper_rejected(tmp_path, field):
    store, _, _, envelope, binding, service = rig(tmp_path)
    receipt = service.ingest(envelope, actor="LOCAL-OPERATOR")
    audit = store.list_campaign_audit(CID)[0]
    changed = audit.model_copy(update={"metadata": {**audit.metadata, field: "CHANGED"}})
    with pytest.raises(Phase9AuditDenied, match="MISMATCH"):
        verify_audit(changed, binding, receipt)


def test_real_watch_conflict_aborts_before_business_mutation(tmp_path, monkeypatch):
    store, _, _, envelope, _, service = rig(tmp_path, "redis")
    original_pipeline = store.redis.pipeline
    injected = False
    executions = 0
    concurrent = CampaignAuditEvent(campaign_id=CID, event_type="local_concurrent", actor="local")
    def pipeline(*args, **kwargs):
        pipe = original_pipeline(*args, **kwargs)
        execute = pipe.execute
        def conflict(*a, **kw):
            nonlocal injected, executions
            executions += 1
            if not injected:
                injected = True
                store.redis.rpush(store._key("campaign-os", "audit", CID), concurrent.model_dump_json())
            return execute(*a, **kw)
        pipe.execute = conflict
        return pipe
    before = state(store)
    monkeypatch.setattr(store.redis, "pipeline", pipeline)
    with pytest.raises(Phase9AuditDenied, match="CONCURRENT_CHANGE"):
        service.ingest(envelope, actor="LOCAL-OPERATOR")
    after = state(store)
    audit_key = store._key("campaign-os", "audit", CID)
    assert {k: v for k, v in before.items() if k != audit_key} == {k: v for k, v in after.items() if k != audit_key}
    assert len(store.list_campaign_audit(CID)) == 2  # creation + concurrent writer only
    assert executions == 1 and store.list_touchpoints(lead_id=LEAD) == []


@pytest.mark.parametrize("backend", ["memory", "redis"])
def test_two_concurrent_deliveries_have_one_winner_no_retry(tmp_path, backend, monkeypatch):
    store, _, _, envelope, _, service = rig(tmp_path, backend)
    barrier = Barrier(2)
    commit = store.commit_phase9_internal_delivery
    def synchronized(bundle):
        barrier.wait(timeout=10)
        return commit(bundle)
    monkeypatch.setattr(store, "commit_phase9_internal_delivery", synchronized)
    def run():
        try:
            service.ingest(envelope, actor="LOCAL-OPERATOR")
            return "committed"
        except Phase9AuditDenied:
            return "denied"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: run(), range(2))) == ["committed", "denied"]
    assert len(store.list_touchpoints(lead_id=LEAD)) == 1
    assert len(store.list_campaign_audit(CID)) == 3


def test_commit_has_no_trim_delete_or_separate_business_write(tmp_path, monkeypatch):
    store, _, _, envelope, _, service = rig(tmp_path, "redis")
    pipeline = store.redis.pipeline
    commands = []
    def trace(*args, **kwargs):
        pipe = pipeline(*args, **kwargs)
        execute = pipe.execute
        def save(*a, **kw):
            commands.extend([cmd[0] for cmd, options in pipe.command_stack])
            return execute(*a, **kw)
        pipe.execute = save
        return pipe
    monkeypatch.setattr(store.redis, "pipeline", trace)
    service.ingest(envelope, actor="LOCAL-OPERATOR")
    assert commands == ["SET", "ZADD", "ZADD", "ZADD", "SET", "ZADD", "SET", "ZADD", "RPUSH"]
    assert "LTRIM" not in commands and "DEL" not in commands


@pytest.mark.parametrize("backend", ["memory", "redis"])
def test_other_campaign_audit_writers_cannot_trim_internal_lane(tmp_path, backend):
    store, _, _, envelope, _, service = rig(tmp_path, backend)
    service.ingest(envelope, actor="LOCAL-OPERATOR")
    records = store.list_campaign_audit(CID)
    extra = [CampaignAuditEvent(campaign_id=CID, event_type="local", actor="local") for i in range(1997)]
    if isinstance(store, MemoryHubStore): store.campaign_audit[CID].extend(extra)
    else: store.redis.rpush(store._key("campaign-os", "audit", CID), *(a.model_dump_json() for a in extra))
    before = state(store)
    with pytest.raises(Phase9AuditDenied, match="CAPACITY"):
        store.append_campaign_audit(CampaignAuditEvent(campaign_id=CID, event_type="local", actor="local"))
    assert state(store) == before
    if isinstance(store, MemoryHubStore): oldest = store.campaign_audit[CID][:3]
    else: oldest = [CampaignAuditEvent.model_validate_json(r) for r in store.redis.lrange(store._key("campaign-os", "audit", CID), 0, 2)]
    assert oldest == list(reversed(records))


@pytest.mark.parametrize("backend", ["memory", "redis"])
def test_default_commercial_delivery_still_uses_two_global_audits(tmp_path, backend):
    store, campaign, _, envelope, _, service = rig(tmp_path, backend)
    store.save_campaign(campaign.model_copy(update={"internal_cohort": None}))
    object.__setattr__(service.settings, "phase9_internal_cohort_binding_file", "")
    event = envelope.events[0].model_copy(update={"metadata": {}, "channel": "organic"})
    receipt = service.ingest(envelope.model_copy(update={"events": [event]}), actor="LOCAL-OPERATOR")
    assert receipt.inserted == 1
    assert [a.event_type for a in reversed(store.list_attribution_audit())] == ["source_touchpoints_ingested", "signed_delivery_received"]
    assert len(store.list_campaign_audit(CID)) == 1
    assert service.attribution.status().touchpoint_count == 1


@pytest.mark.parametrize("backend", ["memory", "redis"])
def test_commercial_reports_exclude_internal_lead_and_revenue_without_redistributing_credit(tmp_path, backend):
    store, campaign, _, envelope, _, service = rig(tmp_path, backend)
    service.ingest(envelope, actor="LOCAL-OPERATOR")
    commercial_id = "CMP-LOCAL-COMMERCIAL-202609-01"
    commercial = campaign.model_copy(update={
        "campaign_id": commercial_id, "internal_cohort": None,
        "tracking": campaign.tracking.model_copy(update={"campaign_id": commercial_id}),
    })
    store.save_campaign(commercial)
    original = store.list_touchpoints(lead_id=LEAD)[0]
    store.append_touchpoint(original.model_copy(update={
        "event_id": "tpt_" + sha("LOCAL-COMMERCIAL-EVENT")[:32], "campaign_id": commercial_id,
        "lead_id": "LOCAL-COMMERCIAL-LEAD", "metadata": {},
    }))
    observations = [OpportunityObservation(
        opportunity_id=f"LOCAL-OPP-{index}", lead_id=lead, stage="Closed Won", status="won",
        amount=amount, observed_at=T0, closed_at=T0,
    ) for index, (lead, amount) in enumerate([(LEAD, 9999), ("LOCAL-COMMERCIAL-LEAD", 100)])]
    reconciliation = service.attribution.reconcile(ReconciliationRequest(observations=observations), actor="local")
    assert reconciliation.quality.total_opportunities == 1
    assert [o.lead_id for o in reconciliation.observations] == ["LOCAL-COMMERCIAL-LEAD"]
    service.attribution.accept_quality(reconciliation.reconciliation_id, AttributionAcceptanceRequest(accepted=True), actor="local")
    for model in AttributionModel:
        report = service.attribution.report(reconciliation.reconciliation_id, model=model)
        assert report.attributed_revenue == 100 and report.attributed_opportunities == 1
        assert [c.campaign_id for c in report.campaigns] == [commercial_id]
    assert service.attribution.status().touchpoint_count == 1
    before = state(store)
    with pytest.raises(Phase9AuditDenied, match="NON_COMMERCIAL_RECONCILIATION"):
        service.attribution.reconcile(ReconciliationRequest(observations=observations[:1]), actor="local")
    assert state(store) == before


def test_forged_marker_on_unclassified_default_traffic_is_denied_without_fallback(tmp_path):
    store, campaign, _, envelope, _, service = rig(tmp_path)
    store.save_campaign(campaign.model_copy(update={"internal_cohort": None}))
    object.__setattr__(service.settings, "phase9_internal_cohort_binding_file", "")
    before = state(store)
    with pytest.raises(Phase9AuditDenied, match="NO_APPROVED_ALLOWLIST"):
        service.ingest(envelope, actor="local")
    assert state(store) == before


@pytest.mark.parametrize("changed", [
    {"customer_contact": True}, {"commercial_attribution": True}, {"automation_enabled": True},
    {"classification": "customer"}, {"reporting_exclusions": {"commercial_leads": False}},
    {"untrusted_extra": True},
])
def test_typed_classification_cannot_enable_customer_attribution_or_actions(tmp_path, changed):
    _, _, cohort, _, _, _ = rig(tmp_path)
    with pytest.raises(ValidationError):
        Phase9InternalCohort.model_validate({**cohort.model_dump(mode="json"), **changed})


@pytest.mark.parametrize("target", ["campaign", "audit", "event_index", "snapshot_index", "receipt_index"])
def test_wrong_redis_type_cannot_partially_write_transaction(tmp_path, target):
    store, _, _, envelope, _, service = rig(tmp_path, "redis")
    keys = {"campaign": store._key("campaign-os", "campaign", CID),
            "audit": store._key("campaign-os", "audit", CID),
            "event_index": store._key("attribution-os", "touchpoints"),
            "snapshot_index": store._key("attribution-os", "data-quality-snapshots"),
            "receipt_index": store._key("attribution-os", "delivery-receipts")}
    store.redis.delete(keys[target])
    if target == "campaign": store.redis.set(keys[target], "malformed-campaign")
    else: store.redis.set(keys[target], "wrong-type")
    before = state(store)
    with pytest.raises(Phase9AuditDenied):
        service.ingest(envelope, actor="local")
    assert state(store) == before


@pytest.mark.parametrize("backend", ["memory", "redis"])
@pytest.mark.parametrize("changed", ["campaign", "registry"])
def test_campaign_or_identity_registry_changed_during_preparation_aborts(tmp_path, backend, changed, monkeypatch):
    store, campaign, _, envelope, _, service = rig(tmp_path, backend)
    commit = store.commit_phase9_internal_delivery
    expected_after_external_writer = None
    def change(bundle):
        nonlocal expected_after_external_writer
        if changed == "campaign":
            store.save_campaign(campaign.model_copy(update={"objective": "Changed by concurrent local writer"}))
        else:
            store.save_identity_mapping(CampaignIdentityMapping(
                source_system=IdentitySource.ESPOCRM, source_campaign_id="unrelated-existing-id",
                campaign_id=CID, project="Local", verified_by="local", note="local concurrency fixture",
            ))
        expected_after_external_writer = state(store)
        return commit(bundle)
    monkeypatch.setattr(store, "commit_phase9_internal_delivery", change)
    with pytest.raises(Phase9AuditDenied, match="CHANGED"):
        service.ingest(envelope, actor="local")
    assert state(store) == expected_after_external_writer


def test_internal_classification_api_requires_owner_not_role_string_spoofing(tmp_path, monkeypatch):
    from npd_agent_hub.main import app
    from npd_agent_hub.orchestrator import hub
    store, _, cohort, _, _, _ = rig(tmp_path)
    request = CampaignCreate(
        name="P9 SLA Cohort", project="Local static acceptance", project_code="AHINTERNAL",
        objective="Non-customer local acceptance", audience=["Internal"], budget=CampaignBudget(amount=0),
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 30),
        kpi_targets=[KPITarget(name="Internal SLA", target=1, unit="case", funnel_stage="lead")],
        owner=cohort.owner_id, internal_cohort=cohort,
    )
    empty = MemoryHubStore()
    monkeypatch.setattr(hub, "campaigns", CampaignService(empty))
    monkeypatch.setattr(authorizer, "settings", HubSettings(auth_mode="static_token",
        viewer_token="LOCAL-VIEWER", operator_token="LOCAL-OPERATOR", owner_token="LOCAL-OWNER"))
    with TestClient(app) as client:
        for token in ["LOCAL-VIEWER", "LOCAL-OPERATOR"]:
            response = client.post("/api/v1/campaigns", json=request.model_dump(mode="json"),
                                   headers={"Authorization": f"Bearer {token}", "X-Role": "owner"})
            assert response.status_code == 403 and empty.campaigns == {}
        response = client.post("/api/v1/campaigns", json=request.model_dump(mode="json"),
                               headers={"Authorization": "Bearer LOCAL-OWNER"})
        assert response.status_code == 201
        assert empty.get_campaign(CID).internal_cohort == cohort


@pytest.mark.parametrize("backend", ["memory", "redis"])
def test_utm_resolution_cannot_enter_internal_campaign_through_default_or_raw_ingest(tmp_path, backend):
    store, campaign, _, envelope, _, service = rig(tmp_path, backend)
    object.__setattr__(service.settings, "phase9_internal_cohort_binding_file", "")
    event = envelope.events[0].model_copy(update={
        "canonical_campaign_id": None, "utm_campaign": campaign.tracking.utm_campaign,
        "metadata": {}, "lead_id": "LOCAL-UNAPPROVED-SUBJECT",
    })
    before = state(store)
    with pytest.raises(Phase9AuditDenied, match="NO_APPROVED_ALLOWLIST"):
        service.ingest(envelope.model_copy(update={"events": [event]}), actor="local")
    with pytest.raises(Phase9AuditDenied, match="SIGNED_DELIVERY_REQUIRED"):
        service.attribution.ingest_source_touchpoints(SourceTouchpointIngestRequest(events=[event]), actor="local")
    assert state(store) == before


def test_signed_receipt_audit_raw_bytes_and_context_are_not_interchangeable(tmp_path, monkeypatch):
    store, _, _, envelope, _, service = rig(tmp_path)
    commit = store.commit_phase9_internal_delivery
    def tamper(bundle):
        audit = bundle.audits[0]
        raw = json.dumps(json.loads(audit.metadata["original_attribution_audit_json"]), indent=2)
        changed = audit.model_copy(update={"metadata": {**audit.metadata,
            "original_attribution_audit_json": raw, "raw_attribution_audit_sha256": sha(raw)}})
        return commit(replace(bundle, audits=(changed, bundle.audits[1])))
    monkeypatch.setattr(store, "commit_phase9_internal_delivery", tamper)
    before = state(store)
    with pytest.raises(Phase9AuditDenied, match="AUDIT_READBACK_MISMATCH"):
        service.ingest(envelope, actor="local")
    assert state(store) == before


def test_phase9_task_report_uses_internal_exact_subject_without_external_execution(tmp_path):
    import asyncio
    from npd_agent_hub.orchestrator import AgentHub
    from test_phase9_marketing_review import ForbiddenExternalExecutor, pilot_task
    store, _, cohort, envelope, _, service = rig(tmp_path)
    service.ingest(envelope, actor="LOCAL-OPERATOR")
    hub = AgentHub(store=store, executor=ForbiddenExternalExecutor())
    task = pilot_task(SalesIntelligencePreviewRequest(subject_ref=cohort.subject_ref,
                      as_of=T0 + timedelta(minutes=16)))
    planned = hub.run(task)
    report = asyncio.run(hub.analyze(planned.task_id))
    serialized = report.model_dump_json()
    assert "overdue_missing_evidence" in serialized
    assert "first_response_sla_deadline_at" in serialized
    assert len(store.tasks) == 1 and len(store.reports) == 1


@pytest.mark.parametrize("backend", ["memory", "redis"])
@pytest.mark.parametrize("existing,passes", [(0, True), (1997, True), (1998, False), (2000, False)])
def test_internal_campaign_creation_guards_capacity_before_first_campaign_write(tmp_path, backend, existing, passes):
    _, campaign, cohort, _, _, _ = rig(tmp_path)
    store = MemoryHubStore() if backend == "memory" else RedisHubStore(
        client=fakeredis.FakeRedis(decode_responses=True), namespace="LOCAL-CREATION")
    request = CampaignCreate.model_validate({**campaign.model_dump(), "owner":cohort.owner_id})
    records = [CampaignAuditEvent(event_id=f"LOCAL-OLD-{i}",campaign_id=CID,event_type="local",actor="local") for i in range(existing)]
    if isinstance(store, MemoryHubStore): store.campaign_audit[CID] = records
    elif records: store.redis.rpush(store._key("campaign-os","audit",CID),*(a.model_dump_json() for a in records))
    before = state(store)
    if passes:
        created = CampaignService(store).create(request,actor="LOCAL-OWNER",owner_authorized=True)
        assert created.campaign_id == CID
        count = len(store.campaign_audit[CID]) if isinstance(store,MemoryHubStore) else store.redis.llen(store._key("campaign-os","audit",CID))
        assert count == existing+1
    else:
        with pytest.raises(Phase9AuditDenied,match="CAPACITY"):
            CampaignService(store).create(request,actor="LOCAL-OWNER",owner_authorized=True)
        assert state(store) == before and store.get_campaign(CID) is None


def test_internal_campaign_creation_watch_conflict_writes_no_campaign(tmp_path, monkeypatch):
    _,campaign,cohort,_,_,_ = rig(tmp_path)
    request = CampaignCreate.model_validate({**campaign.model_dump(),"owner":cohort.owner_id})
    store=RedisHubStore(client=fakeredis.FakeRedis(decode_responses=True),namespace="LOCAL-CREATION")
    pipeline=store.redis.pipeline
    def conflict(*a,**kw):
        pipe=pipeline(*a,**kw)
        execute=pipe.execute
        def fail(*a,**kw):
            store.redis.rpush(store._key("campaign-os","audit",CID),CampaignAuditEvent(campaign_id=CID,event_type="local_concurrent",actor="local").model_dump_json())
            return execute(*a,**kw)
        pipe.execute=fail
        return pipe
    monkeypatch.setattr(store.redis,"pipeline",conflict)
    with pytest.raises(Phase9AuditDenied,match="CONCURRENT_CHANGE"):
        CampaignService(store).create(request,actor="LOCAL-OWNER",owner_authorized=True)
    assert store.get_campaign(CID) is None
    assert store.redis.zcard(store._key("campaign-os","campaigns")) == 0
    assert store.redis.llen(store._key("campaign-os","audit",CID)) == 1


@pytest.mark.parametrize("backend", ["memory", "redis"])
def test_internal_campaign_lifecycle_cannot_save_before_denied_audit(tmp_path, backend):
    store,_,_,_,_,_=rig(tmp_path,backend)
    service=CampaignService(store,execution_enabled=True)
    before=state(store)
    attempts=[lambda:service.update_draft(CID,CampaignDraftUpdate(objective="Changed"),actor="local"),
              lambda:service.refresh_plans(CID,actor="local"),
              lambda:service.request_approval(CID,scope="campaign",actor="local"),
              lambda:service.decide_approval(CID,scope="campaign",decision=CampaignApprovalDecision(approved=True),actor="local"),
              lambda:service.transition(CID,target=CampaignStatus.CANCELLED,actor="local",owner_authorized=True)]
    for attempt in attempts:
        with pytest.raises(ValueError): attempt()
        assert state(store) == before
