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


def authorization_intent(
    *,
    transport_profile_sha256: str = "c" * 64,
    collector_bytes_sha256: str = "d" * 64,
    pinned_target_sha256: str = "9" * 64,
) -> dict[str, object]:
    return readonly.build_authorization_intent(
        operation_id=OPERATION,
        candidate_head=HEAD,
        transport_profile_sha256=transport_profile_sha256,
        collector_bytes_sha256=collector_bytes_sha256,
        pinned_target_sha256=pinned_target_sha256,
        expected_protected_services_sha256="e" * 64,
        candidate_identity=image_identity("1"),
        rollback_identity=image_identity("a", source_head="b" * 40),
    )


def scope_receipt(intent: dict[str, object] | None = None) -> dict[str, object]:
    bound = intent or authorization_intent()
    return {
        "schema": readonly.SCOPE_SCHEMA,
        "lineage": lineage.LINEAGE,
        "operation_id": OPERATION,
        "decision": "FIXTURE_SCOPE_NOT_AUTHORITY",
        "authority_class": readonly.SCOPE_AUTHORITY_FIXTURE_ONLY,
        "human_owner_approval_source_sha256": None,
        "human_owner_approval_source_verified": False,
        "bound_request_intent_sha256": lineage.canonical_digest(bound),
        "bound_transport_profile_sha256": bound["transport_profile_sha256"],
        "bound_collector_bytes_sha256": bound["collector_bytes_sha256"],
        "bound_pinned_target_sha256": bound["pinned_target_sha256"],
        "fresh_evidence_only_scope_fixture": True,
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


def request_from_intent(
    intent: dict[str, object], scope: dict[str, object]
) -> dict[str, object]:
    return readonly.build_request(
        operation_id=str(intent["operation_id"]),
        candidate_head=str(intent["candidate_head"]),
        transport_profile_sha256=str(intent["transport_profile_sha256"]),
        collector_bytes_sha256=str(intent["collector_bytes_sha256"]),
        pinned_target_sha256=str(intent["pinned_target_sha256"]),
        expected_protected_services_sha256=str(
            intent["expected_protected_services_sha256"]
        ),
        candidate_identity=intent["candidate_identity"],
        rollback_identity=intent["rollback_identity"],
        db0_scope_receipt=scope,
        current=NOW,
    )


def fixture() -> tuple[dict, dict, dict, bytes]:
    intent = authorization_intent()
    scope = scope_receipt(intent)
    request = request_from_intent(intent, scope)
    candidate = request["candidate_identity"]
    rollback = request["rollback_identity"]
    evidence = {
        "schema": readonly.EVIDENCE_SCHEMA,
        "lineage": lineage.LINEAGE,
        "operation_id": OPERATION,
        "request_sha256": lineage.canonical_digest(request),
        "observed_at_utc": "2026-10-01T08:59:30Z",
        "agent_hub": {
            "compose_project": "npd-agent-hub-prod",
            "compose_service": "agent-hub",
            "pinned_target_sha256": request["pinned_target_sha256"],
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
        "scope_authority_class": readonly.SCOPE_AUTHORITY_FIXTURE_ONLY,
        "human_owner_approval_source_verified": False,
        "production_execution_approval": "NOT_GRANTED",
    }
    raw = lineage.canonical_bytes(evidence) + b"\n"
    capture = {
        "schema": readonly.CAPTURE_SCHEMA,
        "lineage": lineage.LINEAGE,
        "operation_id": OPERATION,
        "request_sha256": lineage.canonical_digest(request),
        "authorization_intent_sha256": request["authorization_intent_sha256"],
        "transport_profile_sha256": request["transport_profile_sha256"],
        "collector_bytes_sha256": request["collector_bytes_sha256"],
        "pinned_target_sha256": request["pinned_target_sha256"],
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


def reseal_scope_bundle(
    request: dict, scope: dict, capture: dict, evidence: dict
) -> bytes:
    scope_sha256 = lineage.canonical_digest(scope)
    request["db0_scope_receipt_sha256"] = scope_sha256
    request_sha256 = lineage.canonical_digest(request)
    evidence["request_sha256"] = request_sha256
    evidence["video_factory_db0"]["scope_receipt_sha256"] = scope_sha256
    capture["request_sha256"] = request_sha256
    return reseal_raw(capture, evidence)


class ReadonlyEvidenceContractTests(unittest.TestCase):
    def test_exact_bundle_verifies_without_execution_authority(self):
        request, scope, capture, raw = fixture()
        result = readonly.verify_readonly_evidence(
            request, scope, capture, raw, current=NOW
        )
        self.assertEqual(
            result["status"],
            (
                "READONLY_EVIDENCE_STRUCTURAL_FIXTURE_VERIFIED_"
                "EXECUTION_NOT_AUTHORIZED"
            ),
        )
        self.assertEqual(result["protected_service_count"], 18)
        self.assertEqual(
            result["video_factory_db0_counters"]["video_factory_job_count"], 12
        )
        self.assertEqual(result["production_execution_approval"], "NOT_GRANTED")
        self.assertEqual(
            result["evidence_only_scope_authority"],
            "NOT_GRANTED_FIXTURE_ONLY",
        )
        self.assertFalse(result["human_owner_approval_source_verified"])
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
                collector_bytes_sha256="d" * 64,
                pinned_target_sha256="9" * 64,
                expected_protected_services_sha256="e" * 64,
                candidate_identity=image_identity("1"),
                rollback_identity=image_identity("a", source_head="b" * 40),
                db0_scope_receipt=scope,
                current=NOW,
            )

    def test_db0_scope_is_narrow_fresh_and_not_execution_approval(self):
        intent = authorization_intent()
        for field, value in (
            ("agent_hub_execution_authorized", True),
            ("video_factory_writes_authorized", True),
            ("eval_fallback_allowed", True),
            ("video_factory_workstream_opened", True),
            ("expires_at_utc", "2026-10-01T09:00:00Z"),
            ("valid_from_utc", "2026-10-01T09:11:00Z"),
        ):
            with self.subTest(field=field):
                scope = scope_receipt()
                scope[field] = value
                with self.assertRaisesRegex(
                    lineage.NewLineageStop,
                    "DB0_STRUCTURAL_SCOPE_FIXTURE_INVALID",
                ):
                    readonly.verify_scope_receipt(
                        scope,
                        operation_id=OPERATION,
                        authorization_intent=intent,
                        current=NOW,
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

    def test_capture_rejects_transport_collector_target_or_intent_substitution(self):
        for field, value in (
            ("transport_profile_sha256", "0" * 64),
            ("collector_bytes_sha256", "1" * 64),
            ("pinned_target_sha256", "2" * 64),
            ("authorization_intent_sha256", "3" * 64),
        ):
            with self.subTest(field=field):
                request, scope, capture, raw = fixture()
                capture[field] = value
                with self.assertRaisesRegex(
                    lineage.NewLineageStop,
                    "READONLY_CAPTURE_INVALID",
                ):
                    readonly.verify_readonly_evidence(
                        request, scope, capture, raw, current=NOW
                    )

    def test_scope_binds_exact_intent_transport_collector_and_target(self):
        original = authorization_intent()
        scope = scope_receipt(original)
        substitutions = (
            authorization_intent(transport_profile_sha256="0" * 64),
            authorization_intent(collector_bytes_sha256="1" * 64),
            authorization_intent(pinned_target_sha256="2" * 64),
        )
        changed_payload = deepcopy(original)
        changed_payload["expected_protected_services_sha256"] = "3" * 64
        substitutions = substitutions + (changed_payload,)
        for substitute in substitutions:
            with self.subTest(field=lineage.canonical_digest(substitute)):
                with self.assertRaisesRegex(
                    lineage.NewLineageStop,
                    "DB0_STRUCTURAL_SCOPE_FIXTURE_INVALID",
                ):
                    request_from_intent(substitute, scope)

    def test_synthetic_owner_dictionary_cannot_mint_authority(self):
        intent = authorization_intent()
        scope = scope_receipt(intent)
        scope.update(
            {
                "decision": "APPROVED_EVIDENCE_ONLY",
                "authority_class": readonly.SCOPE_AUTHORITY_VERIFIED_HUMAN,
                "human_owner_approval_source_sha256": "4" * 64,
                "human_owner_approval_source_verified": True,
            }
        )
        with self.assertRaisesRegex(
            lineage.NewLineageStop,
            "DB0_STRUCTURAL_SCOPE_FIXTURE_INVALID",
        ):
            readonly.verify_scope_receipt(
                scope,
                operation_id=OPERATION,
                authorization_intent=intent,
                current=NOW,
            )

    def test_future_capture_and_wrong_order_fail_closed(self):
        cases = (
            (
                "future_capture_reviewer_reproduction",
                "2026-10-01T09:08:00Z",
                "2026-10-01T09:08:30Z",
                "2026-10-01T09:09:00Z",
            ),
            (
                "started_after_observed",
                "2026-10-01T08:59:31Z",
                "2026-10-01T08:59:30Z",
                "2026-10-01T08:59:32Z",
            ),
            (
                "observed_after_completed",
                "2026-10-01T08:59:28Z",
                "2026-10-01T08:59:32Z",
                "2026-10-01T08:59:31Z",
            ),
        )
        for name, started, observed, completed in cases:
            with self.subTest(name=name):
                request, scope, capture, raw = fixture()
                evidence = lineage.loads_strict(raw)
                capture["started_at_utc"] = started
                evidence["observed_at_utc"] = observed
                capture["completed_at_utc"] = completed
                raw = reseal_raw(capture, evidence)
                with self.assertRaisesRegex(
                    lineage.NewLineageStop,
                    "READONLY_EVIDENCE_TIMELINE_INVALID",
                ):
                    readonly.verify_readonly_evidence(
                        request, scope, capture, raw, current=NOW
                    )

    def test_entire_capture_must_be_inside_exact_scope_window(self):
        cases = (
            (
                "started_before_scope_reviewer_reproduction",
                "2026-10-01T08:00:00Z",
                "2026-10-01T08:59:30Z",
                "2026-10-01T08:59:31Z",
                NOW,
            ),
            (
                "completed_after_scope",
                "2026-10-01T08:59:29Z",
                "2026-10-01T09:09:59Z",
                "2026-10-01T09:10:01Z",
                datetime(2026, 10, 1, 9, 10, 1, tzinfo=timezone.utc),
            ),
        )
        for name, started, observed, completed, current in cases:
            with self.subTest(name=name):
                request, scope, capture, raw = fixture()
                evidence = lineage.loads_strict(raw)
                capture["started_at_utc"] = started
                evidence["observed_at_utc"] = observed
                capture["completed_at_utc"] = completed
                raw = reseal_raw(capture, evidence)
                with self.assertRaisesRegex(
                    lineage.NewLineageStop,
                    "READONLY_EVIDENCE_OUTSIDE_SCOPE_WINDOW",
                ):
                    readonly.verify_readonly_evidence(
                        request, scope, capture, raw, current=current
                    )

    def test_whole_capture_freshness_is_bounded_to_600_seconds(self):
        request, scope, capture, raw = fixture()
        evidence = lineage.loads_strict(raw)
        scope["valid_from_utc"] = "2026-10-01T08:49:59Z"
        capture["started_at_utc"] = "2026-10-01T08:49:59Z"
        raw = reseal_scope_bundle(request, scope, capture, evidence)
        with self.assertRaisesRegex(
            lineage.NewLineageStop,
            "READONLY_EVIDENCE_STALE_OR_FUTURE",
        ):
            readonly.verify_readonly_evidence(
                request, scope, capture, raw, current=NOW
            )

        request, scope, capture, raw = fixture()
        evidence = lineage.loads_strict(raw)
        capture["started_at_utc"] = "2026-10-01T08:50:00Z"
        evidence["observed_at_utc"] = "2026-10-01T08:59:59Z"
        capture["completed_at_utc"] = "2026-10-01T09:00:00Z"
        raw = reseal_raw(capture, evidence)
        readonly.verify_readonly_evidence(
            request, scope, capture, raw, current=NOW
        )

    def test_all_times_require_utc_and_current_cannot_precede_capture(self):
        timestamp_cases = (
            ("scope_start", "scope", "valid_from_utc"),
            ("scope_end", "scope", "expires_at_utc"),
            ("capture_start", "capture", "started_at_utc"),
            ("observed", "evidence", "observed_at_utc"),
            ("capture_end", "capture", "completed_at_utc"),
        )
        for name, target, field in timestamp_cases:
            with self.subTest(name=name):
                request, scope, capture, raw = fixture()
                evidence = lineage.loads_strict(raw)
                subject = {
                    "scope": scope,
                    "capture": capture,
                    "evidence": evidence,
                }[target]
                subject[field] = "2026-10-01T09:00:00+01:00"
                if target == "scope":
                    raw = reseal_scope_bundle(request, scope, capture, evidence)
                else:
                    raw = reseal_raw(capture, evidence)
                with self.assertRaises(lineage.NewLineageStop):
                    readonly.verify_readonly_evidence(
                        request, scope, capture, raw, current=NOW
                    )

        request, scope, capture, raw = fixture()
        with self.assertRaisesRegex(
            lineage.NewLineageStop,
            "CURRENT_TIME_NOT_UTC",
        ):
            readonly.verify_readonly_evidence(
                request,
                scope,
                capture,
                raw,
                current=datetime.fromisoformat("2026-10-01T10:00:00+01:00"),
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
