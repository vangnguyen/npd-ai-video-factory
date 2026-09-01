from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import Principal, require_operator
from ..espocrm_journey_evidence import (
    EspoJourneyEvidenceError,
    EspoJourneyEvidencePreview,
    EspoJourneyEvidenceReader,
)
from ..orchestrator import hub


router = APIRouter(
    prefix="/api/v1/journeys/sources/espocrm",
    tags=["journey-sources"],
)


@router.get("/preview", response_model=EspoJourneyEvidencePreview)
async def preview_espocrm_journey_evidence(
    limit: int = Query(default=200, ge=1, le=500),
    _principal: Principal = Depends(require_operator),
) -> EspoJourneyEvidencePreview:
    reader = EspoJourneyEvidenceReader(
        opportunity_reader=hub.opportunity_reader,
        settings=hub.opportunity_reader.settings,
    )
    try:
        return await reader.preview(limit=limit)
    except EspoJourneyEvidenceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
