"""Offline-only tests for the new one-delivery lineage contract."""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate2_digest_contract as digest_contract
import one_delivery_new_lineage as lineage


HEAD = "a417b7caea23f4e886ba3b4100e18d8adec1c679"
OPERATION = "AH-P9-ONE-DELIVERY-NL1-11111111-1111-4111-8111-111111111111"
CAMPAIGN = "CMP-AHINTERNAL-P9SLACOHORT-202609-01"
DELIVERY = "P9DELIVERY:LOCAL-NEW-LINEAGE-01"
SOURCE_EVENT = "LOCAL-NEW-LINEAGE-EVENT-01"
LEAD = "LOCAL-NEW-LINEAGE-LEAD-01"
SOURCE_RECORD = "1" * 64
SOURCE_AUDIT = "2" * 64
SIGNING_KEY = "LOCAL-SYNTHETIC-RECEIPT-KEY-0123456789abcdef"


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def file_entry(path: Path) -> dict[str, object]:
    return {
        "path": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "length_bytes": path.stat().st_size,
    }


def package_fixture(root: Path) -> str:
    cohort = {
        "classification": "phase9_internal_non_customer",
        "canonical_campaign_id": CAMPAIGN,
        "subject_ref": f"lead:{LEAD}",
        "owner_id": "LOCAL-NEW-LINEAGE-OWNER",
        "owner_approval_sha256": "3" * 64,
        "non_customer_proof_sha256": "4" * 64,
        "scope": "phase9_one_internal_task_report_audit_one_nba_review",
        "customer_contact": False,
        "commercial_attribution": False,
        "automation_enabled": False,
        "reporting_exclusions": {
            "commercial_leads": True,
            "sales_revenue_attribution": True,
            "customer_sla_metrics": True,
            "provider_spend": True,
            "external_notifications": True,
        },
    }
    event = {
        "source_event_id": SOURCE_EVENT,
        "source_system": "espocrm",
        "event_type": "lead_created",
        "occurred_at": "2026-09-14T12:00:00Z",
        "channel": "internal",
        "canonical_campaign_id": CAMPAIGN,
        "source_account_id": None,
        "source_campaign_id": None,
        "source_adset_id": None,
        "source_ad_group_id": None,
        "source_ad_id": None,
        "lead_id": LEAD,
        "opportunity_id": None,
        "utm_source": None,
        "utm_medium": None,
        "utm_campaign": None,
        "utm_content": None,
        "landing_page": None,
        "metadata": {
            "phase9_internal_cohort": cohort,
            "source_record_sha256": SOURCE_RECORD,
            "source_audit_sha256": SOURCE_AUDIT,
        },
    }
    envelope = {
        "delivery_id": DELIVERY,
        "producer": "local_new_lineage_fixture",
        "source_system": "espocrm",
        "attempt_number": 1,
        "max_attempts": 1,
        "sent_at": "2026-09-14T12:00:01Z",
        "events": [event],
        "metadata": {},
    }
    binding = {
        "cohort": cohort,
        "delivery_id": DELIVERY,
        "source_event_id": SOURCE_EVENT,
        "occurred_at": "2026-09-14T12:00:00Z",
        "source_record_sha256": SOURCE_RECORD,
        "source_audit_sha256": SOURCE_AUDIT,
        "delivery_payload_sha256": lineage.canonical_digest(envelope),
    }
    values = {
        "DELIVERY_BINDING.json": binding,
        "DELIVERY_ENVELOPE.json": envelope,
        "CANDIDATE_IMAGE.json": {
            "schema": "npd.agent-hub.phase9.one-delivery-image-binding.v1",
            "lineage": lineage.LINEAGE,
            "application_source_head": HEAD,
            "candidate_docker_config_sha256": "5" * 64,
            "rollback_docker_config_sha256": "6" * 64,
            "candidate_staged": False,
            "image_loaded": False,
            "production_build_authorized": False,
        },
        "PREFLIGHT_CONTRACT.json": {
            "schema": "npd.agent-hub.phase9.one-delivery-preflight-contract.v1",
            "lineage": lineage.LINEAGE,
            "mode": "OFFLINE_CONTRACT_ONLY",
            "production_probe_performed": False,
            "claim_absent": True,
            "candidate_staged": False,
            "delivery_absent": True,
            "fresh_jit_required": True,
            "video_factory_db0_counter_evidence": "OUT_OF_SCOPE_NOT_COLLECTED",
            "production_qualification": "BLOCKED_EXTERNAL_READONLY_EVIDENCE_REQUIRED",
        },
        "RECOVERY_CONTRACT.json": {
            "schema": "npd.agent-hub.phase9.one-delivery-recovery-contract.v1",
            "lineage": lineage.LINEAGE,
            "max_attempts": 1,
            "automatic_retry": False,
            "pre_post_failure": "ABORT_BEFORE_POST",
            "post_outcome_ambiguous": "HOLD_OWNER_REVIEW",
            "automatic_rollback_after_post": False,
            "rollback_source_status": "NEW_LINEAGE_REQUIRED_NOT_HISTORICAL",
            "owner_recovery_gate_required": True,
        },
        "READBACK_CONTRACT.json": {
            "schema": "npd.agent-hub.phase9.one-delivery-readback-contract.v1",
            "lineage": lineage.LINEAGE,
            "touchpoint_delta": 1,
            "source_event_match_delta": 1,
            "delivery_receipt_delta": 1,
            "campaign_audit_delta": 2,
            "latest_campaign_audit_types": list(lineage.AUDIT_TYPES),
            "dead_letter_delta": 0,
            "receipt_valid_required": True,
            "internal_audit_cap": 2000,
            "minimum_capacity_before_post": 2,
        },
        "CAMPAIGN_DIGEST_EVIDENCE.json": digest_contract.build_evidence(
            campaign_id=CAMPAIGN,
            http_status=200,
            raw_response=b'{"campaign":"original-http-bytes"}\n',
            semantic_model_sha256="7" * 64,
        ),
    }
    for name, value in values.items():
        write_json(root / name, value)
    reseal(root, operation=OPERATION)
    return hashlib.sha256((root / "PACKAGE_MANIFEST.json").read_bytes()).hexdigest()


def reseal(root: Path, *, operation: str | None = None) -> str:
    manifest_path = root / "PACKAGE_MANIFEST.json"
    old_manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    operation = operation or old_manifest.get("operation_id", OPERATION)
    envelope = json.loads((root / "DELIVERY_ENVELOPE.json").read_text())
    binding = json.loads((root / "DELIVERY_BINDING.json").read_text())
    binding["delivery_payload_sha256"] = lineage.canonical_digest(envelope)
    write_json(root / "DELIVERY_BINDING.json", binding)
    campaign_evidence = json.loads((root / "CAMPAIGN_DIGEST_EVIDENCE.json").read_text())
    bindings = {
        "schema": "npd.agent-hub.phase9.one-delivery-bindings.v1",
        "lineage": lineage.LINEAGE,
        "operation_id": operation,
        "candidate_head": HEAD,
        "campaign_id": CAMPAIGN,
        "delivery_id": DELIVERY,
        "source_event_id": SOURCE_EVENT,
        "subject_ref": f"lead:{LEAD}",
        "campaign_raw_transport_sha256": campaign_evidence["raw_transport_sha256"],
        "campaign_semantic_model_sha256": campaign_evidence["semantic_model_sha256"],
        "delivery_binding_sha256": lineage.sha256_file(root / "DELIVERY_BINDING.json"),
        "delivery_envelope_sha256": lineage.sha256_file(root / "DELIVERY_ENVELOPE.json"),
        "candidate_image_sha256": lineage.sha256_file(root / "CANDIDATE_IMAGE.json"),
        "preflight_contract_sha256": lineage.sha256_file(root / "PREFLIGHT_CONTRACT.json"),
        "recovery_contract_sha256": lineage.sha256_file(root / "RECOVERY_CONTRACT.json"),
        "readback_contract_sha256": lineage.sha256_file(root / "READBACK_CONTRACT.json"),
        "campaign_digest_evidence_sha256": lineage.sha256_file(root / "CAMPAIGN_DIGEST_EVIDENCE.json"),
    }
    write_json(root / "OPERATION_BINDINGS.json", bindings)
    entries = [
        file_entry(path)
        for path in sorted(root.iterdir())
        if path.is_file() and path.name != "PACKAGE_MANIFEST.json"
    ]
    manifest = {
        "schema": lineage.MANIFEST_SCHEMA,
        "lineage": lineage.LINEAGE,
        "mode": "OFFLINE_REVIEW_ONLY",
        "historical_equivalence": False,
        "r5_created": False,
        "production_capable": False,
        "execution_approval": "NOT_GRANTED",
        "operation_id": operation,
        "candidate_head": HEAD,
        "artifacts": entries,
    }
    write_json(manifest_path, manifest)
    return lineage.sha256_file(manifest_path)


def snapshot(*, touchpoints=0, source_events=0, receipts=0, audits=1,
             audit_types=None, dead_letters=0, exact=True, limited=False):
    return {
        "schema": lineage.READBACK_SCHEMA,
        "lineage": lineage.LINEAGE,
        "campaign_id": CAMPAIGN,
        "delivery_id": DELIVERY,
        "source_event_id": SOURCE_EVENT,
        "subject_touchpoint_count": touchpoints,
        "source_event_match_count": source_events,
        "delivery_receipt_match_count": receipts,
        "campaign_audit_count": audits,
        "latest_campaign_audit_types": audit_types or [],
        "dead_letter_match_count": dead_letters,
        "counts_are_exact": exact,
        "query_limit_applied": limited,
        "internal_audit_cap": 2000,
        "runtime_mode": "phase9_delivery",
        "scheduler_enabled": False,
    }


def receipt(payload_digest="PLACEHOLDER"):
    value = {
        "receipt_id": "adr_" + "8" * 24,
        "delivery_id": DELIVERY,
        "producer": "local_new_lineage_fixture",
        "source_system": "espocrm",
        "attempt_number": 1,
        "max_attempts": 1,
        "outcome": "accepted",
        "payload_digest": payload_digest,
        "snapshot_id": "LOCAL-SNAPSHOT",
        "received": 1,
        "resolved": 1,
        "inserted": 1,
        "duplicates": 0,
        "unknown": 0,
        "conflicts": 0,
        "retry_allowed": False,
        "next_retry_at": None,
        "dead_lettered": False,
        "error_code": None,
        "received_at": "2026-09-14T12:00:02Z",
        "key_id": "local-key",
        "signature": "",
        "shadow_mode": True,
        "external_writes_enabled": False,
    }
    unsigned = {name: item for name, item in value.items() if name != "signature"}
    value["signature"] = "hmac-sha256:" + hmac.new(
        SIGNING_KEY.encode("utf-8"), lineage.canonical_bytes(unsigned), hashlib.sha256
    ).hexdigest()
    return value


def receipt_verification(value):
    return {
        "receipt_id": value["receipt_id"],
        "valid": True,
        "key_id": value["key_id"],
        "detail": "Signature is valid.",
    }


class NewLineagePackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "package"
        self.root.mkdir()
        self.anchor = package_fixture(self.root)

    def verify(self):
        return lineage.verify_package(
            self.root,
            expected_manifest_sha256=self.anchor,
            expected_head=HEAD,
        )

    def test_exact_package_is_explicitly_offline_and_not_historical_or_r5(self):
        value = self.verify()
        self.assertEqual(value["bindings"]["operation_id"], OPERATION)
        self.assertFalse(value["manifest"]["historical_equivalence"])
        self.assertFalse(value["manifest"]["r5_created"])
        self.assertFalse(value["manifest"]["production_capable"])
        self.assertEqual(value["manifest"]["execution_approval"], "NOT_GRANTED")

    def test_historical_r4_and_rca_identifiers_are_rejected(self):
        for operation, reason in (
            (lineage.HISTORICAL_R4_OPERATION, "HISTORICAL_R4_OPERATION_RETIRED"),
            ("PHASE9-LIMITED-PILOT-RCA06-11111111-1111-4111-8111-111111111111",
             "NEW_LINEAGE_OPERATION_ID_INVALID"),
        ):
            with self.subTest(operation=operation):
                self.anchor = reseal(self.root, operation=operation)
                with self.assertRaisesRegex(lineage.NewLineageStop, reason):
                    self.verify()
                self.anchor = reseal(self.root, operation=OPERATION)

    def test_missing_recovery_preflight_image_or_bindings_fails_closed(self):
        for name in (
            "RECOVERY_CONTRACT.json",
            "PREFLIGHT_CONTRACT.json",
            "CANDIDATE_IMAGE.json",
            "OPERATION_BINDINGS.json",
        ):
            with self.subTest(name=name):
                backup = (self.root / name).read_bytes()
                (self.root / name).unlink()
                manifest = json.loads((self.root / "PACKAGE_MANIFEST.json").read_text())
                manifest["artifacts"] = [row for row in manifest["artifacts"] if row["path"] != name]
                write_json(self.root / "PACKAGE_MANIFEST.json", manifest)
                self.anchor = lineage.sha256_file(self.root / "PACKAGE_MANIFEST.json")
                with self.assertRaisesRegex(lineage.NewLineageStop, "REQUIRED_ARTIFACT_MISSING"):
                    self.verify()
                (self.root / name).write_bytes(backup)
                self.anchor = reseal(self.root)

    def test_path_traversal_duplicate_json_and_tampering_are_rejected(self):
        manifest = json.loads((self.root / "PACKAGE_MANIFEST.json").read_text())
        manifest["artifacts"][0]["path"] = "../escape.json"
        write_json(self.root / "PACKAGE_MANIFEST.json", manifest)
        self.anchor = lineage.sha256_file(self.root / "PACKAGE_MANIFEST.json")
        with self.assertRaisesRegex(lineage.NewLineageStop, "ARTIFACT_PATH_INVALID"):
            self.verify()

        self.anchor = reseal(self.root)
        raw = (self.root / "PACKAGE_MANIFEST.json").read_text()
        raw = raw.replace('"mode": "OFFLINE_REVIEW_ONLY",',
                          '"mode": "OFFLINE_REVIEW_ONLY",\n  "mode": "OFFLINE_REVIEW_ONLY",', 1)
        (self.root / "PACKAGE_MANIFEST.json").write_text(raw)
        self.anchor = lineage.sha256_file(self.root / "PACKAGE_MANIFEST.json")
        with self.assertRaisesRegex(lineage.NewLineageStop, "DUPLICATE_JSON_KEY"):
            self.verify()

        self.anchor = reseal(self.root)
        with (self.root / "RECOVERY_CONTRACT.json").open("ab") as handle:
            handle.write(b" ")
        with self.assertRaisesRegex(lineage.NewLineageStop, "ARTIFACT_HASH_OR_LENGTH_MISMATCH"):
            self.verify()

    def test_attempt_two_and_retry_are_rejected_even_when_resealed(self):
        envelope = json.loads((self.root / "DELIVERY_ENVELOPE.json").read_text())
        envelope["attempt_number"] = 2
        envelope["max_attempts"] = 2
        write_json(self.root / "DELIVERY_ENVELOPE.json", envelope)
        self.anchor = reseal(self.root)
        with self.assertRaisesRegex(lineage.NewLineageStop, "ONE_ATTEMPT_NO_RETRY_REQUIRED"):
            self.verify()

    def test_cohort_missing_extra_malformed_and_timestamp_types_fail_when_resealed(self):
        mutations = (
            ("missing_owner", lambda cohort, binding, envelope: cohort.pop("owner_id")),
            ("extra_field", lambda cohort, binding, envelope: cohort.update({"unexpected": True})),
            ("empty_owner", lambda cohort, binding, envelope: cohort.update({"owner_id": ""})),
            ("wrong_scope", lambda cohort, binding, envelope: cohort.update({"scope": "production"})),
            ("wrong_boolean_type", lambda cohort, binding, envelope: cohort.update({"customer_contact": 0})),
            ("naive_timestamp", lambda cohort, binding, envelope: binding.update({"occurred_at": "2026-09-14T12:00:00"})),
        )
        for name, mutate in mutations:
            with self.subTest(name=name):
                package_fixture(self.root)
                binding = json.loads((self.root / "DELIVERY_BINDING.json").read_text())
                envelope = json.loads((self.root / "DELIVERY_ENVELOPE.json").read_text())
                cohort = binding["cohort"]
                mutate(cohort, binding, envelope)
                envelope["events"][0]["metadata"]["phase9_internal_cohort"] = cohort
                write_json(self.root / "DELIVERY_BINDING.json", binding)
                write_json(self.root / "DELIVERY_ENVELOPE.json", envelope)
                self.anchor = reseal(self.root)
                with self.assertRaises(lineage.NewLineageStop):
                    self.verify()

    def test_extra_artifact_is_denied_by_exact_allowlist(self):
        write_json(self.root / "UNBOUND_EXTRA.json", {"offline": True})
        self.anchor = reseal(self.root)
        with self.assertRaisesRegex(lineage.NewLineageStop, "ARTIFACT_ALLOWLIST_MISMATCH"):
            self.verify()

    def test_campaign_digest_keeps_original_http_and_semantic_domains_separate(self):
        evidence = self.verify()["campaign_digest_evidence"]
        self.assertNotEqual(evidence["raw_transport_sha256"], evidence["semantic_model_sha256"])
        raw = b'{"campaign":"original-http-bytes"}\n'
        self.assertEqual(evidence["raw_transport_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertFalse(evidence["body_exported"])


class OfflineFixtureEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "package"
        self.root.mkdir()
        self.anchor = package_fixture(self.root)
        self.verified = lineage.verify_package(self.root)
        self.before = snapshot()
        self.after = snapshot(
            touchpoints=1,
            source_events=1,
            receipts=1,
            audits=3,
            audit_types=list(lineage.AUDIT_TYPES),
        )
        self.receipt = receipt(
            self.verified["delivery_binding"]["delivery_payload_sha256"]
        )

    @property
    def evidence_directory(self):
        return (
            self.root.parent
            / lineage.OFFLINE_EVIDENCE_DIRECTORY
            / OPERATION
        )

    @property
    def journal(self):
        return self.evidence_directory / "journal.json"

    def begin(self, **kwargs):
        return lineage.begin_offline_fixture(
            self.root,
            expected_manifest_sha256=self.anchor,
            expected_head=HEAD,
            before=kwargs.pop("before", self.before),
            **kwargs,
        )

    def complete(self, **kwargs):
        value = kwargs.pop("semantic_receipt", self.receipt)
        raw = kwargs.pop(
            "raw_response",
            json.dumps(value, ensure_ascii=False, sort_keys=False).encode("utf-8") + b"\n",
        )
        return lineage.complete_offline_fixture(
            self.root,
            expected_manifest_sha256=self.anchor,
            expected_head=HEAD,
            before=kwargs.pop("before", self.before),
            after=kwargs.pop("after", self.after),
            status_code=kwargs.pop("status_code", 200),
            raw_response=raw,
            semantic_receipt=value,
            receipt_verification=kwargs.pop(
                "receipt_verification", receipt_verification(value)
            ),
            verification_keys=kwargs.pop(
                "verification_keys", {value.get("key_id", "missing"): SIGNING_KEY}
            ),
            **kwargs,
        )

    def test_durable_pre_post_intent_and_exact_fixture_evidence_pass(self):
        intent = self.begin()
        self.assertEqual(intent["status"], "OFFLINE_FIXTURE_PRE_POST_INTENT")
        claim = json.loads((self.evidence_directory / "claim.json").read_text())
        self.assertEqual(claim["state"], "OFFLINE_FIXTURE_PRE_POST_INTENT")
        result = self.complete()
        self.assertEqual(result["status"], "OFFLINE_FIXTURE_EVIDENCE_PASS")
        self.assertEqual(result["module_post_attempts"], 0)
        self.assertEqual(result["observed_fixture_attempts"], 1)
        self.assertNotIn("production_writes", result)
        self.assertEqual(
            result["production_interaction"], "NOT_PERFORMED_BY_THIS_MODULE"
        )
        self.assertFalse(result["response_digests"]["raw_body_persisted"])
        self.assertNotEqual(
            result["response_digests"]["raw_http_response_sha256"],
            result["response_digests"]["semantic_receipt_sha256"],
        )
        journal = json.loads(self.journal.read_text())
        self.assertEqual(journal["state"], "OFFLINE_FIXTURE_EVIDENCE_PASS")
        self.assertEqual(journal["module_post_attempts"], 0)
        self.assertFalse(journal["automatic_retry"])
        self.assertFalse(journal["automatic_rollback_after_post"])
        with self.assertRaisesRegex(lineage.NewLineageStop, "ALREADY_STARTED"):
            self.complete()

    def test_invalid_observation_is_explicit_hold_with_original_cause(self):
        self.begin()
        with self.assertRaisesRegex(
            lineage.OfflineOwnerReviewHold,
            "POST_OUTCOME_AMBIGUOUS_HOLD_OWNER_REVIEW:RAW_HTTP_SEMANTIC_RECEIPT_MISMATCH",
        ) as caught:
            self.complete(raw_response=b"{}\n")
        self.assertEqual(caught.exception.original_cause, "RAW_HTTP_SEMANTIC_RECEIPT_MISMATCH")
        journal = json.loads(self.journal.read_text())
        self.assertEqual(journal["state"], "POST_OUTCOME_AMBIGUOUS_HOLD_OWNER_REVIEW")
        self.assertTrue(journal["owner_review_required"])
        with self.assertRaisesRegex(lineage.NewLineageStop, "ALREADY_STARTED"):
            self.begin()

    def test_no_transport_injection_point_and_spoof_has_no_effect(self):
        class SpoofedTransport:
            kind = "IN_PROCESS_FAKE"

            def __init__(self):
                self.side_effects = 0

            def post(self, value):
                self.side_effects += 1

        spoof = SpoofedTransport()
        with self.assertRaises(TypeError):
            self.begin(transport=spoof)
        self.assertEqual(spoof.side_effects, 0)
        self.assertFalse(self.evidence_directory.exists())
        self.assertFalse(hasattr(lineage, "run_offline_simulation"))

    def test_atomic_operation_claim_has_one_winner_under_race(self):
        barrier = threading.Barrier(2)
        outcomes = []

        def contender():
            barrier.wait()
            try:
                self.begin()
                outcomes.append("won")
            except lineage.NewLineageStop as error:
                outcomes.append(str(error))

        threads = [threading.Thread(target=contender) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertCountEqual(outcomes, ["won", "OFFLINE_OPERATION_ALREADY_STARTED"])
        self.assertTrue((self.evidence_directory / "claim.json").is_file())

    def test_journal_path_is_derived_and_alternate_path_is_ignored(self):
        alternate = Path(self.temp.name) / "caller-selected-journal.json"
        alternate.write_text('{"state":"spoofed"}\n', encoding="utf-8")
        result = self.begin()
        self.assertEqual(result["evidence_directory"], str(self.evidence_directory))
        self.assertEqual(json.loads(alternate.read_text())["state"], "spoofed")
        self.assertTrue(self.journal.is_file())

    def test_final_journal_failure_still_returns_explicit_hold(self):
        self.begin()
        with mock.patch.object(
            lineage,
            "_write_journal",
            side_effect=lineage.NewLineageStop("JOURNAL_DURABILITY_FAILURE"),
        ):
            with self.assertRaisesRegex(
                lineage.OfflineOwnerReviewHold,
                "POST_OUTCOME_AMBIGUOUS_HOLD_OWNER_REVIEW:FINAL_JOURNAL_DURABILITY_FAILURE",
            ) as caught:
                self.complete()
        self.assertIn("JOURNAL_DURABILITY_FAILURE", caught.exception.journal_cause)

    def test_tampered_or_missing_signature_fails_even_with_true_verification(self):
        for mode in ("tampered", "missing"):
            with self.subTest(mode=mode):
                value = dict(self.receipt)
                if mode == "tampered":
                    value["signature"] = value["signature"][:-1] + (
                        "0" if value["signature"][-1] != "0" else "1"
                    )
                else:
                    value.pop("signature")
                with self.assertRaisesRegex(
                    lineage.NewLineageStop,
                    "RECEIPT_SIGNATURE_INVALID|DELIVERY_RECEIPT_SCHEMA_INVALID",
                ):
                    lineage.verify_readback(
                        self.before,
                        self.after,
                        value,
                        receipt_verification(self.receipt),
                        {"local-key": SIGNING_KEY},
                        self.verified,
                    )

    def test_readback_index_audit_and_capacity_mismatches_hold(self):
        bad_snapshots = (
            snapshot(touchpoints=1, source_events=0, receipts=1, audits=3,
                     audit_types=list(lineage.AUDIT_TYPES)),
            snapshot(touchpoints=1, source_events=1, receipts=0, audits=3,
                     audit_types=list(lineage.AUDIT_TYPES)),
            snapshot(touchpoints=1, source_events=1, receipts=1, audits=2,
                     audit_types=list(lineage.AUDIT_TYPES)),
            snapshot(touchpoints=1, source_events=1, receipts=1, audits=3,
                     audit_types=list(reversed(lineage.AUDIT_TYPES))),
            snapshot(touchpoints=1, source_events=1, receipts=1, audits=3,
                     audit_types=list(lineage.AUDIT_TYPES), limited=True),
        )
        for after in bad_snapshots:
            with self.subTest(after=after):
                with self.assertRaises(lineage.NewLineageStop):
                    lineage.verify_readback(
                        self.before,
                        after,
                        self.receipt,
                        receipt_verification(self.receipt),
                        {"local-key": SIGNING_KEY},
                        self.verified,
                    )

    def test_capacity_boundaries_1998_1999_and_2000_are_exact(self):
        self.before["campaign_audit_count"] = 1998
        intent = self.begin()
        self.assertEqual(intent["status"], "OFFLINE_FIXTURE_PRE_POST_INTENT")
        after = dict(self.after)
        after["campaign_audit_count"] = 2000
        self.assertEqual(self.complete(after=after)["status"], "OFFLINE_FIXTURE_EVIDENCE_PASS")

        for count in (1999, 2000):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / "package"
                root.mkdir()
                anchor = package_fixture(root)
                denied = snapshot(audits=count)
                with self.assertRaisesRegex(lineage.NewLineageStop, "CAPACITY_INSUFFICIENT"):
                    lineage.begin_offline_fixture(
                        root,
                        expected_manifest_sha256=anchor,
                        expected_head=HEAD,
                        before=denied,
                    )
                self.assertFalse((root.parent / lineage.OFFLINE_EVIDENCE_DIRECTORY).exists())


if __name__ == "__main__":
    unittest.main()
