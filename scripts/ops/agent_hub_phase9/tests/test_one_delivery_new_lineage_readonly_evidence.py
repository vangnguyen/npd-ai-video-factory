"""Offline tests for the new-lineage read-only evidence contract."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import one_delivery_new_lineage as lineage
import one_delivery_new_lineage_readonly_evidence as readonly
from test_one_delivery_new_lineage import HEAD, OPERATION


NOW = datetime(2026, 10, 1, 9, 0, 0, tzinfo=timezone.utc)


def image_identity(seed: str, *, source_head: str = HEAD) -> dict[str, object]:
    return {
        "source_head": source_head,
        "archive_sha256": seed * 64,
        "archive_size_bytes": 123456,
        "oci_index_sha256": chr(ord(seed) + 1) * 64,
        "oci_manifest_sha256": chr(ord(seed) + 2) * 64,
        "oci_config_sha256": chr(ord(seed) + 3) * 64,
        "platform": "linux/amd64",
        "custody_manifest_sha256": chr(ord(seed) + 4) * 64,
    }


def scope_receipt() -> dict[str, object]:
    return {
        "schema": readonly.SCOPE_SCHEMA,
        "lineage": lineage.LINEAGE,
        "operation_id": OPERATION,
        "decision": "APPROVED_EVIDENCE_ONLY",
        "fresh_explicit_owner_evidence_only_scope": True,
        "authorized_counter_names": list(readonly.COUNTER_NAMES),
        "query_command": "EVAL_RO",
        "database": 0,
        "server_readonly_required": True,
        "eval_fallback_allowed": False,
        "raw_keys_values_credentials_or_job_payloads_authorized": False,
        "video_factory_workstream_opened": False,
        "video_factory_writes_authorized": False,
        "agent_hub_execution_authorized": False,
        "valid_from_utc": "2026-10-01T08:50:00Z",
        "expires_at_utc": "2026-10-01T09:10:00Z",
    }


def fixture() -> tuple[dict, dict, dict, bytes]:
    scope = scope_receipt()
    candidate = image_identity("1")
    rollback = image_identity("a", source_head="b" * 40)
    request = readonly.build_request(
        operation_id=OPERATION,
        candidate_head=HEAD,
        transport_profile_sha256="c" * 64,
        collector_source_sha256="d" * 64,
        expected_protected_services_sha256="e" * 64,
        candidate_identity=candidate,
        rollback_identity=rollback,
        db0_scope_receipt=scope,
        current=NOW,
    )
    evidence = {
        "schema": readonly.EVIDENCE_SCHEMA,
        "lineage": lineage.LINEAGE,
        "operation_id": OPERATION,
        "request_sha256": lineage.canonical_digest(request),
        "observed_at_utc": "2026-10-01T08:59:30Z",
        "agent_hub": {
            "compose_project": "npd-agent-hub-prod",
            "compose_service": "agent-hub",
            "target_container_id": "a" * 64,
            "target_image_config_sha256": rollback["oci_config_sha256"],
            "target_signature_sha256": "f" * 64,
            "protected_service_count": 18,
            "protected_services_sha256": "e" * 64,
            "healthy": True,
            "ready": True,
            "restart_count": 0,
            "runtime_mode": "phase9_creation",
            "scheduler_enabled": False,
            "external_writes_enabled": False,
            "claim_absent": True,
            "candidate_staged": False,
            "delivery_absent": True,
        },
        "candidate": {
            "identity": candidate,
            "archive_verified": True,
            "custody_manifest_verified": True,
            "staged": False,
            "loaded": False,
        },
        "rollback": {
            "identity": rollback,
            "archive_verified": True,
            "custody_manifest_verified": True,
            "image_present": True,
            "current_target": True,
        },
        "video_factory_db0": {
            "scope_receipt_sha256": lineage.canonical_digest(scope),
            "counter_names": list(readonly.COUNTER_NAMES),
            "counters": {
                "video_factory_job_count": 12,
                "video_factory_queue_count": 0,
                "video_factory_processing_count": 0,
                "video_factory_in_flight_count": 0,
            },
            "query_command": "EVAL_RO",
            "database": 0,
            "server_enforced_readonly": True,
            "eval_fallback_used": False,
            "raw_keys_values_credentials_or_job_payloads_emitted": False,
            "video_factory_workstream_opened": False,
            "video_factory_writes": 0,
        },
        "effects": {
            "production_read_only": True,
            "production_mutation": False,
            "business_system_write": False,
            "claim_created": False,
            "stage_performed": False,
            "image_loaded": False,
            "delivery_posted": False,
            "provider_calls": 0,
            "video_factory_writes": 0,
        },
        "production_execution_approval": "NOT_GRANTED",
    }
    raw = lineage.canonical_bytes(evidence) + b"\n"
    capture = {
        "schema": readonly.CAPTURE_SCHEMA,
        "lineage": lineage.LINEAGE,
        "operation_id": OPERATION,
        "request_sha256": lineage.canonical_digest(request),
        "transport_profile_sha256": request["transport_profile_sha256"],
        "collector_source_sha256": request["collector_source_sha256"],
        "remote_argv_shape": list(readonly.REMOTE_ARGV_SHAPE),
        "invocation_id": "22222222-2222-4222-8222-222222222222",
        "started_at_utc": "2026-10-01T08:59:29Z",
        "completed_at_utc": "2026-10-01T08:59:31Z",
        "child_returncode": 0,
        "timed_out": False,
        "launch_error_class": None,
        "raw_stdout_sha256": hashlib.sha256(raw).hexdigest(),
        "raw_stdout_length_bytes": len(raw),
        "canonical_payload_sha256": lineage.canonical_digest(evidence),
        "raw_stderr_sha256": readonly.EMPTY_SHA256,
        "raw_stderr_length_bytes": 0,
        "raw_transport_bytes": True,
        "argv_or_authorization_persisted": False,
    }
    return request, scope, capture, raw


def reseal_raw(capture: dict, evidence: dict) -> bytes:
    raw = lineage.canonical_bytes(evidence) + b"\n"
    capture["raw_stdout_sha256"] = hashlib.sha256(raw).hexdigest()
    capture["raw_stdout_length_bytes"] = len(raw)
    capture["canonical_payload_sha256"] = lineage.canonical_digest(evidence)
    return raw


class ReadonlyEvidenceContractTests(unittest.TestCase):
    def test_exact_bundle_verifies_without_execution_authority(self):
        request, scope, capture, raw = fixture()
        result = readonly.verify_readonly_evidence(
            request, scope, capture, raw, current=NOW
        )
        self.assertEqual(
            result["status"],
            "READONLY_EVIDENCE_VERIFIED_EXECUTION_NOT_AUTHORIZED",
        )
        self.assertEqual(result["protected_service_count"], 18)
        self.assertEqual(
            result["video_factory_db0_counters"]["video_factory_job_count"], 12
        )
        self.assertEqual(result["production_execution_approval"], "NOT_GRANTED")
        self.assertFalse(result["production_mutation"])
        self.assertFalse(result["claim_stage_load_deploy_delivery"])

    def test_historical_identity_cannot_build_request(self):
        scope = scope_receipt()
        with self.assertRaisesRegex(
            lineage.NewLineageStop, "HISTORICAL_R4_OPERATION_RETIRED"
        ):
            readonly.build_request(
                operation_id=lineage.HISTORICAL_R4_OPERATION,
                candidate_head=HEAD,
                transport_profile_sha256="c" * 64,
                collector_source_sha256="d" * 64,
                expected_protected_services_sha256="e" * 64,
                candidate_identity=image_identity("1"),
                rollback_identity=image_identity("a", source_head="b" * 40),
                db0_scope_receipt=scope,
                current=NOW,
            )

    def test_db0_scope_is_narrow_fresh_and_not_execution_approval(self):
        for field, value in (
            ("agent_hub_execution_authorized", True),
            ("video_factory_writes_authorized", True),
            ("eval_fallback_allowed", True),
            ("video_factory_workstream_opened", True),
            ("expires_at_utc", "2026-10-01T09:00:00Z"),
        ):
            with self.subTest(field=field):
                scope = scope_receipt()
                scope[field] = value
                with self.assertRaisesRegex(
                    lineage.NewLineageStop,
                    "DB0_EVIDENCE_ONLY_SCOPE_NOT_GRANTED",
                ):
                    readonly.verify_scope_receipt(
                        scope, operation_id=OPERATION, current=NOW
                    )

    def test_scope_or_capture_tamper_fails_closed(self):
        request, scope, capture, raw = fixture()
        changed_scope = deepcopy(scope)
        changed_scope["valid_from_utc"] = "2026-10-01T08:51:00Z"
        with self.assertRaisesRegex(
            lineage.NewLineageStop, "DB0_SCOPE_RECEIPT_BINDING_MISMATCH"
        ):
            readonly.verify_readonly_evidence(
                request, changed_scope, capture, raw, current=NOW
            )
        with self.assertRaisesRegex(
            lineage.NewLineageStop, "READONLY_CAPTURE_INVALID"
        ):
            readonly.verify_readonly_evidence(
                request, scope, capture, raw + b" ", current=NOW
            )

    def test_stale_or_future_evidence_fails_closed(self):
        for observed in (
            "2026-10-01T08:49:59Z",
            "2026-10-01T09:00:06Z",
        ):
            with self.subTest(observed=observed):
                request, scope, capture, raw = fixture()
                evidence = lineage.loads_strict(raw)
                evidence["observed_at_utc"] = observed
                if observed > capture["completed_at_utc"]:
                    capture["completed_at_utc"] = observed
                raw = reseal_raw(capture, evidence)
                with self.assertRaisesRegex(
                    lineage.NewLineageStop,
                    "READONLY_EVIDENCE_STALE_OR_FUTURE",
                ):
                    readonly.verify_readonly_evidence(
                        request, scope, capture, raw, current=NOW
                    )

    def test_observation_must_occur_inside_exact_scope_window(self):
        request, scope, capture, raw = fixture()
        scope["valid_from_utc"] = "2026-10-01T08:59:45Z"
        request["db0_scope_receipt_sha256"] = lineage.canonical_digest(scope)
        evidence = lineage.loads_strict(raw)
        evidence["request_sha256"] = lineage.canonical_digest(request)
        evidence["video_factory_db0"]["scope_receipt_sha256"] = (
            lineage.canonical_digest(scope)
        )
        capture["request_sha256"] = lineage.canonical_digest(request)
        raw = reseal_raw(capture, evidence)
        with self.assertRaisesRegex(
            lineage.NewLineageStop,
            "READONLY_EVIDENCE_OUTSIDE_SCOPE_WINDOW",
        ):
            readonly.verify_readonly_evidence(
                request, scope, capture, raw, current=NOW
            )

    def test_protected_candidate_and_rollback_drift_fail_closed(self):
        mutations = (
            (
                "protected",
                lambda value: value["agent_hub"].update(
                    {"protected_services_sha256": "0" * 64}
                ),
                "READONLY_AGENT_HUB_BOUNDARY_INVALID",
            ),
            (
                "candidate",
                lambda value: value["candidate"].update(
                    {"custody_manifest_verified": False}
                ),
                "READONLY_CANDIDATE_BINDING_INVALID",
            ),
            (
                "rollback",
                lambda value: value["rollback"].update({"image_present": False}),
                "READONLY_ROLLBACK_BINDING_INVALID",
            ),
        )
        for name, mutate, reason in mutations:
            with self.subTest(name=name):
                request, scope, capture, raw = fixture()
                evidence = lineage.loads_strict(raw)
                mutate(evidence)
                raw = reseal_raw(capture, evidence)
                with self.assertRaisesRegex(lineage.NewLineageStop, reason):
                    readonly.verify_readonly_evidence(
                        request, scope, capture, raw, current=NOW
                    )

    def test_db0_must_be_server_readonly_idle_and_aggregate_only(self):
        mutations = (
            lambda value: value["video_factory_db0"]["counters"].update(
                {"video_factory_queue_count": 1}
            ),
            lambda value: value["video_factory_db0"].update(
                {"query_command": "EVAL"}
            ),
            lambda value: value["video_factory_db0"].update(
                {"eval_fallback_used": True}
            ),
            lambda value: value["video_factory_db0"].update(
                {"raw_keys_values_credentials_or_job_payloads_emitted": True}
            ),
            lambda value: value["video_factory_db0"].update({"database": False}),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                request, scope, capture, raw = fixture()
                evidence = lineage.loads_strict(raw)
                mutate(evidence)
                raw = reseal_raw(capture, evidence)
                with self.assertRaisesRegex(
                    lineage.NewLineageStop, "READONLY_DB0_BOUNDARY_INVALID"
                ):
                    readonly.verify_readonly_evidence(
                        request, scope, capture, raw, current=NOW
                    )

    def test_any_write_claim_stage_load_or_delivery_flag_fails(self):
        for field, value in (
            ("production_mutation", True),
            ("business_system_write", True),
            ("claim_created", True),
            ("stage_performed", True),
            ("image_loaded", True),
            ("delivery_posted", True),
            ("provider_calls", 1),
            ("provider_calls", False),
            ("video_factory_writes", 1),
        ):
            with self.subTest(field=field):
                request, scope, capture, raw = fixture()
                evidence = lineage.loads_strict(raw)
                evidence["effects"][field] = value
                raw = reseal_raw(capture, evidence)
                with self.assertRaisesRegex(
                    lineage.NewLineageStop, "READONLY_EFFECTS_INVALID"
                ):
                    readonly.verify_readonly_evidence(
                        request, scope, capture, raw, current=NOW
                    )

    def test_module_has_no_transport_process_or_network_surface(self):
        source = Path(readonly.__file__).read_text(encoding="utf-8")
        for forbidden in (
            "import subprocess",
            "import socket",
            "import requests",
            "import paramiko",
            "urlopen",
            "Popen(",
            "subprocess.run",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
