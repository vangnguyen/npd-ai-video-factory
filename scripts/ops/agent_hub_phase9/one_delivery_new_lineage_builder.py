"""Deterministic offline package builder for the adopted new lineage.

This builder writes only a new local review directory.  It has no transport,
subprocess, credential, claim, staging, image, or production capability.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Mapping
from uuid import uuid4

import one_delivery_new_lineage as lineage
import one_delivery_new_lineage_executor_runtime as executor_runtime
import one_delivery_new_lineage_readonly_evidence as readonly
import one_delivery_new_lineage_transport_runtime as transport_runtime


BUILD_ARTIFACTS = lineage.REQUIRED_ARTIFACTS - {"OPERATION_BINDINGS.json"}
RUNTIME_REVIEW_SCHEMA = "npd.agent-hub.phase9.one-delivery-runtime-review.v1"
RUNTIME_REVIEW_MANIFEST_SCHEMA = (
    "npd.agent-hub.phase9.one-delivery-runtime-review-manifest.v1"
)
RUNTIME_SOURCE_FILES = {
    "BUILDER_SOURCE.py": Path(__file__),
    "CORE_RUNTIME_SOURCE.py": Path(lineage.__file__),
    "READONLY_VERIFIER_SOURCE.py": Path(readonly.__file__),
    "TRANSPORT_RUNTIME_SOURCE.py": Path(transport_runtime.__file__),
    "EXECUTOR_RUNTIME_SOURCE.py": Path(executor_runtime.__file__),
}
RUNTIME_REVIEW_ARTIFACTS = set(RUNTIME_SOURCE_FILES) | {
    "READONLY_REQUEST.json",
    "TRANSPORT_PROFILE.json",
    "STRICT_ARGV.json",
    "READONLY_COLLECTOR.py",
    "RUNTIME_REVIEW_CONTRACT.json",
}


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


def _write_new_bytes(path: Path, raw: object) -> None:
    lineage.require(type(raw) is bytes and len(raw) > 0, "BUILD_SOURCE_BYTES_INVALID")
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


def _runtime_contract(
    *,
    base: Mapping[str, object],
    request: Mapping[str, object],
    profile: Mapping[str, object],
    collector: bytes,
    strict_argv: Mapping[str, object],
    source_bytes: Mapping[str, bytes],
) -> dict[str, object]:
    return {
        "schema": RUNTIME_REVIEW_SCHEMA,
        "lineage": lineage.LINEAGE,
        "operation_id": base["bindings"]["operation_id"],
        "candidate_head": base["bindings"]["candidate_head"],
        "base_package_manifest_sha256": base["manifest_sha256"],
        "readonly_request_sha256": lineage.canonical_digest(request),
        "transport_profile_sha256": lineage.canonical_digest(profile),
        "core_source_sha256": lineage.sha256_file(Path(lineage.__file__)),
        "builder_source_sha256": lineage.sha256_file(Path(__file__)),
        "readonly_verifier_source_sha256": lineage.sha256_file(Path(readonly.__file__)),
        "transport_source_sha256": lineage.sha256_file(
            Path(transport_runtime.__file__)
        ),
        "executor_source_sha256": lineage.sha256_file(
            Path(executor_runtime.__file__)
        ),
        "collector_bytes_sha256": transport_runtime.collector_digest(collector),
        "strict_argv_sha256": lineage.canonical_digest(strict_argv),
        "source_inventory": {
            name: {
                "sha256": hashlib.sha256(raw).hexdigest(),
                "length_bytes": len(raw),
            }
            for name, raw in sorted(source_bytes.items())
        },
        "state_path": (
            "PREFLIGHT->CLAIMED->STAGED->PRE_POST_INTENT->"
            "POST_OBSERVED->PASS_OR_HOLD"
        ),
        "max_attempts": 1,
        "automatic_retry": False,
        "pre_post_recovery": "LOCAL_SANDBOX_ONLY_REVIEWED_BOUNDARY",
        "automatic_rollback_after_post": False,
        "generated_command_executed": False,
        "fixture_only": True,
        "production_capable": False,
        "read_scope_authority": "NOT_GRANTED_STRUCTURAL_FIXTURE_ONLY",
        "execution_authority": "NOT_GRANTED",
    }


def verify_runtime_review_package(
    directory: Path | str,
    *,
    expected_manifest_sha256: str,
    base_package: Path | str,
    expected_base_manifest_sha256: str,
    expected_head: str,
) -> dict[str, object]:
    """Verify the exact runtime-review package without executing any source."""
    lineage.require(
        isinstance(expected_manifest_sha256, str)
        and bool(lineage.HASH.fullmatch(expected_manifest_sha256)),
        "RUNTIME_REVIEW_MANIFEST_ANCHOR_INVALID",
    )
    root = Path(directory).resolve(strict=True)
    lineage.require(root.is_dir() and not root.is_symlink(), "RUNTIME_REVIEW_DIRECTORY_INVALID")
    manifest_path = root / "PACKAGE_MANIFEST.json"
    lineage.require(
        lineage.sha256_file(manifest_path) == expected_manifest_sha256,
        "RUNTIME_REVIEW_MANIFEST_HASH_MISMATCH",
    )
    manifest = lineage.load_json(manifest_path)
    lineage.require(isinstance(manifest, Mapping), "RUNTIME_REVIEW_MANIFEST_INVALID")
    lineage.require(
        set(manifest)
        == {
            "schema",
            "lineage",
            "mode",
            "operation_id",
            "candidate_head",
            "artifacts",
            "production_capable",
            "read_scope_authority",
            "execution_authority",
        }
        and manifest.get("schema") == RUNTIME_REVIEW_MANIFEST_SCHEMA
        and manifest.get("lineage") == lineage.LINEAGE
        and manifest.get("mode") == "OFFLINE_RUNTIME_REVIEW_ONLY"
        and manifest.get("candidate_head") == expected_head
        and manifest.get("production_capable") is False
        and manifest.get("read_scope_authority")
        == "NOT_GRANTED_STRUCTURAL_FIXTURE_ONLY"
        and manifest.get("execution_authority") == "NOT_GRANTED",
        "RUNTIME_REVIEW_MANIFEST_BOUNDARY_INVALID",
    )
    rows = manifest.get("artifacts")
    lineage.require(isinstance(rows, list), "RUNTIME_REVIEW_INVENTORY_INVALID")
    listed: dict[str, Path] = {}
    for row in rows:
        lineage.require(
            isinstance(row, Mapping)
            and set(row) == {"path", "sha256", "length_bytes"},
            "RUNTIME_REVIEW_ENTRY_INVALID",
        )
        path = lineage.safe_artifact(root, row["path"])
        lineage.require(path.name not in listed, "RUNTIME_REVIEW_DUPLICATE_ARTIFACT")
        lineage.require(
            path.is_file()
            and not path.is_symlink()
            and lineage.sha256_file(path) == row["sha256"]
            and path.stat().st_size == row["length_bytes"],
            "RUNTIME_REVIEW_ARTIFACT_TAMPERED",
        )
        listed[path.name] = path
    lineage.require(
        set(listed) == RUNTIME_REVIEW_ARTIFACTS
        and {item.name for item in root.iterdir()}
        == RUNTIME_REVIEW_ARTIFACTS | {"PACKAGE_MANIFEST.json"},
        "RUNTIME_REVIEW_ALLOWLIST_MISMATCH",
    )
    base = lineage.verify_package(
        base_package,
        expected_manifest_sha256=expected_base_manifest_sha256,
        expected_head=expected_head,
    )
    request = readonly.verify_request_contract(
        lineage.load_json(listed["READONLY_REQUEST.json"])
    )
    profile = transport_runtime.verify_transport_profile(
        lineage.load_json(listed["TRANSPORT_PROFILE.json"])
    )
    collector = listed["READONLY_COLLECTOR.py"].read_bytes()
    strict_argv = lineage.load_json(listed["STRICT_ARGV.json"])
    contract = lineage.load_json(listed["RUNTIME_REVIEW_CONTRACT.json"])
    source_bytes = {
        name: listed[name].read_bytes() for name in RUNTIME_SOURCE_FILES
    }
    expected_contract = _runtime_contract(
        base=base,
        request=request,
        profile=profile,
        collector=collector,
        strict_argv=strict_argv,
        source_bytes=source_bytes,
    )
    lineage.require(contract == expected_contract, "RUNTIME_REVIEW_CONTRACT_MISMATCH")
    lineage.require(
        collector == transport_runtime.render_readonly_collector(profile)
        and strict_argv
        == transport_runtime.render_strict_argv_template(request, profile, collector),
        "RUNTIME_REVIEW_RENDERED_BYTES_MISMATCH",
    )
    lineage.require(
        base["bindings"]["operation_id"] == request["operation_id"]
        == manifest.get("operation_id"),
        "RUNTIME_REVIEW_OPERATION_MISMATCH",
    )
    return {
        "status": "OFFLINE_RUNTIME_REVIEW_PACKAGE_VERIFIED",
        "package": root,
        "manifest": manifest,
        "manifest_sha256": expected_manifest_sha256,
        "base": base,
        "request": request,
        "profile": profile,
        "collector": collector,
        "strict_argv": strict_argv,
        "contract": contract,
    }


def build_offline_runtime_review_package(
    output_directory: Path | str,
    *,
    base_package: Path | str,
    expected_base_manifest_sha256: str,
    expected_head: str,
    readonly_request: object,
    transport_profile: object,
) -> dict[str, object]:
    """Seal the actual reviewed source path without granting runtime use."""
    base = lineage.verify_package(
        base_package,
        expected_manifest_sha256=expected_base_manifest_sha256,
        expected_head=expected_head,
    )
    request = readonly.verify_request_contract(readonly_request)
    profile = transport_runtime.verify_transport_profile(transport_profile)
    lineage.require(
        base["bindings"]["operation_id"] == request["operation_id"],
        "RUNTIME_REVIEW_OPERATION_MISMATCH",
    )
    collector = transport_runtime.render_readonly_collector(profile)
    strict_argv = transport_runtime.render_strict_argv_template(
        request, profile, collector
    )
    source_bytes = {
        name: path.read_bytes() for name, path in RUNTIME_SOURCE_FILES.items()
    }
    contract = _runtime_contract(
        base=base,
        request=request,
        profile=profile,
        collector=collector,
        strict_argv=strict_argv,
        source_bytes=source_bytes,
    )

    raw_output = Path(output_directory).absolute()
    lineage.require(not raw_output.is_symlink(), "RUNTIME_REVIEW_OUTPUT_SYMLINK_DENIED")
    parent = raw_output.parent.resolve(strict=True)
    output = parent / raw_output.name
    lineage.require(not output.exists(), "RUNTIME_REVIEW_OUTPUT_EXISTS")
    stage = parent / f".agent-hub-runtime-review-{uuid4().hex}"
    stage.mkdir(mode=0o700)
    try:
        for name, raw in sorted(source_bytes.items()):
            _write_new_bytes(stage / name, raw)
        _write_new_bytes(stage / "READONLY_COLLECTOR.py", collector)
        _write_new_json(stage / "READONLY_REQUEST.json", request)
        _write_new_json(stage / "TRANSPORT_PROFILE.json", profile)
        _write_new_json(stage / "STRICT_ARGV.json", strict_argv)
        _write_new_json(stage / "RUNTIME_REVIEW_CONTRACT.json", contract)
        entries = [
            {
                "path": path.name,
                "sha256": lineage.sha256_file(path),
                "length_bytes": path.stat().st_size,
            }
            for path in sorted(stage.iterdir(), key=lambda item: item.name)
        ]
        manifest = {
            "schema": RUNTIME_REVIEW_MANIFEST_SCHEMA,
            "lineage": lineage.LINEAGE,
            "mode": "OFFLINE_RUNTIME_REVIEW_ONLY",
            "operation_id": base["bindings"]["operation_id"],
            "candidate_head": expected_head,
            "artifacts": entries,
            "production_capable": False,
            "read_scope_authority": "NOT_GRANTED_STRUCTURAL_FIXTURE_ONLY",
            "execution_authority": "NOT_GRANTED",
        }
        _write_new_json(stage / "PACKAGE_MANIFEST.json", manifest)
        manifest_sha256 = lineage.sha256_file(stage / "PACKAGE_MANIFEST.json")
        verify_runtime_review_package(
            stage,
            expected_manifest_sha256=manifest_sha256,
            base_package=base_package,
            expected_base_manifest_sha256=expected_base_manifest_sha256,
            expected_head=expected_head,
        )
        _sync_directory(stage)
        os.replace(stage, output)
        _sync_directory(parent)
    except Exception:
        if stage.exists():
            _cleanup_owned_runtime_stage(stage, parent)
        raise

    verified = verify_runtime_review_package(
        output,
        expected_manifest_sha256=manifest_sha256,
        base_package=base_package,
        expected_base_manifest_sha256=expected_base_manifest_sha256,
        expected_head=expected_head,
    )
    binding = runtime_binding_from_verified(verified)
    executor_runtime.verify_runtime_binding(binding)
    return {
        "status": "OFFLINE_RUNTIME_REVIEW_PACKAGE_BUILT",
        "package_directory": str(output),
        "package_manifest_sha256": manifest_sha256,
        "base_package_manifest_sha256": expected_base_manifest_sha256,
        "runtime_binding": binding,
        "verified_status": verified["status"],
        "generated_command_executed": False,
        "production_capable": False,
        "read_scope_authority": "NOT_GRANTED_STRUCTURAL_FIXTURE_ONLY",
        "execution_authority": "NOT_GRANTED",
    }


def runtime_binding_from_verified(verified: Mapping[str, object]) -> dict[str, object]:
    """Derive the executor binding from already verified package bytes."""
    lineage.require(
        verified.get("status") == "OFFLINE_RUNTIME_REVIEW_PACKAGE_VERIFIED",
        "RUNTIME_REVIEW_VERIFICATION_REQUIRED",
    )
    contract = verified["contract"]
    manifest = verified["manifest"]
    lineage.require(
        isinstance(contract, Mapping) and isinstance(manifest, Mapping),
        "RUNTIME_REVIEW_VERIFICATION_INVALID",
    )
    binding = {
        "schema": executor_runtime.BINDING_SCHEMA,
        "lineage": lineage.LINEAGE,
        "operation_id": manifest["operation_id"],
        "candidate_head": manifest["candidate_head"],
        "base_package_manifest_sha256": contract[
            "base_package_manifest_sha256"
        ],
        "runtime_review_manifest_sha256": verified["manifest_sha256"],
        "readonly_request_sha256": contract["readonly_request_sha256"],
        "transport_profile_sha256": contract["transport_profile_sha256"],
        "core_source_sha256": contract["core_source_sha256"],
        "transport_source_sha256": contract["transport_source_sha256"],
        "builder_source_sha256": contract["builder_source_sha256"],
        "executor_source_sha256": contract["executor_source_sha256"],
        "readonly_verifier_source_sha256": contract[
            "readonly_verifier_source_sha256"
        ],
        "collector_bytes_sha256": contract["collector_bytes_sha256"],
        "strict_argv_sha256": contract["strict_argv_sha256"],
        "candidate_archive_sha256": verified["request"]["candidate_identity"][
            "archive_sha256"
        ],
        "rollback_archive_sha256": verified["request"]["rollback_identity"][
            "archive_sha256"
        ],
        "fixture_only": True,
        "generated_command_executed": False,
        "real_post_attempts": 0,
        "read_scope_authority": "NOT_GRANTED_STRUCTURAL_FIXTURE_ONLY",
        "execution_authority": "NOT_GRANTED",
    }
    executor_runtime.verify_runtime_binding(binding)
    return binding


def _cleanup_owned_runtime_stage(stage: Path, parent: Path) -> None:
    resolved = stage.resolve(strict=True)
    lineage.require(
        resolved.parent == parent
        and resolved.name.startswith(".agent-hub-runtime-review-"),
        "RUNTIME_REVIEW_STAGE_OWNERSHIP_INVALID",
    )
    for child in resolved.iterdir():
        lineage.require(child.is_file() or child.is_symlink(), "RUNTIME_REVIEW_STAGE_INVALID")
        child.unlink()
    resolved.rmdir()
