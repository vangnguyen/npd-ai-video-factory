"""All fixtures/archives/commits are local synthetic data, not production writes."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from threading import Barrier, Thread
import unittest

PATH = Path(__file__).resolve().parents[1] / "retention_design.py"
SPEC = importlib.util.spec_from_file_location("rca16_retention_design", PATH)
m = importlib.util.module_from_spec(SPEC); sys.modules[SPEC.name] = m; SPEC.loader.exec_module(m)
LEDGER = "npd:agent-hub:v1:attribution-os:audit"
AT = "2026-09-14T00:00:00+00:00"
POLICY = m.Policy("SYNTHETIC_RCA16_POLICY_NOT_OWNER_DISPOSITION", (
    ("provider_health_scheduled_evaluation", m.Category.ARCHIVABLE),
    ("phase9_terminal_provenance", m.Category.PROTECTED)), True)


def entry(index, *, kind="provider_health_scheduled_evaluation", metadata=None, links=(), ledger=LEDGER):
    value = {"event_id": "static_audit_" + str(index), "event_type": kind, "created_at": AT,
             "metadata": metadata or {}}
    return m.Entry(ledger, json.dumps(value, indent=2, ensure_ascii=False).encode("utf8") + b"\r\n", links)


class RetentionDesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = tuple(entry(i) for i in range(5000))

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.archive = m.LocalArchive(Path(self.temporary.name))

    def append(self, ledger, added=None, *, observation=None, receipts=None, commit="static_commit_a"):
        return ledger.append(observation or ledger.observe(), added or (entry(5001),),
                             commit_id=commit, archive=self.archive, receipts=receipts or {})

    def preserve(self, ledger, observation, added):
        return {row.identity: self.archive.preserve(row, ledger.policy, AT)
                for row in ledger.prospective_evictions(observation, added)}

    def test_4999_append_has_no_eviction(self):
        ledger = m.ReferenceLedger(self.rows[:-1], POLICY)
        result = self.append(ledger)
        self.assertEqual(len(ledger.rows), 5000); self.assertEqual(result["evicted_ids"], [])

    def test_5000_observation_is_read_only(self):
        ledger = m.ReferenceLedger(self.rows, POLICY)
        observation = ledger.observe()
        self.assertEqual(len(observation.rows), 5000); self.assertEqual(ledger.version, 0)

    def test_append_at_cap_archives_exact_oldest_then_trims(self):
        ledger = m.ReferenceLedger(self.rows, POLICY); observation = ledger.observe(); added = (entry(5001),)
        receipts = self.preserve(ledger, observation, added)
        result = self.append(ledger, added, observation=observation, receipts=receipts)
        self.assertEqual(result["evicted_ids"], [self.rows[0].identity]); self.assertEqual(len(ledger.rows), 5000)
        self.archive.verify(self.rows[0], POLICY, receipts[self.rows[0].identity])
        self.assertFalse(result["execution_authorized"]); self.assertEqual(result["production_writes"], 0)

    def test_two_append_batch_is_one_commit_and_two_evictions(self):
        ledger = m.ReferenceLedger(self.rows, POLICY); observation = ledger.observe(); added = (entry(5001), entry(5002))
        result = self.append(ledger, added, observation=observation, receipts=self.preserve(ledger, observation, added))
        self.assertEqual(result["evicted_ids"], [r.identity for r in self.rows[:2]]); self.assertEqual(ledger.version, 1)

    def test_protected_oldest_blocks_even_with_archive(self):
        ledger = m.ReferenceLedger((entry(0, kind="phase9_terminal_provenance"), *self.rows[1:]), POLICY)
        observation = ledger.observe(); receipts = self.preserve(ledger, observation, (entry(5001),))
        with self.assertRaisesRegex(m.RetentionBlocked, "PROTECTED_EVICTION_BOUNDARY"):
            self.append(ledger, observation=observation, receipts=receipts)
        self.assertEqual(ledger.rows, observation.rows); self.assertEqual(ledger.version, 0)

    def test_active_operation_reference_blocks_archivable_class(self):
        first = entry(0, metadata={"operation_id": "static_owned_operation_reference"})
        ledger = m.ReferenceLedger((first, *self.rows[1:]), POLICY)
        ledger.hold(reference="static_owned_operation_reference"); observation = ledger.observe()
        with self.assertRaisesRegex(m.RetentionBlocked, "PROTECTED_EVICTION_BOUNDARY"):
            self.append(ledger, observation=observation, receipts=self.preserve(ledger, observation, (entry(5001),)))

    def test_new_hold_after_observation_aborts_CAS(self):
        ledger = m.ReferenceLedger(self.rows, POLICY); observation = ledger.observe()
        receipts = self.preserve(ledger, observation, (entry(5001),)); ledger.hold(event_id=self.rows[0].identity)
        with self.assertRaisesRegex(m.RetentionBlocked, "LEDGER_OR_POLICY_CHANGED_STOP_NO_RETRY"):
            self.append(ledger, observation=observation, receipts=receipts)
        self.assertEqual(ledger.rows, observation.rows)

    def test_held_linked_snapshot_blocks_archivable_event(self):
        linked = m.LinkedBytes("phs_static", b'{"snapshot_id":"phs_static"}')
        first = entry(0, metadata={"snapshot_id": "phs_static"}, links=(linked,))
        ledger = m.ReferenceLedger((first, *self.rows[1:]), POLICY)
        ledger.hold(reference="phs_static"); observation = ledger.observe()
        with self.assertRaisesRegex(m.RetentionBlocked, "PROTECTED_EVICTION_BOUNDARY"):
            self.append(ledger, observation=observation, receipts=self.preserve(ledger, observation, (entry(5001),)))

    def test_concurrent_writers_one_wins_other_stops_without_retry(self):
        ledger = m.ReferenceLedger(self.rows[:-1], POLICY); observation = ledger.observe(); barrier = Barrier(2); results = []
        def writer(index):
            barrier.wait()
            try: results.append(self.append(ledger, (entry(index),), observation=observation, commit="static_commit_" + str(index)))
            except m.RetentionBlocked as error: results.append(str(error))
        threads = [Thread(target=writer, args=(5001,)), Thread(target=writer, args=(5002,))]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(sum(isinstance(value, dict) for value in results), 1)
        self.assertIn("LEDGER_OR_POLICY_CHANGED_STOP_NO_RETRY", results)
        self.assertEqual(ledger.version, 1); self.assertEqual(len(ledger.rows), 5000)

    def test_archive_failure_does_not_append_or_trim(self):
        ledger = m.ReferenceLedger(self.rows, POLICY); observation = ledger.observe()
        self.archive._write = lambda *args: (_ for _ in ()).throw(OSError("static archive failure"))
        with self.assertRaises(OSError): self.preserve(ledger, observation, (entry(5001),))
        self.assertEqual(ledger.rows, observation.rows); self.assertEqual(ledger.version, 0)

    def test_missing_archive_rejected(self):
        ledger = m.ReferenceLedger(self.rows, POLICY)
        with self.assertRaisesRegex(m.RetentionBlocked, "ARCHIVE_MISSING"): self.append(ledger)
        self.assertEqual(ledger.rows, self.rows)

    def test_one_changed_raw_archive_byte_rejected(self):
        ledger = m.ReferenceLedger(self.rows, POLICY); observation = ledger.observe()
        receipts = self.preserve(ledger, observation, (entry(5001),))
        self.archive._path("blobs", m.digest(self.rows[0].raw)).write_bytes(self.rows[0].raw + b" ")
        with self.assertRaisesRegex(m.RetentionBlocked, "ARCHIVE_RAW_DIGEST_MISMATCH"):
            self.append(ledger, observation=observation, receipts=receipts)
        self.assertEqual(ledger.rows, self.rows)

    def test_archive_manifest_tamper_rejected(self):
        ledger = m.ReferenceLedger(self.rows, POLICY); observation = ledger.observe()
        receipts = self.preserve(ledger, observation, (entry(5001),)); receipt = receipts[self.rows[0].identity]
        self.archive._path("manifests", receipt.manifest_sha256).write_bytes(b"{}")
        with self.assertRaisesRegex(m.RetentionBlocked, "ARCHIVE_MANIFEST_DIGEST_MISMATCH"):
            self.append(ledger, observation=observation, receipts=receipts)

    def test_another_entry_archive_does_not_authorize_eviction(self):
        ledger = m.ReferenceLedger(self.rows, POLICY)
        receipt = self.archive.preserve(self.rows[1], POLICY, AT)
        with self.assertRaisesRegex(m.RetentionBlocked, "ARCHIVE_ENTRY_BINDING_MISMATCH"):
            self.append(ledger, receipts={self.rows[0].identity: receipt})

    def test_linked_snapshot_bytes_are_required_and_independently_verified(self):
        linked = m.LinkedBytes("phs_static", b'{"snapshot_id":"phs_static","value":1}')
        first = entry(0, metadata={"snapshot_id": "phs_static"}, links=(linked,))
        ledger = m.ReferenceLedger((first, *self.rows[1:]), POLICY); observation = ledger.observe()
        receipts = self.preserve(ledger, observation, (entry(5001),))
        self.archive._path("blobs", m.digest(linked.raw)).write_bytes(b"changed")
        with self.assertRaisesRegex(m.RetentionBlocked, "ARCHIVE_RAW_DIGEST_MISMATCH"):
            self.append(ledger, observation=observation, receipts=receipts)

    def test_missing_or_wrong_linked_custody_fails(self):
        with self.assertRaisesRegex(m.RetentionBlocked, "LINKED_CUSTODY_MISSING"):
            entry(0, metadata={"snapshot_id": "phs_static"}).custody()
        with self.assertRaisesRegex(m.RetentionBlocked, "LINKED_REFERENCE_MISMATCH"):
            entry(0, metadata={"snapshot_id": "phs_static"}, links=(m.LinkedBytes("phs_static", b'{"snapshot_id":"wrong"}'),)).custody()

    def test_retry_returns_existing_commit_zero_second_write(self):
        ledger = m.ReferenceLedger(self.rows[:-1], POLICY); observation = ledger.observe()
        first = self.append(ledger, observation=observation); after = ledger.rows
        self.assertEqual(self.append(ledger, observation=observation), first)
        self.assertEqual(ledger.rows, after); self.assertEqual(ledger.version, 1)

    def test_retry_changed_payload_is_rejected(self):
        ledger = m.ReferenceLedger(self.rows[:-1], POLICY); observation = ledger.observe(); self.append(ledger)
        with self.assertRaisesRegex(m.RetentionBlocked, "IDEMPOTENCY_PAYLOAD_CONFLICT"):
            self.append(ledger, (entry(5002),), observation=observation)

    def test_missing_policy_or_unknown_category_fails_before_write(self):
        ledger = m.ReferenceLedger(self.rows[:-1], m.Policy("NOT_GRANTED"))
        with self.assertRaisesRegex(m.RetentionBlocked, "OWNER_POLICY_REQUIRED"): self.append(ledger)
        ledger = m.ReferenceLedger(self.rows[:-1], POLICY)
        with self.assertRaisesRegex(m.RetentionBlocked, "UNKNOWN_CATEGORY"): self.append(ledger, (entry(5001, kind="unknown"),))

    def test_unknown_oldest_and_wrong_ledger_fails(self):
        ledger = m.ReferenceLedger((entry(0, kind="unknown"), *self.rows[1:]), POLICY)
        with self.assertRaisesRegex(m.RetentionBlocked, "UNKNOWN_CATEGORY"): self.append(ledger)
        ledger = m.ReferenceLedger(self.rows[:-1], POLICY)
        with self.assertRaisesRegex(m.RetentionBlocked, "LEDGER_SCOPE_MISMATCH"):
            self.append(ledger, (entry(5001, ledger="another-ledger"),))

    def test_missing_timezone_duplicate_json_and_bad_encoding_rejected(self):
        for raw in (b'{"event_id":"x","event_type":"x","created_at":"2026-09-14T00:00:00"}',
                    b'{"event_id":"x","event_id":"y"}', b"\xff"):
            with self.assertRaises((ValueError, UnicodeError)): m.Entry(LEDGER, raw).custody()

    def test_same_raw_archive_can_be_preserved_without_overwrite(self):
        first = self.archive.preserve(self.rows[0], POLICY, AT)
        self.assertEqual(self.archive.preserve(self.rows[0], POLICY, AT), first)
        self.assertEqual(self.archive._path("blobs", m.digest(self.rows[0].raw)).read_bytes(), self.rows[0].raw)

    def test_original_raw_CRLF_whitespace_and_unicode_are_not_reserialized(self):
        first = entry(0, metadata={"static_marker": "Nội bộ"})
        receipt = self.archive.preserve(first, POLICY, AT); self.archive.verify(first, POLICY, receipt)
        self.assertEqual(self.archive._path("blobs", m.digest(first.raw)).read_bytes(), first.raw)

    def test_out_of_band_ledger_change_is_detected_by_raw_digest(self):
        ledger = m.ReferenceLedger(self.rows[:-1], POLICY); observation = ledger.observe()
        ledger.rows = (entry(0, metadata={"changed": True}), *ledger.rows[1:])
        with self.assertRaisesRegex(m.RetentionBlocked, "LEDGER_OR_POLICY_CHANGED_STOP_NO_RETRY"):
            self.append(ledger, observation=observation)

    def test_policy_change_after_archive_is_rejected(self):
        ledger = m.ReferenceLedger(self.rows, POLICY); observation = ledger.observe()
        receipts = self.preserve(ledger, observation, (entry(5001),))
        ledger.policy = m.Policy("SYNTHETIC_DIFFERENT_POLICY", POLICY.classes, True)
        with self.assertRaisesRegex(m.RetentionBlocked, "LEDGER_OR_POLICY_CHANGED_STOP_NO_RETRY"):
            self.append(ledger, observation=observation, receipts=receipts)


if __name__ == "__main__": unittest.main()
