from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from .attribution_models import TouchpointEvent, TouchpointType
from .journeys import JourneyService
from .sales_intelligence_models import (
    SalesActivityObservation,
    SalesActivityType,
    SalesFunnelEvidence,
    SalesIntelligencePreviewRequest,
    SalesIntelligenceSnapshot,
    SalesSLAStatus,
    SalesSLAWindow,
)
from .store import HubStore


SALES_HUB_SOURCES = {"sales hub", "salehub", "npd sales hub"}


class SalesIntelligenceService:
    """Deterministic Phase 9B SLA/funnel preview over immutable journey evidence plus supplied sales activity evidence."""

    def __init__(self, store: HubStore, journeys: JourneyService | None = None) -> None:
        self.store = store
        self.journeys = journeys or JourneyService(store)

    @staticmethod
    def _normalize_source(value: str) -> str:
        normalized = re.sub(r"[_-]+", " ", value.strip().lower())
        return re.sub(r"\s+", " ", normalized)

    def _events(self, subject_ref: str) -> tuple[str, str, list[TouchpointEvent]]:
        parsed = self.journeys.parse_subject_ref(subject_ref)
        kwargs = (
            {"lead_id": parsed.identifier}
            if parsed.kind == "lead"
            else {"opportunity_id": parsed.identifier}
        )
        rows = self.store.list_touchpoints(limit=5000, **kwargs)
        if not rows:
            raise KeyError(subject_ref)
        rows = sorted(rows, key=lambda item: (item.occurred_at, item.event_id))
        return parsed.kind, parsed.identifier, rows

    @staticmethod
    def _lead_start(events: list[TouchpointEvent]) -> tuple[TouchpointEvent | None, str | None]:
        created = [item for item in events if item.event_type == TouchpointType.LEAD_CREATED]
        if created:
            return created[0], "lead_created"
        forms = [item for item in events if item.event_type == TouchpointType.FORM_SUBMIT]
        if forms:
            return forms[0], "form_submit_fallback"
        return None, None

    @staticmethod
    def _same_subject(
        observation: SalesActivityObservation,
        *,
        kind: str,
        identifier: str,
    ) -> bool:
        if kind == "lead":
            return observation.lead_id == identifier
        return observation.opportunity_id == identifier

    def _accepted_activities(
        self,
        request: SalesIntelligencePreviewRequest,
        *,
        kind: str,
        identifier: str,
        campaign_id: str | None,
    ) -> tuple[list[SalesActivityObservation], int, int]:
        accepted: list[SalesActivityObservation] = []
        duplicate_count = 0
        untrusted_count = 0
        seen: dict[str, str] = {}

        for item in sorted(
            request.observations,
            key=lambda row: (row.occurred_at, row.activity_id),
        ):
            fingerprint = item.model_dump_json()
            existing = seen.get(item.activity_id)
            if existing is not None:
                duplicate_count += 1
                if existing != fingerprint:
                    untrusted_count += 1
                continue
            seen[item.activity_id] = fingerprint

            if self._normalize_source(item.source_system) not in SALES_HUB_SOURCES:
                untrusted_count += 1
                continue
            if not self._same_subject(item, kind=kind, identifier=identifier):
                untrusted_count += 1
                continue
            if campaign_id is not None and item.campaign_id != campaign_id:
                untrusted_count += 1
                continue
            accepted.append(item)

        return accepted, duplicate_count, untrusted_count

    @staticmethod
    def _first(
        rows: list[SalesActivityObservation], activity_type: SalesActivityType
    ) -> SalesActivityObservation | None:
        matches = [item for item in rows if item.activity_type == activity_type]
        return matches[0] if matches else None

    @staticmethod
    def _refs(
        rows: list[SalesActivityObservation], activity_type: SalesActivityType
    ) -> list[str]:
        return [item.activity_id for item in rows if item.activity_type == activity_type]

    @staticmethod
    def _window(
        *,
        name: str,
        start_at: datetime | None,
        target_minutes: int | None,
        observed: SalesActivityObservation | None,
        evidence_refs: list[str],
        as_of: datetime,
    ) -> SalesSLAWindow:
        if start_at is None or target_minutes is None:
            return SalesSLAWindow(
                name=name,
                target_minutes=target_minutes,
                status=SalesSLAStatus.NOT_EVALUABLE,
                clock_start_at=start_at,
                evidence_refs=evidence_refs,
                caveats=[
                    "The SLA clock or Campaign OS policy is unavailable; no SLA result was inferred."
                ],
            )

        deadline = start_at + timedelta(minutes=target_minutes)
        if observed is not None:
            elapsed = max(
                0.0,
                (observed.occurred_at - start_at).total_seconds() / 60,
            )
            return SalesSLAWindow(
                name=name,
                target_minutes=target_minutes,
                status=(
                    SalesSLAStatus.MET
                    if elapsed <= target_minutes
                    else SalesSLAStatus.LATE
                ),
                clock_start_at=start_at,
                deadline_at=deadline,
                observed_at=observed.occurred_at,
                elapsed_minutes=round(elapsed, 2),
                evidence_refs=evidence_refs,
            )

        status = (
            SalesSLAStatus.PENDING
            if as_of <= deadline
            else SalesSLAStatus.OVERDUE_MISSING_EVIDENCE
        )
        caveats: list[str] = []
        if status == SalesSLAStatus.OVERDUE_MISSING_EVIDENCE:
            caveats.append(
                "The deadline passed without supplied Sales Hub activity evidence, but source completeness is not proven; this is not a confirmed SLA breach."
            )
        return SalesSLAWindow(
            name=name,
            target_minutes=target_minutes,
            status=status,
            clock_start_at=start_at,
            deadline_at=deadline,
            evidence_refs=evidence_refs,
            caveats=caveats,
        )

    def preview(self, request: SalesIntelligencePreviewRequest) -> SalesIntelligenceSnapshot:
        kind, identifier, events = self._events(request.subject_ref)
        evaluation_time = request.as_of.astimezone(timezone.utc)
        start_event, start_basis = self._lead_start(events)
        start_at = start_event.occurred_at if start_event is not None else None
        if start_at is not None and start_at.tzinfo is None:
            start_at = start_at.replace(tzinfo=timezone.utc)
        if start_at is not None:
            start_at = start_at.astimezone(timezone.utc)

        policy_campaign_id = (
            start_event.campaign_id if start_event is not None else events[0].campaign_id
        )
        campaign = self.store.get_campaign(policy_campaign_id)
        first_response_target = (
            campaign.sales_handoff.first_response_sla_minutes if campaign is not None else None
        )
        visit_booking_target = (
            campaign.sales_handoff.visit_booking_sla_hours * 60
            if campaign is not None
            else None
        )

        accepted, duplicates, untrusted = self._accepted_activities(
            request,
            kind=kind,
            identifier=identifier,
            campaign_id=policy_campaign_id,
        )
        if start_at is not None:
            before_start = [item for item in accepted if item.occurred_at < start_at]
            if before_start:
                untrusted += len(before_start)
                accepted = [item for item in accepted if item.occurred_at >= start_at]

        first_response = self._first(accepted, SalesActivityType.FIRST_RESPONSE)
        appointment = self._first(accepted, SalesActivityType.APPOINTMENT_BOOKED)
        site_visit = self._first(accepted, SalesActivityType.SITE_VISIT_COMPLETED)

        first_response_refs = self._refs(accepted, SalesActivityType.FIRST_RESPONSE)
        appointment_refs = self._refs(accepted, SalesActivityType.APPOINTMENT_BOOKED)
        site_visit_refs = self._refs(accepted, SalesActivityType.SITE_VISIT_COMPLETED)

        missing_inputs = ["sales_activity_source_completeness"]
        if start_at is None:
            missing_inputs.append("lead_start")
        if campaign is None:
            missing_inputs.append("campaign_sales_handoff_policy")
        if first_response is None:
            missing_inputs.append("first_response_evidence")
        if appointment is None:
            missing_inputs.append("appointment_booking_evidence")
        if site_visit is None:
            missing_inputs.append("site_visit_evidence")

        return SalesIntelligenceSnapshot(
            subject_ref=request.subject_ref,
            as_of=evaluation_time,
            campaign_id=policy_campaign_id,
            project=campaign.project if campaign is not None else None,
            lead_start_at=start_at,
            lead_start_basis=start_basis,
            first_response_sla=self._window(
                name="first_response",
                start_at=start_at,
                target_minutes=first_response_target,
                observed=first_response,
                evidence_refs=first_response_refs,
                as_of=evaluation_time,
            ),
            visit_booking_sla=self._window(
                name="visit_booking",
                start_at=start_at,
                target_minutes=visit_booking_target,
                observed=appointment,
                evidence_refs=appointment_refs,
                as_of=evaluation_time,
            ),
            funnel=SalesFunnelEvidence(
                first_response_at=(first_response.occurred_at if first_response else None),
                appointment_booked_at=(appointment.occurred_at if appointment else None),
                site_visit_completed_at=(site_visit.occurred_at if site_visit else None),
                first_response_refs=first_response_refs,
                appointment_refs=appointment_refs,
                site_visit_refs=site_visit_refs,
            ),
            accepted_activity_count=len(accepted),
            duplicate_activity_count=duplicates,
            untrusted_activity_count=untrusted,
            missing_inputs=sorted(set(missing_inputs)),
        )
