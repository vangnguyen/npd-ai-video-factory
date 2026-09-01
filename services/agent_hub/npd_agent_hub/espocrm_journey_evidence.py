from __future__ import annotations

import json
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .attribution_models import (
    IdentitySource,
    SourceTouchpointEvent,
    TouchpointType,
    assert_no_raw_pii,
)
from .config import HubSettings, settings as default_settings
from .espocrm_opportunities import (
    EspoOpportunityError,
    EspoOpportunityNotConfigured,
    EspoOpportunityReader,
)
from .journey_models import JOURNEY_SALES_EVIDENCE_VERSION, SALES_EVIDENCE_STATES, JourneyState


ESPO_JOURNEY_PREVIEW_VERSION = "phase-9a-espo-preview-v1"


class EspoJourneyEvidenceError(RuntimeError):
    pass


class EspoJourneyEvidencePreview(BaseModel):
    preview_version: str = ESPO_JOURNEY_PREVIEW_VERSION
    status: Literal["not_configured", "no_data", "available", "partial"]
    configured_stage_count: int = Field(ge=0)
    records_read: int = Field(ge=0)
    candidates: list[SourceTouchpointEvent] = Field(default_factory=list)
    skipped_unmapped: int = Field(default=0, ge=0)
    skipped_missing_campaign_identity: int = Field(default=0, ge=0)
    stage_mapping: dict[str, JourneyState] = Field(default_factory=dict)
    caveats: list[str] = Field(default_factory=list)
    ingest_enabled: bool = False
    execution_enabled: bool = False
    external_writes_enabled: bool = False

    @model_validator(mode="after")
    def validate_preview_only(self) -> "EspoJourneyEvidencePreview":
        if self.ingest_enabled or self.execution_enabled or self.external_writes_enabled:
            raise ValueError("EspoCRM journey evidence preview cannot enable ingestion or writes")
        assert_no_raw_pii(self.model_dump(mode="python"), path="espo_journey_preview")
        return self


class EspoJourneyEvidenceReader:
    """Read-only adapter that proposes journey evidence only from an explicit stage map."""

    def __init__(
        self,
        opportunity_reader: EspoOpportunityReader | None = None,
        settings: HubSettings | None = None,
    ) -> None:
        self.settings = settings or default_settings
        self.opportunity_reader = opportunity_reader or EspoOpportunityReader(self.settings)

    @staticmethod
    def _normalize_stage(value: str) -> str:
        return " ".join(value.strip().casefold().split())

    def _stage_mapping(self) -> tuple[dict[str, JourneyState], dict[str, JourneyState]]:
        raw = self.settings.espocrm_journey_stage_map_json.strip()
        if not raw:
            return {}, {}
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EspoJourneyEvidenceError(
                "ESPOCRM_JOURNEY_STAGE_MAP_JSON must be valid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise EspoJourneyEvidenceError(
                "ESPOCRM_JOURNEY_STAGE_MAP_JSON must be a JSON object"
            )

        normalized: dict[str, JourneyState] = {}
        display: dict[str, JourneyState] = {}
        for source_stage, raw_state in payload.items():
            if not isinstance(source_stage, str) or not source_stage.strip():
                raise EspoJourneyEvidenceError("EspoCRM journey stage names must be non-empty strings")
            if len(source_stage.strip()) > 120:
                raise EspoJourneyEvidenceError("EspoCRM journey stage names are limited to 120 characters")
            try:
                state = JourneyState(str(raw_state))
            except ValueError as exc:
                raise EspoJourneyEvidenceError(
                    f"Unsupported journey state in EspoCRM stage map: {raw_state!r}"
                ) from exc
            if state not in SALES_EVIDENCE_STATES:
                raise EspoJourneyEvidenceError(
                    f"EspoCRM stage map cannot declare {state.value}; use the base attribution contract for that state"
                )
            key = self._normalize_stage(source_stage)
            existing = normalized.get(key)
            if existing is not None and existing != state:
                raise EspoJourneyEvidenceError(
                    "EspoCRM stage map contains conflicting normalized stage names"
                )
            normalized[key] = state
            display[source_stage.strip()] = state
        return normalized, display

    @staticmethod
    def _source_event_id(
        *,
        opportunity_id: str,
        stage: str,
        observed_at: object,
        state: JourneyState,
    ) -> str:
        material = f"{opportunity_id}|{stage}|{observed_at}|{state.value}|{ESPO_JOURNEY_PREVIEW_VERSION}"
        return f"espo-journey-{sha256(material.encode('utf-8')).hexdigest()[:32]}"

    async def preview(self, *, limit: int = 200) -> EspoJourneyEvidencePreview:
        mapping, display_mapping = self._stage_mapping()
        if not mapping:
            return EspoJourneyEvidencePreview(
                status="not_configured",
                configured_stage_count=0,
                records_read=0,
                stage_mapping={},
                caveats=[
                    "No EspoCRM journey stage map is configured; no provider request or inference was performed."
                ],
            )

        try:
            source = await self.opportunity_reader.read(limit=limit)
        except EspoOpportunityNotConfigured:
            return EspoJourneyEvidencePreview(
                status="not_configured",
                configured_stage_count=len(display_mapping),
                records_read=0,
                stage_mapping=display_mapping,
                caveats=["EspoCRM Opportunity read credentials are not configured."],
            )
        except EspoOpportunityError as exc:
            raise EspoJourneyEvidenceError(str(exc)) from exc

        candidates: list[SourceTouchpointEvent] = []
        skipped_unmapped = 0
        skipped_missing_campaign = 0
        for observation in source.observations:
            state = mapping.get(self._normalize_stage(observation.stage))
            if state is None:
                skipped_unmapped += 1
                continue

            source_campaign_id = None
            metadata_campaign = observation.metadata.get("source_campaign_id")
            if isinstance(metadata_campaign, str) and metadata_campaign.strip():
                source_campaign_id = metadata_campaign.strip()
            if observation.campaign_id_hint is None and source_campaign_id is None:
                skipped_missing_campaign += 1
                continue

            source_record_ref = f"espo-opportunity-{observation.opportunity_id}"
            event = SourceTouchpointEvent(
                source_event_id=self._source_event_id(
                    opportunity_id=observation.opportunity_id,
                    stage=observation.stage,
                    observed_at=observation.observed_at.isoformat(),
                    state=state,
                ),
                source_system=IdentitySource.ESPOCRM,
                event_type=TouchpointType.OPPORTUNITY_STAGE_CHANGED,
                occurred_at=observation.observed_at,
                channel="crm",
                canonical_campaign_id=observation.campaign_id_hint,
                source_campaign_id=source_campaign_id,
                opportunity_id=observation.opportunity_id,
                metadata={
                    "journey_evidence": {
                        "contract_version": JOURNEY_SALES_EVIDENCE_VERSION,
                        "state": state.value,
                        "source_record_ref": source_record_ref,
                        "external_writes_enabled": False,
                    },
                    "source_stage": observation.stage,
                    "preview_version": ESPO_JOURNEY_PREVIEW_VERSION,
                },
            )
            candidates.append(event)

        if not source.observations:
            status: Literal["no_data", "available", "partial"] = "no_data"
        elif candidates and (skipped_unmapped or skipped_missing_campaign):
            status = "partial"
        elif candidates:
            status = "available"
        else:
            status = "no_data"

        caveats = [
            "Preview uses Opportunity.modifiedAt/createdAt as observed evidence time; it does not claim an exact historical stage-change timestamp.",
            "Candidates are not inserted into the attribution ledger by this adapter.",
            "Only exact explicitly configured EspoCRM stage mappings can produce journey candidates.",
        ]
        if skipped_missing_campaign:
            caveats.append(
                "Mapped records without canonical or external campaign identity were omitted rather than guessed."
            )

        return EspoJourneyEvidencePreview(
            status=status,
            configured_stage_count=len(display_mapping),
            records_read=source.records_read,
            candidates=candidates,
            skipped_unmapped=skipped_unmapped,
            skipped_missing_campaign_identity=skipped_missing_campaign,
            stage_mapping=display_mapping,
            caveats=caveats,
        )
