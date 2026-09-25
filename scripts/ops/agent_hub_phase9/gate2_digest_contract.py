"""Strict Gate-2 campaign digest-domain evidence.

Gate C captures the SHA-256 of the authenticated HTTP response bytes while
Agent Hub's ``content_sha256`` identifies the validated Pydantic model.  Those
values intentionally belong to different domains and are never substitutes.
This module gives Gate-2 tooling one strict, named representation for both.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping


SCHEMA = "npd.agent-hub.phase9.gate2-campaign-digest-evidence.v1"
HASH_CONTRACT = "raw-http-response-bytes+semantic-pydantic-model.v1"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
FIELDS = {
    "schema",
    "hash_contract",
    "campaign_id",
    "http_status",
    "raw_response_bytes",
    "raw_transport_sha256",
    "semantic_model_sha256",
    "body_exported",
    "secrets_exported",
}


class Gate2DigestContractError(ValueError):
    """A digest-domain receipt is missing, ambiguous, or bound incorrectly."""


def _require(value: object, reason: str) -> None:
    if not value:
        raise Gate2DigestContractError(reason)


def raw_transport_sha256(raw_response: bytes) -> str:
    """Hash the exact HTTP response bytes without parsing or normalization."""
    if type(raw_response) is not bytes:
        raise Gate2DigestContractError("RAW_HTTP_RESPONSE_BYTES_REQUIRED")
    return hashlib.sha256(raw_response).hexdigest()


def build_evidence(
    *,
    campaign_id: str,
    http_status: int,
    raw_response: bytes,
    semantic_model_sha256: str,
) -> dict[str, object]:
    """Build sanitized evidence after callers independently validate the model."""
    _require(type(campaign_id) is str and bool(campaign_id), "CAMPAIGN_ID_INVALID")
    _require(type(http_status) is int, "HTTP_STATUS_INVALID")
    _require(type(semantic_model_sha256) is str and HEX64.fullmatch(semantic_model_sha256),
             "SEMANTIC_MODEL_SHA256_INVALID")
    raw_hash = raw_transport_sha256(raw_response)
    return {
        "schema": SCHEMA,
        "hash_contract": HASH_CONTRACT,
        "campaign_id": campaign_id,
        "http_status": http_status,
        "raw_response_bytes": len(raw_response),
        "raw_transport_sha256": raw_hash,
        "semantic_model_sha256": semantic_model_sha256,
        "body_exported": False,
        "secrets_exported": False,
    }


def verify_evidence(
    evidence: Mapping[str, object],
    *,
    expected_campaign_id: str,
    expected_raw_transport_sha256: str,
    expected_semantic_model_sha256: str,
) -> dict[str, object]:
    """Verify exact, independently named raw and semantic digest bindings."""
    _require(isinstance(evidence, Mapping), "DIGEST_EVIDENCE_OBJECT_REQUIRED")
    _require(set(evidence) == FIELDS, "DIGEST_EVIDENCE_SCHEMA_INVALID")
    _require(evidence.get("schema") == SCHEMA, "DIGEST_EVIDENCE_SCHEMA_INVALID")
    _require(evidence.get("hash_contract") == HASH_CONTRACT, "HASH_CONTRACT_INVALID")
    _require(type(evidence.get("campaign_id")) is str
             and evidence.get("campaign_id") == expected_campaign_id,
             "CAMPAIGN_ID_MISMATCH")
    _require(type(evidence.get("http_status")) is int
             and evidence.get("http_status") == 200, "HTTP_STATUS_INVALID")
    _require(type(evidence.get("raw_response_bytes")) is int
             and evidence.get("raw_response_bytes", 0) > 0, "RAW_RESPONSE_LENGTH_INVALID")
    raw_hash = evidence.get("raw_transport_sha256")
    semantic_hash = evidence.get("semantic_model_sha256")
    _require(type(raw_hash) is str and HEX64.fullmatch(raw_hash),
             "RAW_TRANSPORT_SHA256_INVALID")
    _require(type(semantic_hash) is str and HEX64.fullmatch(semantic_hash),
             "SEMANTIC_MODEL_SHA256_INVALID")
    _require(raw_hash == expected_raw_transport_sha256, "RAW_TRANSPORT_DIGEST_MISMATCH")
    _require(semantic_hash == expected_semantic_model_sha256,
             "SEMANTIC_MODEL_DIGEST_MISMATCH")
    _require(raw_hash != semantic_hash, "DIGEST_DOMAIN_COLLAPSE_DENIED")
    _require(evidence.get("body_exported") is False, "RAW_BODY_EXPORT_DENIED")
    _require(evidence.get("secrets_exported") is False, "SECRET_EXPORT_DENIED")
    return dict(evidence)
