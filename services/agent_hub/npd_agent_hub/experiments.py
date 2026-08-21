from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, time, timezone
from math import erfc, sqrt
from urllib.parse import urlencode

from .campaign_models import Campaign, CampaignAuditEvent, CampaignStatus
from .experiment_models import (
    Experiment,
    ExperimentApprovalDecision,
    ExperimentAuditEvent,
    ExperimentCreate,
    ExperimentDraftUpdate,
    ExperimentEvaluation,
    ExperimentEvaluationRequest,
    ExperimentMetaTrackingMappingUpdate,
    ExperimentObservation,
    ExperimentObservationCreate,
    ExperimentObservationQualityDecision,
    ExperimentOSStatus,
    ExperimentPreview,
    ExperimentSourceReadRequest,
    ExperimentSourceReadResult,
    ExperimentStatus,
    ExperimentTrackingValidation,
    MetricDirection,
    ObservationQualityState,
    ObservationSource,
    ObservationState,
    RecommendationAction,
    VariantObservation,
)
from .marketing_sources import MarketingSourceError, MarketingSourceReader
from .store import HubStore


class ExperimentService:
    """Plan/preview-only experiment control plane backed by accepted attribution."""

    def __init__(
        self,
        store: HubStore,
        *,
        source_status_provider: Callable[[], dict[str, str]] | None = None,
        source_reader: MarketingSourceReader | None = None,
    ) -> None:
        self.store = store
        self.source_status_provider = source_status_provider
        self.source_reader = source_reader

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

    def decide_observation_quality(
        self,
        experiment_id: str,
        observation_id: str,
        decision: ExperimentObservationQualityDecision,
        *,
        actor: str,
    ) -> ExperimentObservation:
        experiment = self.get(experiment_id)
        target = next(
            (item for item in experiment.observations if item.observation_id == observation_id),
            None,
        )
        if target is None:
            raise KeyError("observation")
        state = (
            ObservationQualityState.ACCEPTED
            if decision.accepted
            else ObservationQualityState.REJECTED
        )
        decided = target.model_copy(
            update={
                "quality_state": state,
                "quality_decided_by": actor,
                "quality_decided_at": datetime.now(timezone.utc),
                "quality_note": decision.note,
            },
            deep=True,
        )
        observations = [
            decided if item.observation_id == observation_id else item
            for item in experiment.observations
        ]
        updated = experiment.model_copy(
            update={
                "observations": observations,
                "last_evaluation": None,
                "updated_by": actor,
                "updated_at": datetime.now(timezone.utc),
            },
            deep=True,
        )
        self.store.save_experiment(updated)
        self._audit(
            updated,
            event_type="experiment_observation_quality_decided",
            actor=actor,
            detail="Owner accepted or rejected the read-only source snapshot quality.",
            metadata={
                "observation_id": observation_id,
                "quality_state": state.value,
                "source_state": target.source_state.value,
                "external_side_effect": False,
            },
        )
        return decided

    def validate_tracking(
        self, experiment_id: str, source_system: ObservationSource
    ) -> ExperimentTrackingValidation:
        experiment = self.get(experiment_id)
        campaign = self.store.get_campaign(experiment.campaign_id)
        if campaign is None:
            raise KeyError("campaign")
        configured = self.source_status_provider() if self.source_status_provider else {}
        issues: list[str] = []
        variant_keys: dict[str, str] = {}
        campaign_key: str | None = None
        landing_path = (
            campaign.landing_pages[0].target_path
            if campaign.landing_pages
            else f"/campaigns/{campaign.campaign_id.casefold()}"
        )
        tracked_urls: dict[str, str] = {}
        if landing_path and "{{" not in landing_path:
            separator = "&" if "?" in landing_path else "?"
            tracked_urls = {
                item.variant_id: landing_path
                + separator
                + urlencode(
                    {
                        "campaign_id": campaign.campaign_id,
                        "utm_campaign": campaign.tracking.utm_campaign,
                        "utm_content": item.variant_id,
                    }
                )
                for item in experiment.variants
            }
        if source_system == ObservationSource.GA4:
            if configured.get("ga4") != "configured":
                state = "not_configured"
                issues.append("GA4 read-only credential/property is not configured.")
            else:
                campaign_key = campaign.tracking.utm_campaign
                if not campaign_key or "{{" in campaign_key:
                    issues.append("utm_campaign must be a concrete Campaign tracking key.")
                variant_keys = {item.variant_id: item.variant_id for item in experiment.variants}
                state = "ready" if not issues else "partial"
        elif source_system == ObservationSource.META_ADS:
            provider_configured = configured.get("meta_ads") == "configured"
            if not provider_configured:
                issues.append("Meta Ads read-only credential/account is not configured.")
            campaign_key = campaign.attribution_refs.get("meta_ads_campaign_id")
            if not campaign_key or not campaign_key.isdigit():
                issues.append(
                    "Campaign attribution_refs.meta_ads_campaign_id must be a numeric Meta campaign ID."
                )
            for item in experiment.variants:
                asset_ref = item.asset_ref or ""
                if asset_ref.startswith("meta_ad:") and asset_ref[8:].isdigit():
                    variant_keys[item.variant_id] = asset_ref[8:]
                else:
                    issues.append(
                        f"{item.variant_id} needs asset_ref=meta_ad:<numeric_ad_id>."
                    )
            state = "ready" if provider_configured and not issues else (
                "not_configured" if not provider_configured else "partial"
            )
        else:
            state = "partial"
            issues.append("verified_import is manually ingested and has no live adapter.")
        return ExperimentTrackingValidation(
            experiment_id=experiment_id,
            campaign_id=experiment.campaign_id,
            source_system=source_system,
            state=state,
            issues=issues,
            campaign_key=campaign_key,
            variant_keys=variant_keys,
            tracked_urls=tracked_urls,
        )

    def apply_meta_tracking_mapping(
        self,
        experiment_id: str,
        request: ExperimentMetaTrackingMappingUpdate,
        *,
        actor: str,
    ) -> ExperimentTrackingValidation:
        experiment = self.get(experiment_id)
        campaign = self.store.get_campaign(experiment.campaign_id)
        if campaign is None:
            raise KeyError("campaign")
        if campaign.status not in {CampaignStatus.DRAFT, CampaignStatus.PLANNED}:
            raise ValueError("Meta tracking can only be mapped while Campaign is draft/planned")
        if experiment.status not in {ExperimentStatus.PLANNED, ExperimentStatus.PREVIEWED}:
            raise ValueError("Meta tracking can only be mapped while experiment is planned/previewed")
        if experiment.observations:
            raise ValueError(
                "tracking mapping is immutable after observations exist; create a new experiment"
            )
        expected = {item.variant_id for item in experiment.variants}
        supplied = set(request.variant_meta_ad_ids)
        if supplied != expected:
            missing = sorted(expected - supplied)
            extra = sorted(supplied - expected)
            raise ValueError(
                f"Meta mapping must cover every planned variant; missing={missing}, extra={extra}"
            )

        now = datetime.now(timezone.utc)
        updated_campaign = campaign.model_copy(deep=True)
        updated_campaign.attribution_refs = {
            **updated_campaign.attribution_refs,
            "meta_ads_campaign_id": request.meta_ads_campaign_id,
        }
        updated_campaign.audit_metadata.updated_by = actor
        updated_campaign.audit_metadata.version += 1
        updated_campaign.updated_at = now
        updated_campaign = Campaign.model_validate(updated_campaign.model_dump())

        updated_variants = [
            item.model_copy(
                update={
                    "asset_ref": f"meta_ad:{request.variant_meta_ad_ids[item.variant_id]}"
                }
            )
            for item in experiment.variants
        ]
        updated_experiment = experiment.model_copy(
            update={
                "variants": updated_variants,
                "last_preview": None,
                "last_evaluation": None,
                "status": ExperimentStatus.PLANNED,
                "updated_by": actor,
                "updated_at": now,
            },
            deep=True,
        )
        self.store.save_campaign(updated_campaign)
        self.store.save_experiment(updated_experiment)
        self.store.append_campaign_audit(
            CampaignAuditEvent(
                campaign_id=campaign.campaign_id,
                event_type="campaign_meta_tracking_mapped",
                actor=actor,
                scope="meta_ads",
                detail=request.note,
                metadata={
                    "experiment_id": experiment_id,
                    "variant_count": len(updated_variants),
                    "external_side_effect": False,
                },
            )
        )
        self._audit(
            updated_experiment,
            event_type="experiment_meta_tracking_mapped",
            actor=actor,
            detail="Owner mapped Meta campaign/ad IDs inside Agent Hub; no Ads were changed.",
            metadata={
                "campaign_id": campaign.campaign_id,
                "variant_count": len(updated_variants),
                "preview_invalidated": True,
                "external_side_effect": False,
            },
        )
        return self.validate_tracking(experiment_id, ObservationSource.META_ADS)

    async def read_source_observation(
        self,
        experiment_id: str,
        request: ExperimentSourceReadRequest,
        *,
        actor: str,
    ) -> ExperimentSourceReadResult:
        experiment = self.get(experiment_id)
        tracking = self.validate_tracking(experiment_id, request.source_system)
        if tracking.state != "ready" or self.source_reader is None:
            state = "not_configured" if tracking.state == "not_configured" else "partial"
            return ExperimentSourceReadResult(
                experiment_id=experiment_id,
                source_system=request.source_system,
                state=state,
                tracking=tracking,
                message="Tracking/source contract is not ready; no observation was stored.",
            )
        try:
            if request.source_system == ObservationSource.GA4:
                snapshot = await self.source_reader.read_ga4_experiment(
                    campaign_key=str(tracking.campaign_key),
                    variant_ids=[item.variant_id for item in experiment.variants],
                    since=request.window_start.isoformat(),
                    until=request.window_end.isoformat(),
                )
            else:
                snapshot = await self.source_reader.read_meta_experiment(
                    source_campaign_id=str(tracking.campaign_key),
                    variant_ad_ids=tracking.variant_keys,
                    since=request.window_start.isoformat(),
                    until=request.window_end.isoformat(),
                )
        except MarketingSourceError as exc:
            raise ValueError(str(exc)) from exc
        raw_variants = list(snapshot.get("variants") or [])
        if not raw_variants:
            self._audit(
                experiment,
                event_type="experiment_source_read_no_data",
                actor=actor,
                detail="Read-only source query returned no mapped variant evidence.",
                metadata={
                    "source_system": request.source_system.value,
                    "external_side_effect": False,
                },
            )
            return ExperimentSourceReadResult(
                experiment_id=experiment_id,
                source_system=request.source_system,
                state="no_data",
                tracking=tracking,
                message="Source query succeeded but returned no mapped variant data.",
            )
        expected = {item.variant_id for item in experiment.variants}
        present = {str(item.get("variant_id")) for item in raw_variants}
        complete = bool(snapshot.get("coverage_complete")) and present == expected
        observed_at = datetime.fromisoformat(str(snapshot["observed_at"]))
        window_end = min(
            datetime.combine(request.window_end, time.max, tzinfo=timezone.utc),
            observed_at,
        )
        observation = self.add_observation(
            experiment_id,
            ExperimentObservationCreate(
                source_system=request.source_system,
                source_state=(
                    ObservationState.VERIFIED_READ_ONLY if complete else ObservationState.PARTIAL
                ),
                source_snapshot_id=str(snapshot["source_snapshot_id"]),
                window_start=datetime.combine(request.window_start, time.min, tzinfo=timezone.utc),
                window_end=window_end,
                collected_at=observed_at,
                variants=[VariantObservation.model_validate(item) for item in raw_variants],
                note="Direct read-only aggregate source snapshot; pending owner quality acceptance.",
            ),
            actor=actor,
        )
        return ExperimentSourceReadResult(
            experiment_id=experiment_id,
            source_system=request.source_system,
            state="observed" if complete else "partial",
            tracking=tracking,
            observation=observation,
            message="Read-only observation stored and is pending owner quality acceptance.",
        )

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
                if (
                    item.observation_id == request.observation_id
                    if request.observation_id is not None
                    else item.quality_state == ObservationQualityState.ACCEPTED
                )
            ),
            None,
        )
        if observation is None:
            if experiment.observations and request.observation_id is None:
                raise ValueError(
                    "observation quality must be accepted by an owner before evaluation"
                )
            raise ValueError("no matching observation is available")
        if observation.quality_state != ObservationQualityState.ACCEPTED:
            raise ValueError("observation quality must be accepted by an owner before evaluation")

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
        ga4_ready = sum(
            self.validate_tracking(item.experiment_id, ObservationSource.GA4).state
            == "ready"
            for item in rows
        )
        meta_ready = sum(
            self.validate_tracking(item.experiment_id, ObservationSource.META_ADS).state
            == "ready"
            for item in rows
        )
        return ExperimentOSStatus(
            experiment_count=len(rows),
            awaiting_approval=sum(item.status == ExperimentStatus.AWAITING_APPROVAL for item in rows),
            approved_plans=sum(item.status == ExperimentStatus.APPROVED for item in rows),
            previewed=sum(item.last_preview is not None for item in rows),
            observation_count=sum(len(item.observations) for item in rows),
            observations_pending_owner=sum(
                observation.quality_state == ObservationQualityState.PENDING_OWNER
                for item in rows
                for observation in item.observations
            ),
            observations_quality_accepted=sum(
                observation.quality_state == ObservationQualityState.ACCEPTED
                for item in rows
                for observation in item.observations
            ),
            ga4_tracking_ready=ga4_ready,
            meta_tracking_ready=meta_ready,
            evaluated=sum(item.last_evaluation is not None for item in rows),
            awaiting_observation=sum(not item.observations for item in rows),
            observation_sources=self._observation_sources(),
        )
