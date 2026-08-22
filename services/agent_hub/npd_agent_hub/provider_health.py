from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Callable

from .attribution_models import AttributionAuditEvent
from .delivery_models import (
    AttributionDeliveryStatus,
    DeliveryFreshnessState,
    DeliveryOutcome,
)
from .delivery_observability import AttributionDeliveryService
from .provider_health_models import (
    ProviderAlertSeverity,
    ProviderAlertStatus,
    ProviderHealthAlert,
    ProviderHealthObservation,
    ProviderHealthSnapshot,
    ProviderHealthState,
    ProviderHealthStatus,
)
from .store import HubStore


REQUIRED_DELIVERY_PRODUCERS = {"n8n_lead_intake"}


class ProviderHealthService:
    """Read-only provider probes with deduplicated, internal-only alert routing."""

    def __init__(
        self,
        store: HubStore,
        delivery: AttributionDeliveryService,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.delivery = delivery
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _digest(prefix: str, value: str) -> str:
        return f"{prefix}_{hashlib.sha256(value.encode('utf-8')).hexdigest()[:24]}"

    def _audit(
        self,
        *,
        event_type: str,
        actor: str,
        detail: str,
        metadata: dict[str, object],
    ) -> None:
        self.store.append_attribution_audit(
            AttributionAuditEvent(
                event_type=event_type,
                actor=actor,
                detail=detail,
                metadata={
                    **metadata,
                    "routing_targets": ["command_center", "audit"],
                    "external_notification": False,
                    "external_side_effect": False,
                },
            )
        )

    def _provider_observations(
        self,
        *,
        configuration: dict[str, str],
        probes: dict[str, str],
        delivery_status: AttributionDeliveryStatus,
        observed_at: datetime,
    ) -> list[ProviderHealthObservation]:
        observations: list[ProviderHealthObservation] = []
        provider_names = ("crm", "meta_ads", "ga4", "social")
        for provider in provider_names:
            configuration_state = configuration.get(provider, "not_configured")
            probe_state = probes.get(provider, "not_configured")
            if configuration_state == "not_configured":
                state = ProviderHealthState.NOT_CONFIGURED
                detail = "Read-only provider credential is not configured."
            elif configuration_state == "incomplete":
                state = ProviderHealthState.DEGRADED
                detail = "Read-only provider configuration is incomplete."
            elif probe_state == "failed":
                state = ProviderHealthState.FAILED
                detail = "The bounded read-only provider probe failed."
            elif probe_state == "available":
                state = ProviderHealthState.HEALTHY
                detail = "The bounded read-only provider probe succeeded."
            else:
                state = ProviderHealthState.NO_DATA
                detail = "Provider is configured but no bounded probe result is available."
            observations.append(
                ProviderHealthObservation(
                    provider=provider,
                    state=state,
                    configuration_state=configuration_state,
                    probe_state=probe_state,
                    detail=detail,
                    observed_at=observed_at,
                )
            )

        for freshness in delivery_status.sources:
            if freshness.producer not in REQUIRED_DELIVERY_PRODUCERS:
                continue
            state = {
                DeliveryFreshnessState.FRESH: ProviderHealthState.HEALTHY,
                DeliveryFreshnessState.STALE: ProviderHealthState.STALE,
                DeliveryFreshnessState.NO_DATA: ProviderHealthState.NO_DATA,
            }[freshness.state]
            detail = {
                ProviderHealthState.HEALTHY: "Signed delivery is within its freshness SLO.",
                ProviderHealthState.STALE: "Signed delivery exceeded its freshness SLO.",
                ProviderHealthState.NO_DATA: "No successful signed delivery has been observed.",
            }[state]
            observations.append(
                ProviderHealthObservation(
                    provider=freshness.producer,
                    state=state,
                    configuration_state="internal",
                    probe_state="not_applicable",
                    freshness_state=freshness.state.value,
                    target_minutes=freshness.target_minutes,
                    age_minutes=freshness.age_minutes,
                    last_success_at=freshness.last_success_at,
                    last_receipt_id=freshness.last_receipt_id,
                    detail=detail,
                    observed_at=observed_at,
                )
            )
        return observations

    def _unresolved_retry_count(self) -> int:
        """Count deliveries whose latest recorded attempt still needs a retry."""
        latest_by_delivery = {}
        for receipt in self.delivery.list_receipts(limit=5000):
            current = latest_by_delivery.get(receipt.delivery_id)
            if current is None or receipt.attempt_number > current.attempt_number:
                latest_by_delivery[receipt.delivery_id] = receipt
        return sum(
            receipt.outcome == DeliveryOutcome.RETRY_PENDING
            for receipt in latest_by_delivery.values()
        )

    @staticmethod
    def _condition_alerts(
        observations: list[ProviderHealthObservation],
        delivery_status: AttributionDeliveryStatus,
        unresolved_retry_count: int,
    ) -> dict[str, tuple[str, str, ProviderAlertSeverity, str]]:
        conditions: dict[str, tuple[str, str, ProviderAlertSeverity, str]] = {}
        for item in observations:
            if item.state == ProviderHealthState.NOT_CONFIGURED:
                continue
            alert_type = None
            severity = ProviderAlertSeverity.WARNING
            if item.state == ProviderHealthState.FAILED:
                alert_type, severity = "probe_failed", ProviderAlertSeverity.CRITICAL
            elif item.state == ProviderHealthState.STALE:
                alert_type, severity = "freshness_stale", ProviderAlertSeverity.CRITICAL
            elif item.state == ProviderHealthState.NO_DATA:
                alert_type = "no_data"
            elif item.state == ProviderHealthState.DEGRADED:
                alert_type = "configuration_incomplete"
            if alert_type:
                dedupe_key = f"provider_health:{item.provider}:{alert_type}"
                conditions[dedupe_key] = (
                    item.provider,
                    alert_type,
                    severity,
                    item.detail,
                )
        if not delivery_status.configured:
            conditions["provider_health:attribution_delivery:signing_not_configured"] = (
                "attribution_delivery",
                "signing_not_configured",
                ProviderAlertSeverity.CRITICAL,
                "Attribution receipt signing is not configured.",
            )
        if unresolved_retry_count:
            conditions["provider_health:attribution_delivery:retry_pending"] = (
                "attribution_delivery",
                "retry_pending",
                ProviderAlertSeverity.WARNING,
                f"{unresolved_retry_count} bounded delivery retry attempt(s) remain pending at the producer.",
            )
        if delivery_status.dead_letter_count:
            conditions["provider_health:attribution_delivery:dead_letter"] = (
                "attribution_delivery",
                "dead_letter",
                ProviderAlertSeverity.CRITICAL,
                "One or more delivery attempts require internal dead-letter review.",
            )
        return conditions

    def _sync_alerts(
        self,
        conditions: dict[str, tuple[str, str, ProviderAlertSeverity, str]],
        *,
        actor: str,
        now: datetime,
    ) -> None:
        existing = {item.dedupe_key: item for item in self.store.list_provider_alerts(limit=5000)}
        for dedupe_key, (provider, alert_type, severity, detail) in conditions.items():
            current = existing.get(dedupe_key)
            if current is None:
                current = ProviderHealthAlert(
                    alert_id=self._digest("pha", dedupe_key),
                    dedupe_key=dedupe_key,
                    provider=provider,
                    alert_type=alert_type,
                    severity=severity,
                    detail=detail,
                    first_detected_at=now,
                    last_detected_at=now,
                )
                event_type = "provider_alert_opened"
            elif current.status == ProviderAlertStatus.RESOLVED:
                current = current.model_copy(
                    update={
                        "status": ProviderAlertStatus.OPEN,
                        "severity": severity,
                        "detail": detail,
                        "first_detected_at": now,
                        "last_detected_at": now,
                        "occurrence_count": current.occurrence_count + 1,
                        "acknowledged_at": None,
                        "acknowledged_by": None,
                        "resolved_at": None,
                    }
                )
                event_type = "provider_alert_reopened"
            else:
                current = current.model_copy(
                    update={
                        "severity": severity,
                        "detail": detail,
                        "last_detected_at": now,
                    }
                )
                event_type = "provider_alert_refreshed"
            self.store.save_provider_alert(current)
            if event_type != "provider_alert_refreshed":
                self._audit(
                    event_type=event_type,
                    actor=actor,
                    detail="Provider health created an internal-only alert.",
                    metadata={
                        "alert_id": current.alert_id,
                        "provider": provider,
                        "alert_type": alert_type,
                        "severity": severity.value,
                    },
                )

        for dedupe_key, current in existing.items():
            if dedupe_key in conditions or current.status == ProviderAlertStatus.RESOLVED:
                continue
            resolved = current.model_copy(
                update={
                    "status": ProviderAlertStatus.RESOLVED,
                    "resolved_at": now,
                    "last_detected_at": now,
                }
            )
            self.store.save_provider_alert(resolved)
            self._audit(
                event_type="provider_alert_resolved",
                actor=actor,
                detail="Provider health condition cleared; the internal alert was resolved.",
                metadata={"alert_id": resolved.alert_id, "provider": resolved.provider},
            )

    def refresh(
        self,
        *,
        configuration: dict[str, str],
        probes: dict[str, str],
        actor: str,
    ) -> ProviderHealthStatus:
        now = self.clock()
        delivery_status = self.delivery.status()
        observations = self._provider_observations(
            configuration=configuration,
            probes=probes,
            delivery_status=delivery_status,
            observed_at=now,
        )
        counts = {state: 0 for state in ProviderHealthState}
        for item in observations:
            counts[item.state] += 1
        snapshot = ProviderHealthSnapshot(
            snapshot_id=self._digest("phs", now.isoformat()),
            observed_at=now,
            providers=observations,
            healthy=counts[ProviderHealthState.HEALTHY],
            degraded=counts[ProviderHealthState.DEGRADED],
            failed=counts[ProviderHealthState.FAILED],
            stale=counts[ProviderHealthState.STALE],
            no_data=counts[ProviderHealthState.NO_DATA],
            not_configured=counts[ProviderHealthState.NOT_CONFIGURED],
        )
        self.store.save_provider_health_snapshot(snapshot)
        self._sync_alerts(
            self._condition_alerts(
                observations,
                delivery_status,
                self._unresolved_retry_count(),
            ),
            actor=actor,
            now=now,
        )
        self._audit(
            event_type="provider_health_refreshed",
            actor=actor,
            detail="Bounded read-only provider probes refreshed internal health state.",
            metadata={
                "snapshot_id": snapshot.snapshot_id,
                "healthy": snapshot.healthy,
                "degraded": snapshot.degraded,
                "failed": snapshot.failed,
                "stale": snapshot.stale,
                "no_data": snapshot.no_data,
            },
        )
        return self.status()

    def acknowledge(self, alert_id: str, *, actor: str) -> ProviderHealthAlert:
        alert = self.store.get_provider_alert(alert_id)
        if alert is None:
            raise KeyError(alert_id)
        if alert.status == ProviderAlertStatus.RESOLVED:
            raise ValueError("resolved alerts cannot be acknowledged")
        if alert.status == ProviderAlertStatus.ACKNOWLEDGED:
            return alert
        now = self.clock()
        updated = alert.model_copy(
            update={
                "status": ProviderAlertStatus.ACKNOWLEDGED,
                "acknowledged_at": now,
                "acknowledged_by": actor,
            }
        )
        self.store.save_provider_alert(updated)
        self._audit(
            event_type="provider_alert_acknowledged",
            actor=actor,
            detail="An operator acknowledged an internal provider-health alert.",
            metadata={"alert_id": alert_id, "provider": alert.provider},
        )
        return updated

    def list_alerts(
        self,
        *,
        status: ProviderAlertStatus | None = None,
        severity: ProviderAlertSeverity | None = None,
        provider: str | None = None,
        limit: int = 100,
    ) -> list[ProviderHealthAlert]:
        rows = self.store.list_provider_alerts(limit=max(limit * 5, limit))
        if status is not None:
            rows = [item for item in rows if item.status == status]
        if severity is not None:
            rows = [item for item in rows if item.severity == severity]
        if provider is not None:
            rows = [item for item in rows if item.provider == provider]
        return rows[:limit]

    def status(self) -> ProviderHealthStatus:
        snapshots = self.store.list_provider_health_snapshots(limit=1)
        alerts = self.store.list_provider_alerts(limit=500)
        active = [item for item in alerts if item.status != ProviderAlertStatus.RESOLVED]
        return ProviderHealthStatus(
            latest_snapshot=snapshots[0] if snapshots else None,
            alerts=active,
            open_alerts=sum(item.status == ProviderAlertStatus.OPEN for item in active),
            acknowledged_alerts=sum(
                item.status == ProviderAlertStatus.ACKNOWLEDGED for item in active
            ),
            critical_alerts=sum(
                item.severity == ProviderAlertSeverity.CRITICAL for item in active
            ),
        )
