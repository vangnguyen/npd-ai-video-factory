from __future__ import annotations

from datetime import datetime, timezone

import pytest

from npd_agent_hub.attribution_models import TouchpointEvent, TouchpointType
from npd_agent_hub.journeys import JourneyService
from npd_agent_hub.lead_scoring import LeadScoringService
from npd_agent_hub.lead_scoring_models import ScoreFactorStatus
from npd_agent_hub.store import MemoryHubStore


UTC = timezone.utc
CAMPAIGN_ID = "CMP-VGP-VINHTIEN-202609-01"


def touch(
    suffix: str,
    event_type: TouchpointType,
    hour: int,
    *,
    source: str,
    stage: str | None = None,
) -> TouchpointEvent:
    metadata = {}
    if stage is not None:
        metadata["journey_evidence"] = {
            "contract_version": "phase-9a-sales-v1",
            "state": stage,
            "source_record_ref": f"ref-{suffix}",
            "external_writes_enabled": False,
        }
    return TouchpointEvent(
        event_id="tpt_" + suffix * 32,
        campaign_id=CAMPAIGN_ID,
        event_type=event_type,
        occurred_at=datetime(2026, 9, 1, hour, tzinfo=UTC),
        source_system=source,
        channel="test",
        lead_id="lead-001",
        opportunity_id="opp-001",
        metadata=metadata,
    )


def scorer_with(*rows: TouchpointEvent) -> LeadScoringService:
    store = MemoryHubStore()
    for row in rows:
        store.append_touchpoint(row)
    return LeadScoringService(JourneyService(store))


def test_score_is_deterministic_factor_explained_and_not_a_probability():
    scorer = scorer_with(
        touch("1", TouchpointType.LEAD_CREATED, 8, source="EspoCRM"),
        touch("2", TouchpointType.LANDING_VIEW, 9, source="GA4"),
        touch("3", TouchpointType.OPPORTUNITY_CREATED, 10, source="EspoCRM"),
        touch(
            "4",
            TouchpointType.OPPORTUNITY_STAGE_CHANGED,
            11,
            source="NPD Sales Hub",
            stage="appointment",
        ),
    )
    as_of = datetime(2026, 9, 1, 12, tzinfo=UTC)

    first = scorer.score("lead:lead-001", as_of=as_of)
    second = scorer.score("lead:lead-001", as_of=as_of)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.score == 74.0
    assert first.available_points == 100
    assert first.confidence == 0.75
    assert first.methodology == "journey_momentum_v1"
    assert first.score_version == "phase-9a-score-v1"
    assert [factor.name for factor in first.factors] == [
        "journey_state",
        "recency",
        "engagement_frequency",
    ]
    assert all(factor.status == ScoreFactorStatus.OBSERVED for factor in first.factors)
    assert "project_fit" in first.missing_inputs
    assert any("not a conversion probability" in caveat for caveat in first.caveats)
    assert first.execution_enabled is False
    assert first.external_writes_enabled is False
    assert first.contains_raw_pii is False


def test_missing_engagement_is_excluded_from_denominator_not_scored_as_zero():
    scorer = scorer_with(
        touch("5", TouchpointType.LEAD_CREATED, 8, source="EspoCRM"),
        touch("6", TouchpointType.OPPORTUNITY_CREATED, 9, source="EspoCRM"),
    )

    result = scorer.score(
        "lead:lead-001",
        as_of=datetime(2026, 9, 1, 10, tzinfo=UTC),
    )
    engagement = next(
        factor for factor in result.factors if factor.name == "engagement_frequency"
    )

    assert engagement.status == ScoreFactorStatus.MISSING
    assert engagement.contribution is None
    assert result.available_points == 90
    assert result.score == 66.67
    assert "engagement_frequency" in result.missing_inputs


def test_untrusted_stage_evidence_cannot_raise_score_or_recency():
    baseline = scorer_with(
        touch("7", TouchpointType.LEAD_CREATED, 8, source="EspoCRM")
    )
    attacked = scorer_with(
        touch("7", TouchpointType.LEAD_CREATED, 8, source="EspoCRM"),
        touch(
            "8",
            TouchpointType.OPPORTUNITY_STAGE_CHANGED,
            11,
            source="GA4",
            stage="appointment",
        ),
    )
    as_of = datetime(2026, 9, 1, 12, tzinfo=UTC)

    clean_score = baseline.score("lead:lead-001", as_of=as_of)
    attacked_score = attacked.score("lead:lead-001", as_of=as_of)

    assert attacked_score.score == clean_score.score
    assert attacked_score.factors[1].evidence_refs == ["tpt_" + "7" * 32]
    assert attacked_score.confidence <= 0.65
    assert any("excluded from score inputs" in caveat for caveat in attacked_score.caveats)


def test_score_requires_trusted_evidence_and_timezone_aware_as_of():
    invalid_only = touch(
        "9",
        TouchpointType.OPPORTUNITY_STAGE_CHANGED,
        9,
        source="GA4",
        stage="customer",
    )
    scorer = scorer_with(invalid_only)

    with pytest.raises(ValueError, match="trusted journey evidence"):
        scorer.score(
            "lead:lead-001",
            as_of=datetime(2026, 9, 1, 10, tzinfo=UTC),
        )

    good = scorer_with(touch("a", TouchpointType.LEAD_CREATED, 8, source="EspoCRM"))
    with pytest.raises(ValueError, match="timezone-aware"):
        good.score("lead:lead-001", as_of=datetime(2026, 9, 1, 10))
