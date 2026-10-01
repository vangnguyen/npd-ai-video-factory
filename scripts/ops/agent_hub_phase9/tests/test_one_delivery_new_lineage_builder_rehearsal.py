"""End-to-end offline builder/rehearsal tests for the adopted new lineage."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import one_delivery_new_lineage as lineage
import one_delivery_new_lineage_builder as builder
import one_delivery_new_lineage_rehearsal as rehearsal
from test_one_delivery_new_lineage import (
    HEAD,
    OPERATION,
    SIGNING_KEY,
    package_fixture,
    write_json,
)


class NewLineageBuilderRehearsalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)
        self.seed = self.parent / "seed"
        self.seed.mkdir()
        package_fixture(self.seed)
        self.artifacts = {
            name: json.loads((self.seed / name).read_text(encoding="utf-8"))
            for name in builder.BUILD_ARTIFACTS
        }

    def build(self, name="package"):
        output = self.parent / name
        result = builder.build_offline_review_package(
            output,
            operation_id=OPERATION,
            candidate_head=HEAD,
            artifacts=self.artifacts,
        )
        return output, result

    def test_builder_is_deterministic_exact_and_self_verified(self):
        first, first_result = self.build("first")
        second, second_result = self.build("second")
        self.assertEqual(
            first_result["package_manifest_sha256"],
            second_result["package_manifest_sha256"],
        )
        self.assertEqual(
            {path.name: path.read_bytes() for path in first.iterdir()},
            {path.name: path.read_bytes() for path in second.iterdir()},
        )
        self.assertEqual(
            {path.name for path in first.iterdir()},
            lineage.REQUIRED_ARTIFACTS | {"PACKAGE_MANIFEST.json"},
        )
        verified = lineage.verify_package(
            first,
            expected_manifest_sha256=first_result["package_manifest_sha256"],
            expected_head=HEAD,
        )
        self.assertEqual(verified["bindings"]["operation_id"], OPERATION)
        self.assertFalse(first_result["historical_equivalence"])
        self.assertFalse(first_result["r5_created"])
        self.assertFalse(first_result["production_capable"])
        self.assertEqual(first_result["execution_approval"], "NOT_GRANTED")

    def test_builder_refuses_overwrite_extra_artifact_and_historical_identity(self):
        existing = self.parent / "existing"
        existing.mkdir()
        with self.assertRaisesRegex(lineage.NewLineageStop, "BUILD_OUTPUT_EXISTS"):
            builder.build_offline_review_package(
                existing,
                operation_id=OPERATION,
                candidate_head=HEAD,
                artifacts=self.artifacts,
            )
        extra = dict(self.artifacts)
        extra["UNBOUND.json"] = {}
        with self.assertRaisesRegex(lineage.NewLineageStop, "ALLOWLIST_MISMATCH"):
            builder.build_offline_review_package(
                self.parent / "extra",
                operation_id=OPERATION,
                candidate_head=HEAD,
                artifacts=extra,
            )
        with self.assertRaisesRegex(lineage.NewLineageStop, "HISTORICAL_R4_OPERATION_RETIRED"):
            builder.build_offline_review_package(
                self.parent / "historical",
                operation_id=lineage.HISTORICAL_R4_OPERATION,
                candidate_head=HEAD,
                artifacts=self.artifacts,
            )
        self.assertFalse((self.parent / "historical").exists())

    def test_invalid_input_leaves_no_published_or_staging_package(self):
        recovery = dict(self.artifacts["RECOVERY_CONTRACT.json"])
        recovery["automatic_retry"] = True
        self.artifacts["RECOVERY_CONTRACT.json"] = recovery
        output = self.parent / "invalid"
        with self.assertRaisesRegex(lineage.NewLineageStop, "RECOVERY_CONTRACT_BOUNDARY_INVALID"):
            builder.build_offline_review_package(
                output,
                operation_id=OPERATION,
                candidate_head=HEAD,
                artifacts=self.artifacts,
            )
        self.assertFalse(output.exists())
        self.assertEqual(
            list(self.parent.glob(".agent-hub-new-lineage-build-*")), []
        )

    def test_closed_end_to_end_rehearsal_passes_once_and_verifies_terminal(self):
        package, built = self.build()
        result = rehearsal.rehearse_offline_package(
            package,
            expected_manifest_sha256=built["package_manifest_sha256"],
            expected_head=HEAD,
            signing_key=SIGNING_KEY,
            observed_at="2026-10-01T07:48:36Z",
            starting_audit_count=1998,
        )
        self.assertEqual(result["status"], "OFFLINE_END_TO_END_REHEARSAL_PASS")
        self.assertEqual(
            result["terminal"]["terminal_state"],
            "OFFLINE_FIXTURE_EVIDENCE_PASS",
        )
        self.assertEqual(result["module_post_attempts"], 0)
        self.assertEqual(result["observed_fixture_attempts"], 1)
        self.assertFalse(result["automatic_retry"])
        self.assertFalse(result["automatic_rollback_after_post"])
        self.assertEqual(
            result["production_interaction"], "NOT_PERFORMED_BY_THIS_MODULE"
        )
        with self.assertRaisesRegex(
            lineage.NewLineageStop, "OFFLINE_OPERATION_ALREADY_STARTED"
        ):
            rehearsal.rehearse_offline_package(
                package,
                expected_manifest_sha256=built["package_manifest_sha256"],
                expected_head=HEAD,
                signing_key=SIGNING_KEY,
                observed_at="2026-10-01T07:48:36Z",
            )

    def test_ambiguous_rehearsal_holds_without_retry_or_rollback(self):
        package, built = self.build()
        with self.assertRaisesRegex(
            lineage.OfflineOwnerReviewHold,
            "RAW_HTTP_SEMANTIC_RECEIPT_MISMATCH",
        ):
            rehearsal.rehearse_offline_package(
                package,
                expected_manifest_sha256=built["package_manifest_sha256"],
                expected_head=HEAD,
                signing_key=SIGNING_KEY,
                observed_at="2026-10-01T07:48:36Z",
                fault_mode="RAW_RECEIPT_MISMATCH",
            )
        terminal = lineage.verify_offline_terminal_journal(
            package,
            expected_manifest_sha256=built["package_manifest_sha256"],
            expected_head=HEAD,
        )
        self.assertEqual(
            terminal["terminal_state"],
            "POST_OUTCOME_AMBIGUOUS_HOLD_OWNER_REVIEW",
        )
        self.assertEqual(terminal["module_post_attempts"], 0)
        self.assertEqual(terminal["observed_fixture_attempts"], 1)
        self.assertFalse(terminal["automatic_retry"])
        self.assertFalse(terminal["automatic_rollback_after_post"])

    def test_terminal_verifier_rejects_journal_tamper(self):
        package, built = self.build()
        rehearsal.rehearse_offline_package(
            package,
            expected_manifest_sha256=built["package_manifest_sha256"],
            expected_head=HEAD,
            signing_key=SIGNING_KEY,
            observed_at="2026-10-01T07:48:36Z",
        )
        journal = (
            package.parent
            / lineage.OFFLINE_EVIDENCE_DIRECTORY
            / OPERATION
            / "journal.json"
        )
        value = json.loads(journal.read_text(encoding="utf-8"))
        value["automatic_retry"] = True
        write_json(journal, value)
        with self.assertRaisesRegex(
            lineage.NewLineageStop, "OFFLINE_TERMINAL_BINDING_INVALID"
        ):
            lineage.verify_offline_terminal_journal(
                package,
                expected_manifest_sha256=built["package_manifest_sha256"],
                expected_head=HEAD,
            )

    def test_builder_and_rehearsal_have_no_transport_or_process_surface(self):
        for module in (builder, rehearsal):
            source = Path(module.__file__).read_text(encoding="utf-8")
            for forbidden in (
                "import subprocess",
                "import socket",
                "import requests",
                "import paramiko",
                "transport=",
                "callback=",
            ):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
