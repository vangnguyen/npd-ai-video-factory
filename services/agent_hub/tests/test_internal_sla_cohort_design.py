"""RCA16 static schema/evaluator evidence; no CRM/delivery/source action executed."""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest
from npd_agent_hub.attribution_models import SourceTouchpointEvent, TouchpointEvent
from npd_agent_hub.campaign_models import CampaignBudget, CampaignCreate, KPITarget, SalesHandoff
from npd_agent_hub.campaigns import CampaignService
from npd_agent_hub.delivery_models import AttributionDeliveryEnvelope
from npd_agent_hub.sales_intelligence import SalesIntelligenceService
from npd_agent_hub.sales_intelligence_models import SalesIntelligencePreviewRequest
from npd_agent_hub.sales_sla_contract import BROWSER_SLA_LABELS, report_sla_fields, validate_first_response_sla
from npd_agent_hub.store import MemoryHubStore
from test_sales_intelligence import activity
from npd_agent_hub.sales_intelligence_models import SalesActivityType

PATH = Path(__file__).with_name("fixtures") / "internal_sla_cohort_design.json"
DESIGN = json.loads(PATH.read_bytes())
T0 = datetime.fromisoformat(DESIGN["source"]["original_created_at_UTC"])


def static_store(clock=True, fallback=False):
    store = MemoryHubStore()
    plan = DESIGN["campaign"]
    campaign = CampaignService(store).create(CampaignCreate(
        name=plan["name"], project=plan["project"], project_code=plan["project_code"],
        objective=plan["purpose"], audience=["static_authenticated_internal_owner_team"],
        budget=CampaignBudget(amount=0), start_date=date(2026, 9, 14), end_date=date(2026, 9, 21),
        kpi_targets=[KPITarget(name="Internal SLA evidence", target=1, unit="internal_subject", funnel_stage="internal")],
        owner=plan["owner"]), actor="static_operator")
    assert campaign.campaign_id == plan["proposed_campaign_id"]
    campaign = campaign.model_copy(update={"sales_handoff": SalesHandoff(first_response_sla_minutes=15,
        owner_rule="Exact internal owner allowlist only; no customer or CRM routing action")})
    store.save_campaign(campaign)
    source_event = SourceTouchpointEvent(
        source_event_id="static_native_creation_event_001", source_system="espocrm",
        event_type="form_submit" if fallback else "lead_created" if clock else "opportunity_stage_changed",
        occurred_at=T0, channel="crm", canonical_campaign_id=campaign.campaign_id,
        lead_id=DESIGN["source"]["static_record_id"],
        metadata={"fixture_kind": "SYNTHETIC_LOCAL_ONLY", "source_custody_sha256": hashlib.sha256(PATH.read_bytes()).hexdigest()})
    envelope = AttributionDeliveryEnvelope(
        delivery_id="static_internal_delivery_001", producer="espocrm", source_system="espocrm",
        attempt_number=1, max_attempts=1, sent_at=T0, events=[source_event], metadata={"fixture_kind": "SYNTHETIC_LOCAL_ONLY"})
    assert len(envelope.events) == envelope.max_attempts == envelope.attempt_number == 1
    # Local fixture adapts the validated schema only; no actual delivery/ingest is called.
    store.append_touchpoint(TouchpointEvent(event_id="tpt_" + "c" * 32, campaign_id=campaign.campaign_id,
        event_type=source_event.event_type, occurred_at=source_event.occurred_at,
        source_system="EspoCRM", channel="crm", lead_id=source_event.lead_id,
        metadata={"fixture_kind": "SYNTHETIC_LOCAL_ONLY"}))
    return store, campaign, source_event


@pytest.mark.parametrize("case", DESIGN["cases"], ids=lambda c: c["name"])
def test_exact_static_source_to_evaluator_report_API_browser_contract(case):
    store, campaign, event = static_store(case["clock"])
    observations = [] if case["response_minutes"] is None else [activity(
        "static_response_001", SalesActivityType.FIRST_RESPONSE, T0 + timedelta(minutes=case["response_minutes"]),
        campaign.campaign_id, lead_id=event.lead_id)]
    request = SalesIntelligencePreviewRequest(subject_ref="lead:" + event.lead_id,
        observations=observations, as_of=T0 + timedelta(minutes=case["as_of_minutes"]))
    snapshot = SalesIntelligenceService(store).preview(request)
    fields = {**report_sla_fields(snapshot), "completeness_verified": snapshot.completeness_verified}
    check = validate_first_response_sla(fields, report_as_of=snapshot.as_of.isoformat())
    assert check["truthful"] and fields["first_response_sla"] == case["expected"]
    assert snapshot.first_response_sla.status.value == case["expected"]
    API = json.loads(snapshot.model_dump_json())
    assert API["first_response_sla"]["status"] == case["expected"]
    assert BROWSER_SLA_LABELS[API["first_response_sla"]["status"]]
    assert snapshot.persisted is snapshot.execution_enabled is snapshot.external_writes_enabled is False
    if case["clock"]:
        assert snapshot.lead_start_basis == "lead_created"
        assert snapshot.first_response_sla.deadline_at == T0 + timedelta(minutes=15)
    else:
        assert snapshot.first_response_sla.deadline_at is None
        assert check["classification"] == "SLA_CLOCK_UNAVAILABLE"
    assert check["overdue_missing_evidence_covered"] == (case["expected"] == "overdue_missing_evidence")
    assert check["execution_authorized"] is False


def test_existing_form_submit_fallback_is_schema_supported_not_a_verified_internal_form_path():
    store, _, event = static_store(fallback=True)
    snapshot = SalesIntelligenceService(store).preview(SalesIntelligencePreviewRequest(
        subject_ref="lead:" + event.lead_id, as_of=T0 + timedelta(minutes=16)))
    assert snapshot.lead_start_basis == "form_submit_fallback"
    assert snapshot.first_response_sla.status.value == "overdue_missing_evidence"
    assert DESIGN["owner_cohort_creation"] == "NOT_GRANTED"


def test_timezone_boundary_keeps_pending_at_exact_deadline():
    store, _, event = static_store()
    for micros, expected in [(0, "pending"), (1, "overdue_missing_evidence")]:
        request = SalesIntelligencePreviewRequest(subject_ref="lead:" + event.lead_id,
            as_of=(T0 + timedelta(minutes=15, microseconds=micros)).astimezone(timezone(timedelta(hours=7))))
        assert SalesIntelligenceService(store).preview(request).first_response_sla.status.value == expected


def test_clockless_static_subject_cannot_be_mapped_to_overdue_acceptance():
    store, _, event = static_store(clock=False)
    snapshot = SalesIntelligenceService(store).preview(SalesIntelligencePreviewRequest(
        subject_ref="lead:" + event.lead_id, as_of=T0 + timedelta(days=1)))
    fields = {**report_sla_fields(snapshot), "completeness_verified": False}
    fields["first_response_sla"] = "overdue_missing_evidence"
    assert not validate_first_response_sla(fields, report_as_of=snapshot.as_of.isoformat())["truthful"]


def test_schema_fixture_and_campaign_name_never_grant_non_customer_or_execution_authority():
    assert DESIGN["artifact_kind"] == "SYNTHETIC_LOCAL_STATIC_DESIGN_NOT_PRODUCTION_EVIDENCE"
    assert DESIGN["owner_policy_adoption"] == DESIGN["owner_cohort_creation"] == "NOT_GRANTED"
    assert DESIGN["execution_authorized"] is False and DESIGN["production_writes"] == 0
    assert "REQUIRES_FUTURE_ENFORCEMENT" in DESIGN["campaign"]["production_reporting_exclusion"]
    assert len(DESIGN["positive_non_customer_proof_required"]) == 5
