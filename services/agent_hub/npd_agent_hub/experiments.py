from __future__ import annotations

from datetime import datetime, timezone

from .experiment_models import (
    Experiment,
    ExperimentApprovalDecision,
    ExperimentAuditEvent,
    ExperimentCreate,
    ExperimentDraftUpdate,
    ExperimentOSStatus,
    ExperimentPreview,
    ExperimentStatus,
)
from .store import HubStore


class ExperimentService:
    """Plan/preview-only experiment control plane backed by accepted attribution."""

    def __init__(self, store: HubStore) -> None:
        self.store = store

    def _audit(
        self,
        experiment: Experiment,
        *,
        event_type: str,
        actor: str,
        detail: str,
        metadata: dict[str, object] | None = None,
    ) -> None:
        self.store.append_experiment_audit(
            ExperimentAuditEvent(
                experiment_id=experiment.experiment_id,
                event_type=event_type,
                actor=actor,
                detail=detail,
                metadata=metadata or {},
            )
        )

    def _accepted_source(self, request: ExperimentCreate) -> None:
        if self.store.get_campaign(request.campaign_id) is None:
            raise KeyError("campaign")
        reconciliation = self.store.get_attribution_reconciliation(
            request.attribution_reconciliation_id
        )
        if reconciliation is None:
            raise KeyError("reconciliation")
        if not reconciliation.accepted or reconciliation.state != "quality_accepted":
            raise ValueError("experiment planning requires an owner-accepted attribution snapshot")
        if not any(
            request.campaign_id in match.campaign_ids for match in reconciliation.matches
        ):
            raise ValueError("accepted attribution snapshot does not cover the Campaign")

    def _next_id(self, campaign_id: str) -> str:
        parts = campaign_id.split("-")
        project_code, period = parts[1], parts[-2]
        prefix = f"EXP-{project_code}-{period}-"
        existing = {
            item.experiment_id
            for item in self.store.list_experiments(limit=1000)
            if item.experiment_id.startswith(prefix)
        }
        for sequence in range(1, 1000):
            candidate = f"{prefix}{sequence:03d}"
            if candidate not in existing:
                return candidate
        raise ValueError("experiment sequence is exhausted for this project/month")

    def create(self, request: ExperimentCreate, *, actor: str) -> Experiment:
        self._accepted_source(request)
        experiment = Experiment(
            experiment_id=self._next_id(request.campaign_id),
            campaign_id=request.campaign_id,
            attribution_reconciliation_id=request.attribution_reconciliation_id,
            name=request.name,
            experiment_type=request.experiment_type,
            hypothesis=request.hypothesis,
            primary_metric=request.primary_metric,
            baseline_value=request.baseline_value,
            target_lift_percent=request.target_lift_percent,
            variants=request.variants,
            guardrails=request.guardrails,
            stop_conditions=request.stop_conditions,
            evaluation_window_days=request.evaluation_window_days,
            owner=request.owner,
            created_by=actor,
            updated_by=actor,
        )
        self.store.save_experiment(experiment)
        self._audit(
            experiment,
            event_type="experiment_planned",
            actor=actor,
            detail="Experiment plan created from an owner-accepted attribution snapshot.",
            metadata={"external_side_effect": False, "mode": "plan_preview"},
        )
        return experiment

    def get(self, experiment_id: str) -> Experiment:
        experiment = self.store.get_experiment(experiment_id)
        if experiment is None:
            raise KeyError(experiment_id)
        return experiment

    def list(
        self,
        *,
        limit: int = 50,
        campaign_id: str | None = None,
        status: ExperimentStatus | None = None,
    ) -> list[Experiment]:
        return self.store.list_experiments(
            limit=limit, campaign_id=campaign_id, status=status
        )

    def update_draft(
        self, experiment_id: str, update: ExperimentDraftUpdate, *, actor: str
    ) -> Experiment:
        experiment = self.get(experiment_id)
        if experiment.status not in {ExperimentStatus.PLANNED, ExperimentStatus.PREVIEWED}:
            raise ValueError("only planned or previewed experiments are draft-safe")
        changes = update.model_dump(exclude_none=True)
        updated = experiment.model_copy(
            update={
                **changes,
                "last_preview": None,
                "status": ExperimentStatus.PLANNED,
                "updated_by": actor,
                "updated_at": datetime.now(timezone.utc),
            },
            deep=True,
        )
        self.store.save_experiment(updated)
        self._audit(
            updated,
            event_type="experiment_updated",
            actor=actor,
            detail="Draft-safe experiment fields updated; previous preview invalidated.",
            metadata={"fields": sorted(changes), "external_side_effect": False},
        )
        return updated

    def preview(self, experiment_id: str, *, actor: str) -> ExperimentPreview:
        experiment = self.get(experiment_id)
        if experiment.status in {
            ExperimentStatus.REJECTED,
            ExperimentStatus.CANCELLED,
            ExperimentStatus.COMPLETED,
        }:
            raise ValueError(f"experiment cannot be previewed from status={experiment.status.value}")
        direction = experiment.primary_metric.direction.value
        multiplier = 1 + experiment.target_lift_percent / 100
        if direction == "decrease":
            multiplier = max(0, 1 - experiment.target_lift_percent / 100)
        preview = ExperimentPreview(
            experiment_id=experiment.experiment_id,
            hypothesis=experiment.hypothesis,
            primary_metric=experiment.primary_metric,
            baseline_value=experiment.baseline_value,
            target_value=round(experiment.baseline_value * multiplier, 4),
            variants=experiment.variants,
            guardrails=experiment.guardrails,
            stop_conditions=experiment.stop_conditions,
            evaluation_window_days=experiment.evaluation_window_days,
        )
        updated = experiment.model_copy(
            update={
                "status": ExperimentStatus.PREVIEWED,
                "last_preview": preview,
                "updated_by": actor,
                "updated_at": datetime.now(timezone.utc),
            },
            deep=True,
        )
        self.store.save_experiment(updated)
        self._audit(
            updated,
            event_type="experiment_previewed",
            actor=actor,
            detail="Experiment preview generated without external execution.",
            metadata={"external_side_effect": False},
        )
        return preview

    def request_approval(
        self, experiment_id: str, *, actor: str, note: str | None = None
    ) -> Experiment:
        experiment = self.get(experiment_id)
        if experiment.status not in {ExperimentStatus.PLANNED, ExperimentStatus.PREVIEWED}:
            raise ValueError("only planned or previewed experiments can request approval")
        updated = experiment.model_copy(
            update={
                "status": ExperimentStatus.AWAITING_APPROVAL,
                "approval_note": note,
                "updated_by": actor,
                "updated_at": datetime.now(timezone.utc),
            },
            deep=True,
        )
        self.store.save_experiment(updated)
        self._audit(
            updated,
            event_type="experiment_approval_requested",
            actor=actor,
            detail="Experiment plan submitted for owner review; execution remains disabled.",
            metadata={"external_side_effect": False},
        )
        return updated

    def decide_approval(
        self,
        experiment_id: str,
        decision: ExperimentApprovalDecision,
        *,
        actor: str,
    ) -> Experiment:
        experiment = self.get(experiment_id)
        if experiment.status != ExperimentStatus.AWAITING_APPROVAL:
            raise ValueError("experiment is not awaiting owner approval")
        now = datetime.now(timezone.utc)
        updated = experiment.model_copy(
            update={
                "status": ExperimentStatus.APPROVED if decision.approved else ExperimentStatus.REJECTED,
                "approval_note": decision.note,
                "approved_by": actor if decision.approved else None,
                "approved_at": now,
                "updated_by": actor,
                "updated_at": now,
            },
            deep=True,
        )
        self.store.save_experiment(updated)
        self._audit(
            updated,
            event_type="experiment_approval_decided",
            actor=actor,
            detail="Owner approved the plan only; no experiment execution was enabled."
            if decision.approved
            else "Owner rejected the experiment plan.",
            metadata={"approved": decision.approved, "external_side_effect": False},
        )
        return updated

    def history(self, experiment_id: str, *, limit: int = 100) -> list[ExperimentAuditEvent]:
        self.get(experiment_id)
        return self.store.list_experiment_audit(experiment_id, limit=limit)

    def status(self) -> ExperimentOSStatus:
        rows = self.store.list_experiments(limit=1000)
        return ExperimentOSStatus(
            experiment_count=len(rows),
            awaiting_approval=sum(item.status == ExperimentStatus.AWAITING_APPROVAL for item in rows),
            approved_plans=sum(item.status == ExperimentStatus.APPROVED for item in rows),
            previewed=sum(item.last_preview is not None for item in rows),
        )

