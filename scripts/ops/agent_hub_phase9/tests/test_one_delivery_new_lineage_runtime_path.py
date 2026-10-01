"""Offline actual-path tests for the four-component new-lineage milestone."""
from __future__ import annotations

import ast
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import one_delivery_new_lineage as lineage
import one_delivery_new_lineage_builder as builder
import one_delivery_new_lineage_executor_runtime as executor
import one_delivery_new_lineage_readonly_evidence as readonly
import one_delivery_new_lineage_rehearsal as rehearsal
import one_delivery_new_lineage_transport_runtime as transport
from test_one_delivery_new_lineage import HEAD, OPERATION, SIGNING_KEY, package_fixture


NOW = datetime(2026, 10, 1, 9, 0, 0, tzinfo=timezone.utc)
CANDIDATE_ARCHIVE = b"offline-candidate-oci-archive-v1"
ROLLBACK_ARCHIVE = b"offline-rollback-oci-archive-v1"


def identity(raw: bytes, *, source_head: str, config: str, prefix: str) -> dict:
    return {
        "source_head": source_head,
        "archive_sha256": hashlib.sha256(raw).hexdigest(),
        "archive_size_bytes": len(raw),
        "oci_index_sha256": hashlib.sha256((prefix + ":index").encode()).hexdigest(),
        "oci_manifest_sha256": hashlib.sha256(
            (prefix + ":manifest").encode()
        ).hexdigest(),
        "oci_config_sha256": config,
        "platform": "linux/amd64",
        "custody_manifest_sha256": hashlib.sha256(
            (prefix + ":custody").encode()
        ).hexdigest(),
    }


def profile_fixture() -> dict[str, object]:
    target = {
        "host": "agent-hub.invalid",
        "port": 22,
        "user": "deploy",
        "host_key_fingerprint_sha256": "8" * 64,
    }
    return {
        "schema": transport.PROFILE_SCHEMA,
        "lineage": lineage.LINEAGE,
        "mode": transport.SOURCE_ONLY_MODE,
        **target,
        "pinned_target_sha256": lineage.canonical_digest(target),
        "ssh_executable_sha256": "9" * 64,
        "known_hosts_bytes_sha256": "a" * 64,
        "identity_public_fingerprint_sha256": "b" * 64,
        "target_container_name": "npd-agent-hub-prod-agent-hub-1",
        "compose_project": "npd-agent-hub-prod",
        "compose_service": "agent-hub",
        "protected_container_names": [
            f"protected-{index:02d}" for index in range(18)
        ],
        "candidate_archive_path": "/var/lib/npd-agent-hub-phase9/candidate.oci.tar",
        "rollback_archive_path": "/var/lib/npd-agent-hub-phase9/rollback.oci.tar",
        "candidate_custody_manifest_path": "/var/lib/npd-agent-hub-phase9/candidate.custody.json",
        "rollback_custody_manifest_path": "/var/lib/npd-agent-hub-phase9/rollback.custody.json",
        "claim_path": "/var/lib/npd-agent-hub-phase9/claim.json",
        "stage_path": "/var/lib/npd-agent-hub-phase9/stage/candidate.oci.tar",
        "delivery_receipt_path": "/var/lib/npd-agent-hub-phase9/delivery.json",
        "connection_attempts": 1,
        "connect_timeout_seconds": 10,
        "batch_mode": True,
        "strict_host_key_checking": True,
        "identities_only": True,
        "password_authentication": False,
        "kbd_interactive_authentication": False,
        "clear_all_forwardings": True,
        "request_tty": False,
        "read_scope_authority": "NOT_GRANTED_STRUCTURAL_FIXTURE_ONLY",
        "execution_authority": "NOT_GRANTED",
    }


def request_fixture(profile: dict[str, object]) -> dict[str, object]:
    collector_sha256 = hashlib.sha256(
        transport.render_readonly_collector(profile)
    ).hexdigest()
    candidate = identity(
        CANDIDATE_ARCHIVE,
        source_head=HEAD,
        config="5" * 64,
        prefix="candidate",
    )
    rollback = identity(
        ROLLBACK_ARCHIVE,
        source_head="b" * 40,
        config="6" * 64,
        prefix="rollback",
    )
    intent = readonly.build_authorization_intent(
        operation_id=OPERATION,
        candidate_head=HEAD,
        transport_profile_sha256=lineage.canonical_digest(profile),
        collector_bytes_sha256=collector_sha256,
        pinned_target_sha256=str(profile["pinned_target_sha256"]),
        expected_protected_services_sha256="d" * 64,
        candidate_identity=candidate,
        rollback_identity=rollback,
    )
    scope = {
        "schema": readonly.SCOPE_SCHEMA,
        "lineage": lineage.LINEAGE,
        "operation_id": OPERATION,
        "decision": "FIXTURE_SCOPE_NOT_AUTHORITY",
        "authority_class": readonly.SCOPE_AUTHORITY_FIXTURE_ONLY,
        "human_owner_approval_source_sha256": None,
        "human_owner_approval_source_verified": False,
        "bound_request_intent_sha256": lineage.canonical_digest(intent),
        "bound_transport_profile_sha256": intent["transport_profile_sha256"],
        "bound_collector_bytes_sha256": intent["collector_bytes_sha256"],
        "bound_pinned_target_sha256": intent["pinned_target_sha256"],
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
    return readonly.build_request(
        operation_id=OPERATION,
        candidate_head=HEAD,
        transport_profile_sha256=lineage.canonical_digest(profile),
        collector_bytes_sha256=collector_sha256,
        pinned_target_sha256=str(profile["pinned_target_sha256"]),
        expected_protected_services_sha256="d" * 64,
        candidate_identity=candidate,
        rollback_identity=rollback,
        db0_scope_receipt=scope,
        current=NOW,
    )


def scenario_fixture() -> dict[str, object]:
    return {
        "schema": executor.SCENARIO_SCHEMA,
        "lineage": lineage.LINEAGE,
        "operation_id": OPERATION,
        "mode": "OFFLINE_SANDBOX_ONLY",
        "fault_mode": "NONE",
        "scope_start_utc": "2026-10-01T08:59:50Z",
        "preflight_at_utc": "2026-10-01T08:59:51Z",
        "claimed_at_utc": "2026-10-01T08:59:52Z",
        "staged_at_utc": "2026-10-01T08:59:53Z",
        "pre_post_intent_at_utc": "2026-10-01T08:59:54Z",
        "post_observed_at_utc": "2026-10-01T08:59:55Z",
        "completed_at_utc": "2026-10-01T08:59:56Z",
        "scope_end_utc": "2026-10-01T09:00:00Z",
        "current_utc": "2026-10-01T08:59:56Z",
        "before": {},
        "after": {},
        "status_code": 200,
        "raw_response": b"{}\n",
        "semantic_receipt": {},
        "receipt_verification": {},
        "verification_keys": {},
    }


class RuntimePathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)
        seed = self.parent / "seed"
        seed.mkdir()
        package_fixture(seed)
        artifacts = {
            name: json.loads((seed / name).read_text(encoding="utf-8"))
            for name in builder.BUILD_ARTIFACTS
        }
        self.base_package = self.parent / "base-package"
        self.base = builder.build_offline_review_package(
            self.base_package,
            operation_id=OPERATION,
            candidate_head=HEAD,
            artifacts=artifacts,
        )
        self.profile = profile_fixture()
        self.request = request_fixture(self.profile)
        self.runtime_package = self.parent / "runtime-review"
        self.runtime = builder.build_offline_runtime_review_package(
            self.runtime_package,
            base_package=self.base_package,
            expected_base_manifest_sha256=self.base["package_manifest_sha256"],
            expected_head=HEAD,
            readonly_request=self.request,
            transport_profile=self.profile,
        )

    def rehearse(self, fault_mode: str, sandbox_name: str):
        sandbox = self.parent / sandbox_name
        sandbox.mkdir(exist_ok=True)
        return rehearsal.rehearse_offline_runtime_path(
            sandbox,
            base_package=self.base_package,
            runtime_review_package=self.runtime_package,
            expected_base_manifest_sha256=self.base["package_manifest_sha256"],
            expected_runtime_manifest_sha256=self.runtime[
                "package_manifest_sha256"
            ],
            expected_head=HEAD,
            runtime_binding=self.runtime["runtime_binding"],
            candidate_archive=CANDIDATE_ARCHIVE,
            rollback_archive=ROLLBACK_ARCHIVE,
            signing_key=SIGNING_KEY,
            observed_at="2026-10-01T09:00:00Z",
            starting_audit_count=1998,
            fault_mode=fault_mode,
        )

    def test_transport_collector_and_strict_argv_are_sealed_not_executed(self):
        verified = builder.verify_runtime_review_package(
            self.runtime_package,
            expected_manifest_sha256=self.runtime["package_manifest_sha256"],
            base_package=self.base_package,
            expected_base_manifest_sha256=self.base["package_manifest_sha256"],
            expected_head=HEAD,
        )
        ast.parse(verified["collector"].decode("utf-8"))
        argv = verified["strict_argv"]["argv"]
        self.assertIn("StrictHostKeyChecking=yes", argv)
        self.assertIn("BatchMode=yes", argv)
        self.assertIn("PasswordAuthentication=no", argv)
        self.assertNotIn("StrictHostKeyChecking=no", argv)
        self.assertFalse(verified["strict_argv"]["generated_command_executed"])
        self.assertEqual(
            verified["contract"]["collector_bytes_sha256"],
            hashlib.sha256(verified["collector"]).hexdigest(),
        )
        self.assertEqual(
            verified["request"]["collector_bytes_sha256"],
            verified["contract"]["collector_bytes_sha256"],
        )
        collector_source = verified["collector"].decode("utf-8")
        self.assertIn("CUSTODY_BINDING_MISMATCH", collector_source)
        self.assertIn("ARTIFACT_NOT_REGULAR_FILE", collector_source)
        self.assertIn("os.path.lexists", collector_source)
        with self.assertRaisesRegex(
            lineage.NewLineageStop, "REAL_TRANSPORT_RUNTIME_NOT_AUTHORIZED"
        ):
            transport.refuse_runtime_execution()
        with self.assertRaisesRegex(
            lineage.NewLineageStop, "REAL_EXECUTION_RUNTIME_NOT_AUTHORIZED"
        ):
            executor.refuse_real_runtime()

    def test_complete_offline_actual_path_passes_once_with_source_receipt(self):
        result = self.rehearse("NONE", "sandbox-pass")
        terminal = result["terminal"]
        self.assertEqual(result["status"], "OFFLINE_RUNTIME_PATH_REHEARSAL_PASS")
        self.assertEqual(terminal["terminal_state"], "PASS")
        self.assertEqual(terminal["simulated_post_attempts"], 1)
        self.assertEqual(terminal["real_post_attempts"], 0)
        self.assertFalse(terminal["generated_command_executed"])
        self.assertEqual(
            result["terminal_verification"]["status"],
            "OFFLINE_RUNTIME_TERMINAL_VERIFIED",
        )
        self.assertEqual(result["terminal_verification"]["state_count"], 6)
        self.assertEqual(
            terminal["transport_source_sha256"],
            self.runtime["runtime_binding"]["transport_source_sha256"],
        )
        self.assertEqual(
            terminal["executor_source_sha256"],
            self.runtime["runtime_binding"]["executor_source_sha256"],
        )
        with self.assertRaisesRegex(
            lineage.NewLineageStop,
            "OFFLINE_PREFLIGHT_ABSENCE_FAILED|OFFLINE_RUNTIME_CLAIM_EXISTS",
        ):
            self.rehearse("NONE", "sandbox-pass")

    def test_fault_model_reaches_only_expected_terminals_and_recovery_boundary(self):
        for index, fault_mode in enumerate(sorted(executor.FAULT_MODES)):
            with self.subTest(fault_mode=fault_mode):
                result = self.rehearse(fault_mode, f"sandbox-{index}")
                terminal = result["terminal"]
                self.assertEqual(
                    terminal["terminal_state"],
                    executor.expected_terminal_state(fault_mode),
                )
                self.assertFalse(terminal["automatic_retry"])
                self.assertFalse(terminal["automatic_rollback_after_post"])
                operation = (
                    self.parent
                    / f"sandbox-{index}"
                    / executor.OFFLINE_RUNTIME_DIRECTORY
                    / OPERATION
                )
                rollback = operation / "recovery" / "rollback.archive"
                if fault_mode == "AFTER_STAGE":
                    self.assertTrue(rollback.is_file())
                    self.assertFalse((operation / "candidate.archive").exists())
                elif terminal["terminal_state"] == "HOLD_OWNER_REVIEW":
                    self.assertFalse(rollback.exists())
                    self.assertEqual(terminal["simulated_post_attempts"], 1)

    def test_atomic_claim_race_has_one_winner_and_no_retry(self):
        sandbox = self.parent / "sandbox-race"
        sandbox.mkdir()
        barrier = threading.Barrier(2)
        outcomes: list[str] = []

        def contender():
            barrier.wait()
            try:
                result = rehearsal.rehearse_offline_runtime_path(
                    sandbox,
                    base_package=self.base_package,
                    runtime_review_package=self.runtime_package,
                    expected_base_manifest_sha256=self.base[
                        "package_manifest_sha256"
                    ],
                    expected_runtime_manifest_sha256=self.runtime[
                        "package_manifest_sha256"
                    ],
                    expected_head=HEAD,
                    runtime_binding=self.runtime["runtime_binding"],
                    candidate_archive=CANDIDATE_ARCHIVE,
                    rollback_archive=ROLLBACK_ARCHIVE,
                    signing_key=SIGNING_KEY,
                    observed_at="2026-10-01T09:00:00Z",
                )
                outcomes.append(result["terminal"]["terminal_state"])
            except lineage.NewLineageStop as error:
                outcomes.append(str(error))

        threads = [threading.Thread(target=contender) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(outcomes.count("PASS"), 1)
        self.assertEqual(len(outcomes), 2)
        self.assertTrue(
            "OFFLINE_RUNTIME_CLAIM_EXISTS" in outcomes
            or "OFFLINE_PREFLIGHT_ABSENCE_FAILED" in outcomes
        )

    def test_runtime_package_path_digest_and_source_tamper_fail_closed(self):
        collector = self.runtime_package / "READONLY_COLLECTOR.py"
        original_collector = collector.read_bytes()
        collector.write_bytes(original_collector + b"\n")
        with self.assertRaisesRegex(
            lineage.NewLineageStop, "RUNTIME_REVIEW_ARTIFACT_TAMPERED"
        ):
            builder.verify_runtime_review_package(
                self.runtime_package,
                expected_manifest_sha256=self.runtime["package_manifest_sha256"],
                base_package=self.base_package,
                expected_base_manifest_sha256=self.base[
                    "package_manifest_sha256"
                ],
                expected_head=HEAD,
            )
        collector.write_bytes(original_collector)
        manifest_path = self.runtime_package / "PACKAGE_MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["artifacts"][0]["path"] = "../escape.py"
        manifest_path.write_bytes(lineage.canonical_bytes(manifest) + b"\n")
        changed_anchor = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(
            lineage.NewLineageStop, "ARTIFACT_PATH_INVALID"
        ):
            builder.verify_runtime_review_package(
                self.runtime_package,
                expected_manifest_sha256=changed_anchor,
                base_package=self.base_package,
                expected_base_manifest_sha256=self.base[
                    "package_manifest_sha256"
                ],
                expected_head=HEAD,
            )

    def test_terminal_state_chain_tamper_fails_closed(self):
        result = self.rehearse("NONE", "sandbox-terminal-tamper")
        self.assertEqual(result["terminal"]["terminal_state"], "PASS")
        state_record = (
            self.parent
            / "sandbox-terminal-tamper"
            / executor.OFFLINE_RUNTIME_DIRECTORY
            / OPERATION
            / "states"
            / "003-PRE_POST_INTENT.json"
        )
        value = json.loads(state_record.read_text(encoding="utf-8"))
        value["automatic_retry"] = True
        state_record.write_bytes(lineage.canonical_bytes(value) + b"\n")
        with self.assertRaisesRegex(
            lineage.NewLineageStop,
            "OFFLINE_STATE_BINDING_INVALID|OFFLINE_STATE_CHAIN_INVALID",
        ):
            executor.verify_offline_runtime_terminal(
                self.parent / "sandbox-terminal-tamper",
                runtime_binding=self.runtime["runtime_binding"],
            )

        semantic = self.rehearse("NONE", "sandbox-semantic-tamper")
        self.assertEqual(semantic["terminal"]["terminal_state"], "PASS")
        operation = (
            self.parent
            / "sandbox-semantic-tamper"
            / executor.OFFLINE_RUNTIME_DIRECTORY
            / OPERATION
        )
        terminal_record = operation / "states" / "005-PASS.json"
        terminal = json.loads(terminal_record.read_text(encoding="utf-8"))
        terminal["rollback_attempted"] = True
        terminal_raw = lineage.canonical_bytes(terminal) + b"\n"
        terminal_record.write_bytes(terminal_raw)
        (operation / "state.json").write_bytes(terminal_raw)
        result_path = operation / "result.json"
        result_value = json.loads(result_path.read_text(encoding="utf-8"))
        result_value["terminal_state_sha256"] = lineage.canonical_digest(terminal)
        result_path.write_bytes(lineage.canonical_bytes(result_value) + b"\n")
        with self.assertRaisesRegex(
            lineage.NewLineageStop, "OFFLINE_STATE_SEMANTICS_INVALID"
        ):
            executor.verify_offline_runtime_terminal(
                self.parent / "sandbox-semantic-tamper",
                runtime_binding=self.runtime["runtime_binding"],
            )

        recovered = self.rehearse("AFTER_STAGE", "sandbox-recovery-tamper")
        self.assertEqual(recovered["terminal"]["terminal_state"], "RECOVERED_PRE_POST")
        rollback = (
            self.parent
            / "sandbox-recovery-tamper"
            / executor.OFFLINE_RUNTIME_DIRECTORY
            / OPERATION
            / "recovery"
            / "rollback.archive"
        )
        rollback.write_bytes(rollback.read_bytes() + b"tamper")
        with self.assertRaisesRegex(
            lineage.NewLineageStop, "OFFLINE_RECOVERY_TERMINAL_INVALID"
        ):
            executor.verify_offline_runtime_terminal(
                self.parent / "sandbox-recovery-tamper",
                runtime_binding=self.runtime["runtime_binding"],
            )

    def test_scenario_timestamp_scope_and_timezone_checks_fail_closed(self):
        mutations = (
            ("claimed_at_utc", "2026-10-01T08:59:50Z"),
            ("completed_at_utc", "2026-10-01T09:00:01Z"),
            ("scope_start_utc", "2026-10-01T09:00:01Z"),
            ("preflight_at_utc", "2026-10-01T09:59:51+01:00"),
            ("current_utc", "2026-10-01T09:10:01Z"),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                scenario = scenario_fixture()
                scenario[field] = value
                with self.assertRaises(lineage.NewLineageStop):
                    executor.verify_scenario(scenario, OPERATION)

    def test_profile_substitution_and_archive_digest_drift_fail_closed(self):
        changed = deepcopy(self.profile)
        changed["host"] = "substitute.invalid"
        with self.assertRaisesRegex(
            lineage.NewLineageStop, "TRANSPORT_PINNED_TARGET_MISMATCH"
        ):
            transport.verify_transport_profile(changed)
        escaped = deepcopy(self.profile)
        escaped["candidate_archive_path"] = (
            "/var/lib/npd-agent-hub-phase9/../escape.oci.tar"
        )
        with self.assertRaisesRegex(
            lineage.NewLineageStop, "TRANSPORT_PROFILE_PATH_INVALID"
        ):
            transport.verify_transport_profile(escaped)
        sandbox = self.parent / "sandbox-bad-archive"
        sandbox.mkdir()
        with self.assertRaisesRegex(
            lineage.NewLineageStop, "OFFLINE_CANDIDATE_ARCHIVE_MISMATCH"
        ):
            rehearsal.rehearse_offline_runtime_path(
                sandbox,
                base_package=self.base_package,
                runtime_review_package=self.runtime_package,
                expected_base_manifest_sha256=self.base[
                    "package_manifest_sha256"
                ],
                expected_runtime_manifest_sha256=self.runtime[
                    "package_manifest_sha256"
                ],
                expected_head=HEAD,
                runtime_binding=self.runtime["runtime_binding"],
                candidate_archive=CANDIDATE_ARCHIVE + b"tamper",
                rollback_archive=ROLLBACK_ARCHIVE,
                signing_key=SIGNING_KEY,
                observed_at="2026-10-01T09:00:00Z",
            )

    def test_no_callback_injection_or_live_transport_surface(self):
        for module in (builder, executor, rehearsal, transport):
            tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
            imports = {
                alias.name.split(".")[0]
                for node in ast.walk(tree)
                if isinstance(node, (ast.Import, ast.ImportFrom))
                for alias in node.names
            }
            self.assertTrue(
                {"subprocess", "socket", "requests", "paramiko"}.isdisjoint(
                    imports
                )
            )
        source = Path(executor.__file__).read_text(encoding="utf-8")
        self.assertNotIn("callback=", source)
        self.assertNotIn("transport=", source)


if __name__ == "__main__":
    unittest.main()
