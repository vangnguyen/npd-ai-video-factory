from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from pydantic import BaseModel

from .delivery_observability import AttributionDeliveryService
from .sales_intelligence_models import (
    SalesActivityCompletenessProof,
    SalesActivityObservation,
    SalesActivityType,
)


COMPLETENESS_DIGEST_METADATA_KEY = "sales_activity_completeness_digest"
ALL_ACTIVITY_TYPES = frozenset(SalesActivityType)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def digest_model(value: BaseModel) -> str:
    return hashlib.sha256(_canonical(value.model_dump(mode="json"))).hexdigest()


def activity_batch_digest(observations: list[SalesActivityObservation]) -> str:
    ordered = sorted(
        observations,
        key=lambda item: (item.occurred_at, item.activity_id),
    )
    payload = [item.model_dump(mode="json") for item in ordered]
    return hashlib.sha256(_canonical(payload)).hexdigest()


@dataclass(frozen=True)
class CompletenessAssessment:
    verified: bool
    source_complete: bool
    receipt_id: str | None
    complete_through: datetime | None
    covered_activity_types: frozenset[SalesActivityType]
    detail: str

    def covers(self, activity_type: SalesActivityType, through: datetime) -> bool:
        if not self.verified or self.complete_through is None:
            return False
        target = through.astimezone(timezone.utc)
        return (
            activity_type in self.covered_activity_types
            and self.complete_through.astimezone(timezone.utc) >= target
        )


class SalesCompletenessVerifier:
    """Bind a PII-free Sales Hub completeness claim to a signed Agent Hub heartbeat receipt."""

    def __init__(self, delivery: AttributionDeliveryService | None) -> None:
        self.delivery = delivery

    @staticmethod
    def _failed(detail: str) -> CompletenessAssessment:
        return CompletenessAssessment(
            verified=False,
            source_complete=False,
            receipt_id=None,
            complete_through=None,
            covered_activity_types=frozenset(),
            detail=detail,
        )

    def verify(
        self,
        proof: SalesActivityCompletenessProof | None,
        *,
        subject_ref: str,
        campaign_id: str,
        observations: list[SalesActivityObservation],
        as_of: datetime,
        lead_start_at: datetime | None,
        duplicate_count: int,
        untrusted_count: int,
    ) -> CompletenessAssessment:
        if proof is None:
            return self._failed("No signed Sales Hub completeness proof was supplied.")
        if self.delivery is None:
            return self._failed("Sales completeness verification service is unavailable.")

        claim = proof.claim
        heartbeat = proof.heartbeat
        receipt = proof.receipt

        signature = self.delivery.verify_heartbeat(receipt)
        if not signature.valid:
            return self._failed("Heartbeat receipt signature verification failed.")
        if receipt.payload_digest != digest_model(heartbeat):
            return self._failed("Heartbeat receipt payload digest does not bind to the supplied heartbeat.")
        if (
            receipt.heartbeat_id != heartbeat.heartbeat_id
            or receipt.producer != heartbeat.producer
            or receipt.sequence != heartbeat.sequence
            or receipt.emitted_at != heartbeat.emitted_at
        ):
            return self._failed("Heartbeat receipt identity does not match the supplied heartbeat.")
        if heartbeat.producer != claim.producer:
            return self._failed("Heartbeat producer does not match the Sales Hub completeness claim.")

        expected_claim_digest = digest_model(claim)
        if heartbeat.metadata.get(COMPLETENESS_DIGEST_METADATA_KEY) != expected_claim_digest:
            return self._failed("Heartbeat metadata is not bound to the supplied completeness claim.")
        if claim.complete_through > heartbeat.emitted_at:
            return self._failed("Completeness watermark cannot be later than heartbeat emission time.")
        if claim.subject_ref != subject_ref:
            return self._failed("Completeness claim subject does not match the evaluated subject.")
        if claim.campaign_id != campaign_id:
            return self._failed("Completeness claim Campaign does not match the evaluated Campaign.")
        if claim.record_count != len(observations):
            return self._failed("Completeness claim record_count does not match the supplied activity batch.")
        if claim.activity_batch_digest != activity_batch_digest(observations):
            return self._failed("Completeness claim activity digest does not match the supplied activity batch.")
        if duplicate_count or untrusted_count:
            return self._failed(
                "Completeness proof is bound to a batch with duplicate or untrusted activity evidence."
            )
        if lead_start_at is not None and claim.window_start > lead_start_at:
            return self._failed("Completeness window starts after the authoritative lead clock.")

        covered = frozenset(claim.covered_activity_types)
        complete_through = claim.complete_through.astimezone(timezone.utc)
        source_complete = (
            covered == ALL_ACTIVITY_TYPES
            and complete_through >= as_of.astimezone(timezone.utc)
        )
        return CompletenessAssessment(
            verified=True,
            source_complete=source_complete,
            receipt_id=receipt.receipt_id,
            complete_through=complete_through,
            covered_activity_types=covered,
            detail=(
                "Signed Sales Hub completeness proof is valid and covers the full evaluation window."
                if source_complete
                else "Signed Sales Hub completeness proof is valid but does not cover every activity type through as_of."
            ),
        )
