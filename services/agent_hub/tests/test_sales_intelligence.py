from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient

from npd_agent_hub.attribution_models import TouchpointEvent, TouchpointType
from npd_agent_hub.auth import authorizer
from npd_agent_hub.campaign_models import CampaignBudget, CampaignCreate, KPITarget
from npd_agent_hub.campaigns import CampaignService
from npd_agent_hub.config import HubSettings
from npd_agent_hub.journeys import JourneyService
from npd_agent_hub.main import app
from npd_agent_hub.orchestrator import hub
from npd_agent_hub.sales_intelligence import SalesIntelligenceService
from npd_agent_hub.sales_intelligence_models import (
    SalesActivityObservation,
    SalesActivityType,
    SalesIntelligencePreviewRequest,
    SalesSLAStatus,
)
from npd_agent_hub.store import MemoryHubStore


UTC = timezone.utc
BASE = datetime(2026, 9, 1, 8, tzinfo=UTC)


def build_store(*, with_lead_start: bool = True):
    store = MemoryHubStore()
    campaign = CampaignService(store).create(
        CampaignCreate(
            name="Vịnh Tiên Sales SLA",
            project="Vinhomes Green Paradise – Vịnh Tiên",
            project_code="VGP",
            objective="Đo SLA phản hồi và đặt lịch đi xem ở chế độ shadow",
            audience=["Nhà đầu tư"],
            budget=CampaignBudget(amount=100_000_000),
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30),
            kpi_targets=[
                KPITarget(name="Lead", target=300, unit="lead", funnel_stage="lead")
            ],
            owner="owner",
        ),
        actor="operator",
    )
    store.append_touchpoint(
        TouchpointEvent(
            event_id="tpt_" + "1" * 32,
            campaign_id=campaign.campaign_id,
            event_type=(
                TouchpointType.LEAD_CREATED if with_lead_start else TouchpointType.LANDING_VIEW
            ),
            occurred_at=BASE,
            source_system="EspoCRM" if with_lead_start else "GA4",
            channel="crm" if with_lead_start else "web",
            lead_id="lead-001",
        )
    )
    return store, campaign


def activity(
    activity_id: str,
    activity_type: SalesActivityType,
    occurred_at: datetime,
    campaign_id: str,
    *,
    source_system: str = "Sales Hub",
    lead_id: str = "lead-001",
) -> SalesActivityObservation:
    return SalesActivityObservation(
        activity_id=activity_id,
        activity_type=activity_type,
        occurred_at=occurred_at,
        source_system=source_system,
        source_record_ref=f"record-{activity_id}",
        campaign_id=campaign_id,
        lead_id=lead_id,
    )


def test_sales_sla_and_funnel_are_deterministic_from_explicit_activity_evidence():
    store, campaign = build_store()
    observations = [
        activity("act-response", SalesActivityType.FIRST_RESPONSE, BASE + timedelta(minutes=10), campaign.campaign_id),
        activity("act-appointment", SalesActivityType.APPOINTMENT_BOOKED, BASE + timedelta(hours=20), campaign.campaign_id),
        activity("act-visit", SalesActivityType.SITE_VISIT_COMPLETED, BASE + timedelta(hours=30), campaign.campaign_id),
    ]
    request = SalesIntelligencePreviewRequest(
        subject_ref="lead:lead-001",
        observations=list(reversed(observations)),
        as_of=BASE + timedelta(hours=40),
    )
    service = SalesIntelligenceService(store)

    first = service.preview(request)
    second = service.preview(request)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.campaign_id == campaign.campaign_id
    assert first.project == campaign.project
    assert first.lead_start_at == BASE
    assert first.lead_start_basis == "lead_created"
    assert first.first_response_sla.target_minutes == 15
    assert first.first_response_sla.status == SalesSLAStatus.MET
    assert first.first_response_sla.elapsed_minutes == 10
    assert first.visit_booking_sla.target_minutes == 24 * 60
    assert first.visit_booking_sla.status == SalesSLAStatus.MET
    assert first.visit_booking_sla.elapsed_minutes == 20 * 60
    assert first.funnel.first_response_at == BASE + timedelta(minutes=10)
    assert first.funnel.appointment_booked_at == BASE + timedelta(hours=20)
    assert first.funnel.site_visit_completed_at == BASE + timedelta(hours=30)
    assert first.accepted_activity_count == 3
    assert first.missing_inputs == ["sales_activity_source_completeness"]
    assert first.source_complete is False
    assert first.persisted is False
    assert first.execution_enabled is False
    assert first.external_writes_enabled is False
    assert first.customer_contact_enabled is False


def test_observed_late_response_is_late_but_missing_activity_is_not_a_confirmed_breach():
    store, campaign = build_store()
    snapshot = SalesIntelligenceService(store).preview(
        SalesIntelligencePreviewRequest(
            subject_ref="lead:lead-001",
            observations=[
                activity(
                    "act-late-response",
                    SalesActivityType.FIRST_RESPONSE,
                    BASE + timedelta(minutes=30),
                    campaign.campaign_id,
                )
            ],
            as_of=BASE + timedelta(hours=30),
        )
    )

    assert snapshot.first_response_sla.status == SalesSLAStatus.LATE
    assert snapshot.first_response_sla.elapsed_minutes == 30
    assert snapshot.visit_booking_sla.status == SalesSLAStatus.OVERDUE_MISSING_EVIDENCE
    assert "not a confirmed SLA breach" in snapshot.visit_booking_sla.caveats[0]
    assert "appointment_booking_evidence" in snapshot.missing_inputs
    assert "site_visit_evidence" in snapshot.missing_inputs


def test_untrusted_mismatched_and_duplicate_activity_evidence_cannot_change_sla():
    store, campaign = build_store()
    valid = activity(
        "act-valid",
        SalesActivityType.FIRST_RESPONSE,
        BASE + timedelta(minutes=12),
        campaign.campaign_id,
    )
    wrong_source = activity(
        "act-wrong-source",
        SalesActivityType.FIRST_RESPONSE,
        BASE + timedelta(minutes=1),
        campaign.campaign_id,
        source_system="GA4",
    )
    wrong_campaign = activity(
        "act-wrong-campaign",
        SalesActivityType.FIRST_RESPONSE,
        BASE + timedelta(minutes=2),
        "CMP-VGP-OTHER-202609-01",
    )
    wrong_subject = activity(
        "act-wrong-subject",
        SalesActivityType.FIRST_RESPONSE,
        BASE + timedelta(minutes=3),
        campaign.campaign_id,
        lead_id="lead-999",
    )
    before_start = activity(
        "act-before-start",
        SalesActivityType.FIRST_RESPONSE,
        BASE - timedelta(minutes=1),
        campaign.campaign_id,
    )

    snapshot = SalesIntelligenceService(store).preview(
        SalesIntelligencePreviewRequest(
            subject_ref="lead:lead-001",
            observations=[
                valid,
                valid,
                wrong_source,
                wrong_campaign,
                wrong_subject,
                before_start,
            ],
            as_of=BASE + timedelta(hours=2),
        )
    )

    assert snapshot.first_response_sla.status == SalesSLAStatus.MET
    assert snapshot.first_response_sla.elapsed_minutes == 12
    assert snapshot.accepted_activity_count == 1
    assert snapshot.duplicate_activity_count == 1
    assert snapshot.untrusted_activity_count == 4
    assert snapshot.funnel.first_response_refs == ["act-valid"]


def test_missing_lead_start_is_reported_missing_instead_of_inferred():
    store, campaign = build_store(with_lead_start=False)
    snapshot = SalesIntelligenceService(store).preview(
        SalesIntelligencePreviewRequest(
            subject_ref="lead:lead-001",
            observations=[
                activity(
                    "act-response",
                    SalesActivityType.FIRST_RESPONSE,
                    BASE + timedelta(minutes=10),
                    campaign.campaign_id,
                )
            ],
            as_of=BASE + timedelta(hours=2),
        )
    )

    assert snapshot.lead_start_at is None
    assert snapshot.first_response_sla.status == SalesSLAStatus.NOT_EVALUABLE
    assert snapshot.visit_booking_sla.status == SalesSLAStatus.NOT_EVALUABLE
    assert "lead_start" in snapshot.missing_inputs


def test_sales_intelligence_api_is_operator_only_non_persisting_and_no_store_mutation():
    previous_settings = authorizer.settings
    previous_store = hub.store
    previous_journeys = hub.journeys
    authorizer.settings = HubSettings(
        auth_mode="static_token",
        viewer_token="viewer-secret",
        operator_token="operator-secret",
        owner_token="owner-secret",
    )
    store, campaign = build_store()
    hub.store = store
    hub.journeys = JourneyService(store)
    client = TestClient(app)
    viewer = {"Authorization": "Bearer viewer-secret"}
    operator = {"Authorization": "Bearer operator-secret"}
    payload = {
        "subject_ref": "lead:lead-001",
        "as_of": (BASE + timedelta(hours=2)).isoformat(),
        "observations": [
            {
                "activity_id": "act-response",
                "activity_type": "first_response",
                "occurred_at": (BASE + timedelta(minutes=10)).isoformat(),
                "source_system": "Sales Hub",
                "source_record_ref": "record-response",
                "campaign_id": campaign.campaign_id,
                "lead_id": "lead-001",
            }
        ],
    }
    try:
        before_touchpoints = [
            item.model_dump(mode="json")
            for item in store.list_touchpoints(lead_id="lead-001", limit=100)
        ]
        before_tasks = store.list_recent_tasks(100)

        assert (
            client.post(
                "/api/v1/sales-intelligence/preview",
                headers=viewer,
                json=payload,
            ).status_code
            == 403
        )
        response = client.post(
            "/api/v1/sales-intelligence/preview",
            headers=operator,
            json=payload,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["first_response_sla"]["status"] == "met"
        assert body["persisted"] is False
        assert body["execution_enabled"] is False
        assert body["external_writes_enabled"] is False
        assert body["customer_contact_enabled"] is False
        assert response.headers["cache-control"] == "no-store"

        after_touchpoints = [
            item.model_dump(mode="json")
            for item in store.list_touchpoints(lead_id="lead-001", limit=100)
        ]
        assert after_touchpoints == before_touchpoints
        assert store.list_recent_tasks(100) == before_tasks

        bad = dict(payload)
        bad["subject_ref"] = "lead:user@example.com"
        assert (
            client.post(
                "/api/v1/sales-intelligence/preview",
                headers=operator,
                json=bad,
            ).status_code
            == 422
        )
    finally:
        authorizer.settings = previous_settings
        hub.store = previous_store
        hub.journeys = previous_journeys


def test_sales_intelligence_openapi_is_preview_only_with_no_execution_route():
    paths = app.openapi()["paths"]
    sales_paths = {
        path: set(operations)
        for path, operations in paths.items()
        if path.startswith("/api/v1/sales-intelligence")
    }
    assert sales_paths == {"/api/v1/sales-intelligence/preview": {"post"}}
    forbidden = ("execute", "contact", "send", "accept")
    assert not any(any(word in path for word in forbidden) for path in sales_paths)
