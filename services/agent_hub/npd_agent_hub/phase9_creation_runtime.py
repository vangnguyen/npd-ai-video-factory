"""Temporary creation-only HTTP boundary; normal product mode is unchanged."""
from __future__ import annotations

from datetime import date

from .campaign_models import CampaignCreate
from .config import HubSettings


class Phase9CreationDenied(ValueError):
    pass


def verify_creation_fence(settings: HubSettings, *, campaign_id: str, owner_id: str) -> None:
    """Execution preparation must reject normal/missing fence, never infer it."""
    if (
        settings.runtime_mode != "phase9_creation"
        or settings.provider_health_scheduler_enabled is not False
        or settings.phase9_creation_campaign_id != campaign_id
        or settings.phase9_creation_owner_id != owner_id
    ):
        raise Phase9CreationDenied("PHASE9_CREATION_FENCE_INVALID")


def allows_read(settings: HubSettings, method: str, path: str) -> bool:
    if method != "GET":
        return False
    cid = settings.phase9_creation_campaign_id
    return path in {
        "/health", "/readyz", "/api/v1/whoami", "/api/v1/tools/capabilities",
        "/api/v1/provider-health/status", "/api/v1/provider-health/scheduler",
        f"/api/v1/campaigns/{cid}", f"/api/v1/campaigns/{cid}/audit",
    }


def validate_creation(settings: HubSettings, payload: object) -> None:
    if not isinstance(payload, dict) or set(payload) - set(CampaignCreate.model_fields):
        raise Phase9CreationDenied("PHASE9_CREATION_REQUEST_DENIED")
    request = CampaignCreate.model_validate(payload)
    cohort = request.internal_cohort
    if (
        cohort is None
        or cohort.canonical_campaign_id != settings.phase9_creation_campaign_id
        or cohort.owner_id != settings.phase9_creation_owner_id
        or request.owner != settings.phase9_creation_owner_id
        or request.project_code != "AHINTERNAL"
        or request.name != "P9SLACOHORT"
        or request.budget.amount != 0
        or request.budget.currency != "VND"
        or request.start_date != date(2026, 9, 1)
        or request.end_date != date(2026, 9, 30)
    ):
        raise Phase9CreationDenied("PHASE9_CREATION_BINDING_DENIED")
