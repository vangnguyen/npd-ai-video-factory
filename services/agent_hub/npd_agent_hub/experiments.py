from __future__ import annotations

from datetime import datetime, timezone
from math import erfc, sqrt
from collections.abc import Callable

from .experiment_models import (
    Experiment,
    ExperimentApprovalDecision,
    ExperimentAuditEvent,
    ExperimentCreate,
    ExperimentDraftUpdate,
    ExperimentEvaluation,
    ExperimentEvaluationRequest,
    ExperimentObservation,
    ExperimentObservationCreate,
    ExperimentOSStatus,
    ExperimentPreview,
    ExperimentStatus,
    MetricDirection,
    ObservationState,
    RecommendationAction,
    VariantObservation,
)
from .store import HubStore


class ExperimentService:
    """Plan/preview-only experiment control plane backed by accepted attribution."""

    def __init__(
        self,
        store: HubStore,
        *,
        source_status_provider: Callable[[], dict[str, str]] | None = None,
    ) -> None:
        self.store = store
        self.source_status_provider = source_status_provider

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

    def _observation_sources(self) -> dict[str, str]:
        configured = self.source_status_provider() if self.source_status_provider else {}
        return {
            "ga4": "partial" if configured.get("ga4") == "configured" else "not_configured",
            "meta_ads": "partial"
            if configured.get("meta_ads") == "configured"
            else "not_configured",
            "verified_import": "read_only",
        }

    def add_observation(
        self,
        experiment_id: str,
        request: ExperimentObservationCreate,
        *,
        actor: str,
    ) -> ExperimentObservation:
        experiment = self.get(experiment_id)
        expected_ids = {item.variant_id for item in experiment.variants}
        observed_ids = {item.variant_id for item in request.variants}
        if not observed_ids.issubset(expected_ids):
            raise ValueError("observation contains a variant outside the experiment plan")
        if request.source_state == ObservationState.VERIFIED_READ_ONLY and observed_ids != expected_ids:
            raise ValueError("verified observation must cover every planned variant")
        observation = ExperimentObservation(
            experiment_id=experiment_id,
            ingested_by=actor,
            **request.model_dump(),
        )
        updated = experiment.model_copy(
            update={
                "observations": [*experiment.observations, observation][-100:],
                "last_evaluation": None,
                "updated_by": actor,
                "updated_at": datetime.now(timezone.utc),
            },
            deep=True,
        )
        self.store.save_experiment(updated)
        self._audit(
            updated,
            event_type="experiment_observation_ingested",
            actor=actor,
            detail="Read-only variant observation attached; no source system was changed.",
            metadata={
                "observation_id": observation.observation_id,
                "source_system": observation.source_system.value,
                "source_state": observation.source_state.value,
                "variant_count": len(observation.variants),
                "contains_raw_pii": False,
                "external_side_effect": False,
            },
        )
        return observation

    def observations(
        self, experiment_id: str, *, limit: int = 50
    ) -> list[ExperimentObservation]:
        experiment = self.get(experiment_id)
        limit = max(1, min(limit, 100))
        return [item.model_copy(deep=True) for item in experiment.observations[-limit:]][::-1]

    @staticmethod
    def _metric_value(item: VariantObservation) -> float:
        if item.conversions is not None and item.sample_size:
            return item.conversions * 100 / item.sample_size
        return float(item.metric_value or 0)

    @staticmethod
    def _two_proportion_p_value(
        control: VariantObservation, challenger: VariantObservation
    ) -> float | None:
        if (
            control.conversions is None
            or challenger.conversions is None
            or control.sample_size == 0
            or challenger.sample_size == 0
        ):
            return None
        pooled = (control.conversions + challenger.conversions) / (
            control.sample_size + challenger.sample_size
        )
        standard_error = sqrt(
            pooled
            * (1 - pooled)
            * (1 / control.sample_size + 1 / challenger.sample_size)
        )
        if standard_error == 0:
            return 1.0
        control_rate = control.conversions / control.sample_size
        challenger_rate = challenger.conversions / challenger.sample_size
        return erfc(abs(challenger_rate - control_rate) / standard_error / sqrt(2))

    @staticmethod
    def _guardrail_breaches(
        experiment: Experiment, variants: list[VariantObservation]
    ) -> list[str]:
        breaches: list[str] = []
        comparisons = {
            "<=": lambda value, threshold: value <= threshold,
            ">=": lambda value, threshold: value >= threshold,
            "<": lambda value, threshold: value < threshold,
            ">": lambda value, threshold: value > threshold,
        }
        for guardrail in experiment.guardrails:
            for variant in variants:
                value = variant.guardrail_values.get(guardrail.metric)
                if value is None:
                    continue
                if not comparisons[guardrail.operator](value, guardrail.threshold):
                    breaches.append(
                        f"{variant.variant_id}: {guardrail.metric}={value:g} "
                        f"{guardrail.unit} violates {guardrail.operator} {guardrail.threshold:g}"
                    )
        return breaches

    def evaluate(
        self,
        experiment_id: str,
        request: ExperimentEvaluationRequest,
        *,
        actor: str,
    ) -> ExperimentEvaluation:
        experiment = self.get(experiment_id)
        observation = next(
            (
                item
                for item in reversed(experiment.observations)
                if request.observation_id is None
                or item.observation_id == request.observation_id
            ),
            None,
        )
        if observation is None:
            raise ValueError("no matching observation is available")

        planned_ids = [item.variant_id for item in experiment.variants]
        observed = {item.variant_id: item for item in observation.variants}
        control_id = planned_ids[0]
        control = observed.get(control_id)
        challengers = [observed[item] for item in planned_ids[1:] if item in observed]
        now = datetime.now(timezone.utc)
        collected_at = observation.collected_at
        if collected_at.tzinfo is None:
            collected_at = collected_at.replace(tzinfo=timezone.utc)
        source_age_hours = max(0, (now - collected_at).total_seconds() / 3600)
        source_fresh = source_age_hours <= request.max_source_age_hours
        complete = control is not None and len(challengers) == len(planned_ids) - 1
        sample_sufficient = complete and all(
            item.sample_size >= request.min_sample_per_variant
            for item in [control, *challengers]
            if item is not None
        )
        reasons: list[str] = []
        caveats = [
            "Recommendation is advisory and cannot change traffic, spend or production content."
        ]
        breaches = self._guardrail_breaches(experiment, observation.variants)
        recommendation = RecommendationAction.CONTINUE
        compared: VariantObservation | None = None
        winner_id: str | None = None
        p_value: float | None = None
        lift: float | None = None
        control_value = self._metric_value(control) if control else None
        compared_value: float | None = None

        if not complete:
            recommendation = RecommendationAction.INSUFFICIENT_DATA
            reasons.append("Observation does not cover every planned variant.")
        elif not source_fresh:
            recommendation = RecommendationAction.MANUAL_REVIEW
            reasons.append("Observation is older than the accepted freshness window.")
        elif breaches:
            recommendation = RecommendationAction.STOP_AND_REVIEW
            reasons.append("One or more experiment guardrails were breached.")
        else:
            direction = experiment.primary_metric.direction
            compared = (
                max(challengers, key=self._metric_value)
                if direction == MetricDirection.INCREASE
                else min(challengers, key=self._metric_value)
            )
            compared_value = self._metric_value(compared)
            if control_value:
                signed_change = (
                    compared_value - control_value
                    if direction == MetricDirection.INCREASE
                    else control_value - compared_value
                )
                lift = signed_change * 100 / control_value
            p_value = self._two_proportion_p_value(control, compared)
            alpha = 1 - request.confidence_level
            if observation.source_state == ObservationState.PARTIAL:
                recommendation = RecommendationAction.MANUAL_REVIEW
                reasons.append("Source is partial; it cannot support a winner candidate.")
            elif not sample_sufficient:
                recommendation = RecommendationAction.INSUFFICIENT_DATA
                reasons.append(
                    f"Each variant needs at least {request.min_sample_per_variant} samples."
                )
            elif p_value is None:
                recommendation = RecommendationAction.MANUAL_REVIEW
                reasons.append("Conversion counts are required for significance calculation.")
            elif lift is not None and lift >= experiment.target_lift_percent and p_value <= alpha:
                recommendation = RecommendationAction.WINNER_CANDIDATE
                winner_id = compared.variant_id
                reasons.append(
                    "Challenger meets the target lift and confidence threshold."
                )
            elif lift is not None and lift < 0 and p_value <= alpha:
                recommendation = RecommendationAction.STOP_AND_REVIEW
                winner_id = control.variant_id
                reasons.append("Challenger is significantly worse than control.")
            else:
                recommendation = RecommendationAction.CONTINUE
                reasons.append("Evidence does not yet justify a winner or stop recommendation.")

        if observation.source_state == ObservationState.PARTIAL:
            caveats.append("Partial source evidence requires verified read-only reconciliation.")
        evaluation = ExperimentEvaluation(
            experiment_id=experiment_id,
            observation_id=observation.observation_id,
            recommendation=recommendation,
            sample_sufficient=sample_sufficient,
            source_fresh=source_fresh,
            source_state=observation.source_state,
            control_variant_id=control_id,
            compared_variant_id=compared.variant_id if compared else None,
            winner_candidate_variant_id=winner_id,
            control_value=round(control_value, 6) if control_value is not None else None,
            compared_value=round(compared_value, 6) if compared_value is not None else None,
            observed_lift_percent=round(lift, 4) if lift is not None else None,
            p_value=round(p_value, 8) if p_value is not None else None,
            confidence_level=request.confidence_level,
            guardrail_breaches=breaches,
            reasons=reasons,
            caveats=caveats,
            evaluated_by=actor,
        )
        updated = experiment.model_copy(
            update={
                "last_evaluation": evaluation,
                "updated_by": actor,
                "updated_at": datetime.now(timezone.utc),
            },
            deep=True,
        )
        self.store.save_experiment(updated)
        self._audit(
            updated,
            event_type="experiment_evaluated",
            actor=actor,
            detail="Read-only evidence evaluated; recommendation is advisory only.",
            metadata={
                "evaluation_id": evaluation.evaluation_id,
                "observation_id": evaluation.observation_id,
                "recommendation": evaluation.recommendation.value,
                "sample_sufficient": evaluation.sample_sufficient,
                "source_fresh": evaluation.source_fresh,
                "external_side_effect": False,
                "automatic_decision": False,
            },
        )
        return evaluation

    def status(self) -> ExperimentOSStatus:
        rows = self.store.list_experiments(limit=1000)
        return ExperimentOSStatus(
            experiment_count=len(rows),
            awaiting_approval=sum(item.status == ExperimentStatus.AWAITING_APPROVAL for item in rows),
            approved_plans=sum(item.status == ExperimentStatus.APPROVED for item in rows),
            previewed=sum(item.last_preview is not None for item in rows),
            observation_count=sum(len(item.observations) for item in rows),
            evaluated=sum(item.last_evaluation is not None for item in rows),
            awaiting_observation=sum(not item.observations for item in rows),
            observation_sources=self._observation_sources(),
        )
