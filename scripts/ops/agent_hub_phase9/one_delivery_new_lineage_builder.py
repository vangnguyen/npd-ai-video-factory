"""Deterministic offline package builder for the adopted new lineage.

This builder writes only a new local review directory.  It has no transport,
subprocess, credential, claim, staging, image, or production capability.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping
from uuid import uuid4

import one_delivery_new_lineage as lineage


BUILD_ARTIFACTS = lineage.REQUIRED_ARTIFACTS - {"OPERATION_BINDINGS.json"}


def _copy_json(value: object) -> object:
    """Normalize to strict JSON data and reject non-JSON inputs."""
    return lineage.loads_strict(lineage.canonical_bytes(value))


def _write_new_json(path: Path, value: object) -> None:
    raw = lineage.canonical_bytes(value) + b"\n"
    try:
        with path.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        raise lineage.NewLineageStop("BUILD_ARTIFACT_COLLISION") from None
    except OSError:
        raise lineage.NewLineageStop("BUILD_ARTIFACT_WRITE_FAILED") from None


def _sync_directory(path: Path) -> None:
    if not hasattr(os, "O_DIRECTORY"):
        return
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        raise lineage.NewLineageStop("BUILD_DIRECTORY_SYNC_FAILED") from None


def _cleanup_owned_stage(stage: Path, parent: Path) -> None:
    """Remove only files created inside this builder's unique staging dir."""
    try:
        resolved = stage.resolve(strict=True)
        lineage.require(
            resolved.parent == parent
            and resolved.name.startswith(".agent-hub-new-lineage-build-"),
            "BUILD_STAGE_OWNERSHIP_INVALID",
        )
        for child in resolved.iterdir():
            lineage.require(
                child.is_file() or child.is_symlink(),
                "BUILD_STAGE_UNEXPECTED_ENTRY",
            )
            child.unlink()
        resolved.rmdir()
    except FileNotFoundError:
        return
    except OSError:
        raise lineage.NewLineageStop("BUILD_STAGE_CLEANUP_FAILED") from None


def _operation_bindings(
    stage: Path,
    *,
    operation_id: str,
    candidate_head: str,
    artifacts: Mapping[str, object],
) -> dict[str, object]:
    binding = artifacts["DELIVERY_BINDING.json"]
    evidence = artifacts["CAMPAIGN_DIGEST_EVIDENCE.json"]
    lineage.require(isinstance(binding, Mapping), "BUILD_DELIVERY_BINDING_INVALID")
    lineage.require(isinstance(evidence, Mapping), "BUILD_CAMPAIGN_EVIDENCE_INVALID")
    cohort = binding.get("cohort")
    lineage.require(isinstance(cohort, Mapping), "BUILD_COHORT_INVALID")
    values: dict[str, object] = {
        "schema": "npd.agent-hub.phase9.one-delivery-bindings.v1",
        "lineage": lineage.LINEAGE,
        "operation_id": operation_id,
        "candidate_head": candidate_head,
        "campaign_id": cohort.get("canonical_campaign_id"),
        "delivery_id": binding.get("delivery_id"),
        "source_event_id": binding.get("source_event_id"),
        "subject_ref": cohort.get("subject_ref"),
        "campaign_raw_transport_sha256": evidence.get("raw_transport_sha256"),
        "campaign_semantic_model_sha256": evidence.get("semantic_model_sha256"),
    }
    for filename, field in {
        "DELIVERY_BINDING.json": "delivery_binding_sha256",
        "DELIVERY_ENVELOPE.json": "delivery_envelope_sha256",
        "CANDIDATE_IMAGE.json": "candidate_image_sha256",
        "PREFLIGHT_CONTRACT.json": "preflight_contract_sha256",
        "RECOVERY_CONTRACT.json": "recovery_contract_sha256",
        "READBACK_CONTRACT.json": "readback_contract_sha256",
        "CAMPAIGN_DIGEST_EVIDENCE.json": "campaign_digest_evidence_sha256",
    }.items():
        values[field] = lineage.sha256_file(stage / filename)
    return values


def build_offline_review_package(
    output_directory: Path | str,
    *,
    operation_id: str,
    candidate_head: str,
    artifacts: Mapping[str, object],
) -> dict[str, object]:
    """Build and self-verify one immutable offline-review package.

    The destination must not exist.  The operation identity and every input
    artifact are caller-selected review data; this function creates no
    production operation or execution authority.
    """
    lineage.parse_operation_id(operation_id)
    lineage.require(
        isinstance(candidate_head, str)
        and bool(lineage.HEAD.fullmatch(candidate_head)),
        "CANDIDATE_HEAD_INVALID",
    )
    lineage.require(
        isinstance(artifacts, Mapping) and set(artifacts) == BUILD_ARTIFACTS,
        "BUILD_ARTIFACT_ALLOWLIST_MISMATCH",
    )
    normalized = {name: _copy_json(artifacts[name]) for name in BUILD_ARTIFACTS}

    raw_output = Path(output_directory).absolute()
    lineage.require(not raw_output.is_symlink(), "BUILD_OUTPUT_SYMLINK_DENIED")
    try:
        parent = raw_output.parent.resolve(strict=True)
    except OSError:
        raise lineage.NewLineageStop("BUILD_PARENT_INVALID") from None
    lineage.require(parent.is_dir() and not parent.is_symlink(), "BUILD_PARENT_INVALID")
    output = parent / raw_output.name
    lineage.require(not output.exists() and not output.is_symlink(), "BUILD_OUTPUT_EXISTS")
    stage = parent / f".agent-hub-new-lineage-build-{uuid4().hex}"
    try:
        stage.mkdir(mode=0o700)
    except OSError:
        raise lineage.NewLineageStop("BUILD_STAGE_CREATE_FAILED") from None

    try:
        for name in sorted(BUILD_ARTIFACTS):
            _write_new_json(stage / name, normalized[name])
        bindings = _operation_bindings(
            stage,
            operation_id=operation_id,
            candidate_head=candidate_head,
            artifacts=normalized,
        )
        _write_new_json(stage / "OPERATION_BINDINGS.json", bindings)
        entries = [
            {
                "path": path.name,
                "sha256": lineage.sha256_file(path),
                "length_bytes": path.stat().st_size,
            }
            for path in sorted(stage.iterdir(), key=lambda item: item.name)
        ]
        manifest = {
            "schema": lineage.MANIFEST_SCHEMA,
            "lineage": lineage.LINEAGE,
            "mode": "OFFLINE_REVIEW_ONLY",
            "historical_equivalence": False,
            "r5_created": False,
            "production_capable": False,
            "execution_approval": "NOT_GRANTED",
            "operation_id": operation_id,
            "candidate_head": candidate_head,
            "artifacts": entries,
        }
        _write_new_json(stage / "PACKAGE_MANIFEST.json", manifest)
        manifest_sha256 = lineage.sha256_file(stage / "PACKAGE_MANIFEST.json")
        lineage.verify_package(
            stage,
            expected_manifest_sha256=manifest_sha256,
            expected_head=candidate_head,
        )
        _sync_directory(stage)
        try:
            os.replace(stage, output)
        except OSError:
            raise lineage.NewLineageStop("BUILD_ATOMIC_PUBLISH_FAILED") from None
        _sync_directory(parent)
    except Exception:
        if stage.exists():
            _cleanup_owned_stage(stage, parent)
        raise

    return {
        "status": "OFFLINE_REVIEW_PACKAGE_BUILT",
        "lineage": lineage.LINEAGE,
        "operation_id": operation_id,
        "candidate_head": candidate_head,
        "package_directory": str(output),
        "package_manifest_sha256": manifest_sha256,
        "historical_equivalence": False,
        "r5_created": False,
        "production_capable": False,
        "execution_approval": "NOT_GRANTED",
        "production_interaction": "NOT_PERFORMED_BY_THIS_MODULE",
    }
