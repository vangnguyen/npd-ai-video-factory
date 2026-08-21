from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime, timezone

from .attribution_models import (
    AttributionAcceptanceRequest,
    AttributionAuditEvent,
    AttributionModel,
    AttributionQuality,
    AttributionReconciliation,
    AttributionReport,
    AttributionStatus,
    CampaignAttributionRow,
    OpportunityMatch,
    OpportunityObservation,
    OpportunityStatus,
    ReconciliationRequest,
    TouchpointBackfillRequest,
    TouchpointEvent,
)
from .store import HubStore


class AttributionService:
    """Immutable attribution ledger and read-only revenue reconciliation."""

    def __init__(self, store: HubStore) -> None:
        self.store = store

    def _audit(
        self,
        *,
        event_type: str,
        actor: str,
        detail: str,
        reconciliation_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        self.store.append_attribution_audit(
            AttributionAuditEvent(
                event_type=event_type,
                actor=actor,
                detail=detail,
                reconciliation_id=reconciliation_id,
                metadata=metadata or {},
            )
        )

    def backfill(
        self, request: TouchpointBackfillRequest, *, actor: str
    ) -> dict[str, int | bool]:
        seen: set[str] = set()
        pending: list[TouchpointEvent] = []
        duplicates = 0

        # Validate the complete batch before appending anything. This keeps a
        # conflict near the end of a request from leaving a partially ingested
        # ledger.
        for event in request.touchpoints:
            if event.event_id in seen:
                raise ValueError("backfill batch contains a duplicate event_id")
            seen.add(event.event_id)
            if self.store.get_campaign(event.campaign_id) is None:
                raise KeyError(event.campaign_id)
            existing = self.store.get_touchpoint(event.event_id)
            if existing is not None:
                if existing.model_dump(mode="json") != event.model_dump(mode="json"):
                    raise ValueError(
                        "touchpoint ledger is immutable; event_id payload cannot change"
                    )
                duplicates += 1
                continue
            pending.append(event)

        for event in pending:
            self.store.append_touchpoint(event)
        inserted = len(pending)
        self._audit(
            event_type="touchpoints_backfilled",
            actor=actor,
            detail="Immutable touchpoint batch recorded in shadow mode.",
            metadata={
                "inserted": inserted,
                "duplicates": duplicates,
                "external_side_effect": False,
            },
        )
        return {
            "inserted": inserted,
            "duplicates": duplicates,
            "shadow_mode": True,
            "external_writes_enabled": False,
        }

    def list_touchpoints(
        self,
        *,
        campaign_id: str | None = None,
        opportunity_id: str | None = None,
        lead_id: str | None = None,
        limit: int = 200,
    ) -> list[TouchpointEvent]:
        return self.store.list_touchpoints(
            campaign_id=campaign_id,
            opportunity_id=opportunity_id,
            lead_id=lead_id,
            limit=limit,
        )

    def _ledger_fingerprint(self) -> str:
        events = self.store.list_touchpoints(limit=5000)
        payload = "\n".join(
            sorted(event.model_dump_json() for event in events)
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def reconcile(
        self, request: ReconciliationRequest, *, actor: str
    ) -> AttributionReconciliation:
        opportunity_ids = [item.opportunity_id for item in request.observations]
        if len(set(opportunity_ids)) != len(opportunity_ids):
            raise ValueError("reconciliation requires one latest snapshot per opportunity_id")

        matches: list[OpportunityMatch] = []
        for observation in request.observations:
            events = self.store.list_touchpoints(
                opportunity_id=observation.opportunity_id, limit=1000
            )
            method = "opportunity_id"
            if not events and observation.lead_id:
                events = self.store.list_touchpoints(
                    lead_id=observation.lead_id, limit=1000
                )
                method = "lead_id"
            events = sorted(events, key=lambda item: (item.occurred_at, item.event_id))
            campaign_ids = list(dict.fromkeys(event.campaign_id for event in events))
            issues: list[str] = []
            if not campaign_ids and observation.campaign_id_hint:
                if self.store.get_campaign(observation.campaign_id_hint) is None:
                    issues.append("campaign_id_hint_not_found")
                else:
                    campaign_ids = [observation.campaign_id_hint]
                    method = "campaign_id_hint"
            if not campaign_ids:
                issues.append("no_campaign_touchpoint_match")
            if (
                observation.campaign_id_hint
                and campaign_ids
                and observation.campaign_id_hint not in campaign_ids
            ):
                issues.append("campaign_id_hint_conflicts_with_touchpoints")
            matches.append(
                OpportunityMatch(
                    opportunity_id=observation.opportunity_id,
                    campaign_ids=campaign_ids,
                    touchpoint_event_ids=[event.event_id for event in events],
                    match_method=method,
                    issues=issues,
                )
            )

        quality = self._quality(request.observations, matches)
        reconciliation = AttributionReconciliation(
            ledger_fingerprint=self._ledger_fingerprint(),
            observations=request.observations,
            matches=matches,
            quality=quality,
            state=(
                "awaiting_quality_acceptance"
                if quality.eligible_for_acceptance
                else "blocked_by_data_quality"
            ),
            created_by=actor,
        )
        self.store.save_attribution_reconciliation(reconciliation)
        self._audit(
            event_type="reconciliation_created",
            actor=actor,
            reconciliation_id=reconciliation.reconciliation_id,
            detail="Opportunity and closed-revenue snapshots reconciled in shadow mode.",
            metadata={
                "eligible_for_acceptance": quality.eligible_for_acceptance,
                "matched_opportunities": quality.matched_opportunities,
                "total_opportunities": quality.total_opportunities,
                "external_side_effect": False,
            },
        )
        return reconciliation

    @staticmethod
    def _quality(
        observations: list[OpportunityObservation], matches: list[OpportunityMatch]
    ) -> AttributionQuality:
        total = len(observations)
        matched = sum(bool(item.campaign_ids) for item in matches)
        conflicting = sum(
            "campaign_id_hint_conflicts_with_touchpoints" in item.issues
            or "campaign_id_hint_not_found" in item.issues
            for item in matches
        )
        won = [item for item in observations if item.status == OpportunityStatus.WON]
        won_covered = sum(item.amount > 0 and item.closed_at is not None for item in won)
        match_rate = round(matched / total, 4) if total else 0.0
        conflict_rate = round(conflicting / total, 4) if total else 0.0
        revenue_coverage = round(won_covered / len(won), 4) if won else 0.0
        issues: list[str] = []
        if matched != total:
            issues.append("Every opportunity must map to at least one Campaign.")
        if conflicting:
            issues.append("Campaign hints conflict with immutable touchpoint evidence.")
        if not won:
            issues.append("At least one closed-won opportunity is required for revenue acceptance.")
        elif won_covered != len(won):
            issues.append("Every closed-won opportunity needs positive reconciled revenue and closed_at.")
        eligible = total > 0 and matched == total and conflicting == 0 and bool(won) and won_covered == len(won)
        return AttributionQuality(
            total_opportunities=total,
            matched_opportunities=matched,
            unmatched_opportunities=total - matched,
            conflicting_opportunities=conflicting,
            won_opportunities=len(won),
            won_revenue_covered=won_covered,
            match_rate=match_rate,
            conflict_rate=conflict_rate,
            won_revenue_coverage_rate=revenue_coverage,
            eligible_for_acceptance=eligible,
            issues=issues,
        )

    def get_reconciliation(self, reconciliation_id: str) -> AttributionReconciliation:
        reconciliation = self.store.get_attribution_reconciliation(reconciliation_id)
        if reconciliation is None:
            raise KeyError(reconciliation_id)
        return reconciliation

    def accept_quality(
        self,
        reconciliation_id: str,
        request: AttributionAcceptanceRequest,
        *,
        actor: str,
    ) -> AttributionReconciliation:
        reconciliation = self.get_reconciliation(reconciliation_id)
        if request.accepted and not reconciliation.quality.eligible_for_acceptance:
            raise ValueError("data-quality gate is not eligible for owner acceptance")
        state = "quality_accepted" if request.accepted else "quality_rejected"
        updated = reconciliation.model_copy(
            update={
                "accepted": request.accepted,
                "accepted_by": actor,
                "acceptance_note": request.note,
                "accepted_at": datetime.now(timezone.utc),
                "state": state,
            },
            deep=True,
        )
        self.store.save_attribution_reconciliation(updated)
        self._audit(
            event_type="quality_acceptance_decided",
            actor=actor,
            reconciliation_id=reconciliation_id,
            detail="Owner accepted attribution data quality."
            if request.accepted
            else "Owner rejected attribution data quality.",
            metadata={
                "accepted": request.accepted,
                "external_side_effect": False,
            },
        )
        return updated

    def report(
        self, reconciliation_id: str, *, model: AttributionModel
    ) -> AttributionReport:
        reconciliation = self.get_reconciliation(reconciliation_id)
        if not reconciliation.accepted:
            return AttributionReport(
                reconciliation_id=reconciliation_id,
                model=model,
                state="blocked_until_owner_quality_acceptance",
                caveats=[
                    "Pipeline, revenue, CAC and ROAS remain hidden until the owner accepts the reconciliation quality gate.",
                    "This is a read-only shadow report and cannot mutate channels, CRM or customer communications.",
                ],
            )

        match_by_opportunity = {
            item.opportunity_id: item for item in reconciliation.matches
        }
        rows: dict[tuple[str, str], dict[str, float]] = defaultdict(
            lambda: {"opportunity_credit": 0.0, "pipeline": 0.0, "revenue": 0.0}
        )
        currencies = {item.currency for item in reconciliation.observations}
        if len(currencies) != 1:
            raise ValueError("one reconciliation cannot calculate across multiple currencies")
        currency = next(iter(currencies))
        for observation in reconciliation.observations:
            match = match_by_opportunity[observation.opportunity_id]
            campaign_ids = match.campaign_ids
            if not campaign_ids:
                continue
            if model == AttributionModel.FIRST_TOUCH:
                credits = [(campaign_ids[0], 1.0)]
            elif model == AttributionModel.LAST_TOUCH:
                credits = [(campaign_ids[-1], 1.0)]
            else:
                share = 1 / len(campaign_ids)
                credits = [(campaign_id, share) for campaign_id in campaign_ids]
            for campaign_id, credit in credits:
                row = rows[(campaign_id, currency)]
                row["opportunity_credit"] += credit
                if observation.status in {OpportunityStatus.OPEN, OpportunityStatus.WON}:
                    row["pipeline"] += observation.amount * credit
                if observation.status == OpportunityStatus.WON:
                    row["revenue"] += observation.amount * credit

        campaign_rows = [
            CampaignAttributionRow(
                campaign_id=campaign_id,
                opportunity_credit=round(values["opportunity_credit"], 4),
                attributed_pipeline=round(values["pipeline"], 2),
                attributed_revenue=round(values["revenue"], 2),
                currency=row_currency,
            )
            for (campaign_id, row_currency), values in sorted(rows.items())
        ]
        return AttributionReport(
            reconciliation_id=reconciliation_id,
            model=model,
            state="calculated_shadow",
            attributed_opportunities=round(
                sum(row.opportunity_credit for row in campaign_rows), 4
            ),
            attributed_pipeline=round(
                sum(row.attributed_pipeline for row in campaign_rows), 2
            ),
            attributed_revenue=round(
                sum(row.attributed_revenue for row in campaign_rows), 2
            ),
            currency=currency,
            campaigns=campaign_rows,
            caveats=[
                "Attribution is a read-only shadow calculation over an owner-accepted snapshot.",
                "CAC/ROAS require reconciled channel spend for the same Campaign and period; they are not inferred here.",
                "No Ads, CRM, CMS, Email, Zalo or customer-contact write is enabled.",
            ],
        )

    def status(self) -> AttributionStatus:
        reconciliations = self.store.list_attribution_reconciliations(limit=1)
        latest = reconciliations[0] if reconciliations else None
        return AttributionStatus(
            touchpoint_count=len(self.store.list_touchpoints(limit=5000)),
            reconciliation_count=self.store.count_attribution_reconciliations(),
            latest_reconciliation_id=latest.reconciliation_id if latest else None,
            latest_state=latest.state if latest else "not_started",
        )

    def audit(self, *, limit: int = 100) -> list[AttributionAuditEvent]:
        return self.store.list_attribution_audit(limit=limit)
