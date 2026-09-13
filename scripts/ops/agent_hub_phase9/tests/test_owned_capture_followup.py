"""Full owned followup proofs in temporary synthetic packages; no remote calls."""
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import capture_hash_contract as hashes
import gate_bindings as gate
import operation_identity as identity
import pilot_runner as runner
import pilot_dispatcher as dispatcher
import remote_preflight_capture as capture
from test_gate_bindings import HEAD, NOW, fixture, write
import test_execution_window as window_tests
import test_pilot_runner as runner_tests

class OwnedFollowupTests(unittest.TestCase):
    proof = window_tests.WindowTests.proof
    approval = runner_tests.RunnerTests.approval

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'package'; self.root.mkdir()
        self.baseline, self.anchor = fixture(self.root, family='RCA06',
            agent_counter_values={'tool_execution_total': 181, 'execution_audit_count': 362})
        self.verified = gate.verify_package(self.root, self.anchor, HEAD, self.baseline, current=NOW)

    def verify(self, authority):
        return runner.verify_followup_package(self.root, self.anchor, HEAD, self.baseline,
            authority, current=NOW + timedelta(seconds=3600))

    def receipt(self, authority):
        proof = gate.load(authority / 'INITIAL_DISPATCH_CAPTURE.json')
        return authority / 'captures' / proof['capture_name']

    def rebind_receipt(self, authority, value):
        path = self.receipt(authority); write(path, value)
        proof = gate.load(authority / 'INITIAL_DISPATCH_CAPTURE.json'); proof['sha256'] = gate.sha(path)
        write(authority / 'INITIAL_DISPATCH_CAPTURE.json', proof)

    def test_exact_1953_pretty_production_shape_new_full_followup_passes_old_flat_hash_fails(self):
        historical = hashes.parse_payload((Path(__file__).parent / 'fixtures/owned_preflight_1953.stdout.bin').read_bytes())
        def formatter(primary):
            current = {**historical, **primary}
            raw = json.dumps(current, indent=2, sort_keys=True).encode() + b'\n'
            self.assertEqual(len(raw), 1953)
            self.assertEqual(len(json.dumps(current, sort_keys=True).encode() + b'\n'), 1805)
            return raw
        authority = self.proof(formatter=formatter)
        captured = gate.load(self.receipt(authority))
        primary = gate.load(authority / 'FINAL_READONLY_PREFLIGHT.json')
        old = json.dumps(primary, sort_keys=True).encode() + b'\n'
        self.assertNotEqual(hashlib.sha256(old).hexdigest(), captured['stdout']['sha256'])
        self.verify(authority)

    def test_crlf_unicode_escaping_and_no_final_newline_full_followup_pass(self):
        authority = self.proof(formatter=lambda value: json.dumps(value, indent=2, ensure_ascii=False).encode().replace(b'\n', b'\r\n'),
            primary_updates={'note': 'Tiếng Việt; café e\u0301; "quote" \\ slash\nline'})
        self.verify(authority)

    def test_actual_producer_runner_observe_and_owned_consumer_share_raw_custody(self):
        historical = hashes.parse_payload((Path(__file__).parent / 'fixtures/owned_preflight_1953.stdout.bin').read_bytes())
        authority = self.proof(formatter=lambda primary:
            json.dumps({**historical, **primary}, indent=2, sort_keys=True).encode() + b'\n')
        synthetic_receipt = gate.load(self.receipt(authority))
        raw = (authority / 'captures' / synthetic_receipt['raw_stdout_file']).read_bytes()
        self.assertEqual(len(raw), 1953)
        for path in (authority / 'captures').iterdir(): path.unlink()
        profile = gate.load(self.root / 'RUNTIME_PROFILE.json')
        envelope = gate.load(authority / 'DISPATCH_CLAIM.json')
        def dispatch(*args, **kwargs):
            self.assertIs(kwargs['retain_raw_stdout'], True)
            return dispatcher.dispatch_preflight(*args, **kwargs,
                current=NOW + timedelta(seconds=40))
        def invoker(argv, *, input_bytes, timeout):
            self.assertEqual(input_bytes, (self.root / 'remote_runtime.py').read_bytes())
            self.assertEqual(timeout, 240)
            return subprocess.CompletedProcess(argv, 0, raw, b'')
        with patch.object(runner, 'strict_argv', return_value=['fixture-binary-transport']), \
             patch.object(runner, 'dispatch_preflight', side_effect=dispatch), \
             patch.object(capture, 'datetime') as clock:
            clock.now.side_effect = [NOW + timedelta(seconds=10), NOW + timedelta(seconds=40)]
            primary, path = runner.observe(self.root, self.verified, profile, self.anchor,
                envelope, authority / 'captures', invoker)
        receipt = gate.load(path)
        self.assertEqual((path.parent / receipt['raw_stdout_file']).read_bytes(), raw)
        hashes.verify_stdout(raw, primary, receipt)
        digests = {name: receipt[name] for name in
            ('hash_contract', 'raw_stdout_sha256', 'canonical_payload_sha256')}
        write(authority / 'DISPATCH_CLAIM.json', {**envelope, **digests})
        write(authority / 'INITIAL_DISPATCH_CAPTURE.json',
            {'capture_name': path.name, 'sha256': gate.sha(path), **digests})
        self.verify(authority)

    def test_one_raw_byte_changed_or_truncated_fail(self):
        authority = self.proof(); receipt = gate.load(self.receipt(authority))
        raw_path = authority / 'captures' / receipt['raw_stdout_file']; original = raw_path.read_bytes()
        for changed in (original.replace(b'PASS', b'FAIL'), original[:-1], b'\xff' + original):
            raw_path.write_bytes(changed)
            with self.assertRaisesRegex(gate.GateStop, 'CAPTURE_INVALID'): self.verify(authority)
        raw_path.write_bytes(original)

    def test_missing_raw_file_rejected(self):
        authority = self.proof(); receipt = gate.load(self.receipt(authority))
        (authority / 'captures' / receipt['raw_stdout_file']).unlink()
        with self.assertRaisesRegex(gate.GateStop, 'RAW_STDOUT_MISSING'): self.verify(authority)

    def test_modified_semantic_object_cannot_be_silently_substituted(self):
        authority = self.proof(); primary = gate.load(authority / 'FINAL_READONLY_PREFLIGHT.json')
        primary['note'] = 'modified'
        write(authority / 'FINAL_READONLY_PREFLIGHT.json', primary)
        with self.assertRaisesRegex(gate.GateStop, 'CAPTURE_INVALID'): self.verify(authority)

    def test_old_v1_receipt_rejected_even_when_outer_proof_rehashed(self):
        authority = self.proof(); value = gate.load(self.receipt(authority)); value['schema'] = 'npd.agent-hub.phase9.remote-preflight-capture.v1'
        self.rebind_receipt(authority, value)
        with self.assertRaisesRegex(gate.GateStop, 'HASH_CONTRACT_INVALID'): self.verify(authority)

    def test_digest_domain_swap_type_and_binding_modifications_rejected(self):
        authority = self.proof(); original = gate.load(self.receipt(authority))
        for change in ({'raw_stdout_sha256': original['canonical_payload_sha256']},
            {'canonical_payload_sha256': original['raw_stdout_sha256']}, {'raw_stdout_sha256': 1},
            {'hash_contract': 'canonical-only'}, {'binding_id': 'OTHER-OPERATION'}, {'raw_transport_bytes': False}):
            self.rebind_receipt(authority, {**original, **change})
            with self.assertRaises(gate.GateStop): self.verify(authority)

    def test_bound_raw_or_semantic_digest_modified_after_claim_rejected(self):
        authority = self.proof(); original = gate.load(authority / 'DISPATCH_CLAIM.json')
        for name in ('raw_stdout_sha256', 'canonical_payload_sha256', 'hash_contract'):
            write(authority / 'DISPATCH_CLAIM.json', {**original, name: 'wrong'})
            with self.assertRaisesRegex(gate.GateStop, 'DIGEST_BINDING_MISMATCH'): self.verify(authority)

    def test_stale_checked_at_and_initial_capture_rejected(self):
        authority = self.proof(primary_updates={'checked_at': (NOW - timedelta(seconds=601)).isoformat()})
        with self.assertRaisesRegex(gate.GateStop, 'STALE'): self.verify(authority)

    def test_nonempty_stderr_rejected_even_with_updated_raw_digest(self):
        authority = self.proof(); value = gate.load(self.receipt(authority))
        value['stderr'] = {'length_bytes': 7, 'sha256': hashes.raw_digest(b'warning')}
        value['raw_stderr_sha256'] = value['stderr']['sha256']; self.rebind_receipt(authority, value)
        with self.assertRaisesRegex(gate.GateStop, 'CAPTURE_INVALID'): self.verify(authority)

    def test_another_package_or_operation_proof_rejected(self):
        authority = self.proof(); previous = gate.load(authority / 'DISPATCH_CLAIM.json')
        for name in ('operation_id', 'package_manifest_sha256', 'snapshot_sha256'):
            write(authority / 'DISPATCH_CLAIM.json', {**previous, name: 'wrong-package-or-operation'})
            with self.assertRaises(gate.GateStop): self.verify(authority)

    def test_raw_path_traversal_and_wrong_uuid_rejected(self):
        authority = self.proof(); original = gate.load(self.receipt(authority))
        for change in ({'raw_stdout_file': '../outside.bin'}, {'invocation_id': 'bad-uuid'}):
            self.rebind_receipt(authority, {**original, **change})
            with self.assertRaises(gate.GateStop): self.verify(authority)

    def test_recovered_and_aborted_operation_ids_cannot_start_fresh_execution(self):
        for old in (identity.CONSUMED_ABORTED_OPERATION, identity.RECOVERED_TERMINAL_OPERATION):
            with self.assertRaisesRegex(identity.OperationIdentityError, 'RETIRED_NOT_REUSABLE'):
                identity.validate_fresh_operation_id(old)

if __name__ == '__main__': unittest.main()
