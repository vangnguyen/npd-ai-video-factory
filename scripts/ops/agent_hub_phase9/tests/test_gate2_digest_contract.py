"""Production-shaped Gate-2 digest-domain regression fixtures."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate2_digest_contract as contract


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "gate2_campaign_digest_domains.json"
CAMPAIGN_ID = "CMP-AHINTERNAL-P9SLACOHORT-202609-01"
RAW = "60cb41b0da6384ee8677fff7d7cc5b89d6a759e0355ac6b0c56d8e7ae4c50cd8"
SEMANTIC = "8c06ad499c8bffc40ff26fe2361e0ae7a4226ff4d5d738ecd41f73bc938614ec"


def fixture() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def verify(value: dict[str, object]) -> dict[str, object]:
    return contract.verify_evidence(
        value,
        expected_campaign_id=CAMPAIGN_ID,
        expected_raw_transport_sha256=RAW,
        expected_semantic_model_sha256=SEMANTIC,
    )


class Gate2DigestContractTests(unittest.TestCase):
    def test_exact_sanitized_production_shape_passes(self):
        self.assertEqual(verify(fixture()), fixture())

    def test_old_raw_vs_semantic_comparison_is_reproduced_and_rejected(self):
        value = fixture()
        self.assertNotEqual(value["raw_transport_sha256"], value["semantic_model_sha256"])
        value["semantic_model_sha256"] = value["raw_transport_sha256"]
        with self.assertRaisesRegex(contract.Gate2DigestContractError,
                                    "SEMANTIC_MODEL_DIGEST_MISMATCH"):
            verify(value)

    def test_swapped_domains_are_rejected(self):
        value = fixture()
        value["raw_transport_sha256"], value["semantic_model_sha256"] = (
            value["semantic_model_sha256"], value["raw_transport_sha256"])
        with self.assertRaisesRegex(contract.Gate2DigestContractError,
                                    "RAW_TRANSPORT_DIGEST_MISMATCH"):
            verify(value)

    def test_each_required_field_is_mandatory(self):
        for name in contract.FIELDS:
            with self.subTest(name=name):
                value = fixture()
                value.pop(name)
                with self.assertRaisesRegex(contract.Gate2DigestContractError,
                                            "SCHEMA_INVALID"):
                    verify(value)

    def test_unknown_or_ambiguous_digest_field_is_rejected(self):
        for name in ("campaign_sha256", "response_sha256", "raw_body"):
            with self.subTest(name=name):
                value = fixture()
                value[name] = "x"
                with self.assertRaisesRegex(contract.Gate2DigestContractError,
                                            "SCHEMA_INVALID"):
                    verify(value)

    def test_wrong_types_status_length_and_campaign_are_rejected(self):
        changes = (
            ("campaign_id", "other"),
            ("http_status", True),
            ("http_status", 404),
            ("raw_response_bytes", 0),
            ("raw_response_bytes", True),
            ("raw_transport_sha256", 1),
            ("semantic_model_sha256", "x" * 64),
        )
        for name, changed in changes:
            with self.subTest(name=name, changed=changed):
                value = fixture()
                value[name] = changed
                with self.assertRaises(contract.Gate2DigestContractError):
                    verify(value)

    def test_raw_body_or_secret_export_cannot_be_asserted_safe_by_omission(self):
        for name in ("body_exported", "secrets_exported"):
            value = fixture()
            value[name] = True
            with self.subTest(name=name), self.assertRaises(contract.Gate2DigestContractError):
                verify(value)

    def test_builder_hashes_exact_bytes_and_keeps_semantic_hash_separate(self):
        raw = b'{"campaign":"example"}\n'
        value = contract.build_evidence(
            campaign_id=CAMPAIGN_ID,
            http_status=200,
            raw_response=raw,
            semantic_model_sha256=SEMANTIC,
        )
        self.assertEqual(value["raw_response_bytes"], len(raw))
        self.assertEqual(value["raw_transport_sha256"], contract.raw_transport_sha256(raw))
        self.assertEqual(value["semantic_model_sha256"], SEMANTIC)
        self.assertNotEqual(value["raw_transport_sha256"], SEMANTIC)

    def test_builder_requires_literal_bytes_and_valid_semantic_digest(self):
        with self.assertRaisesRegex(contract.Gate2DigestContractError,
                                    "RAW_HTTP_RESPONSE_BYTES_REQUIRED"):
            contract.build_evidence(campaign_id=CAMPAIGN_ID, http_status=200,
                                    raw_response="{}", semantic_model_sha256=SEMANTIC)
        with self.assertRaisesRegex(contract.Gate2DigestContractError,
                                    "SEMANTIC_MODEL_SHA256_INVALID"):
            contract.build_evidence(campaign_id=CAMPAIGN_ID, http_status=200,
                                    raw_response=b"{}", semantic_model_sha256=RAW[:-1])


if __name__ == "__main__":
    unittest.main()
