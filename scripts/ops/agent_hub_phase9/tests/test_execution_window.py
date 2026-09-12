"""Synthetic timed-transaction proofs only; no remote actions or owner authority."""
import base64
from datetime import timedelta
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_bindings as gate
import pilot_dispatcher as dispatcher
import pilot_runner as runner
from test_gate_bindings import HEAD, NOW, write
import test_pilot_runner as runner_tests
TEMPLATE = runner_tests.TEMPLATE

class WindowTests(unittest.TestCase):
    setUp = runner_tests.RunnerTests.setUp
    approval = runner_tests.RunnerTests.approval

    def test_ordered_but_different_approval_window_denied(self):
        approval = self.approval()
        approval['window'] = {name: (gate.utc_time(value) + timedelta(seconds=1)).isoformat()
                              for name, value in approval['window'].items()}
        with self.assertRaisesRegex(gate.GateStop, 'WINDOW_MISMATCH'):
            dispatcher.verify_execution_approval(approval, self.verified, self.anchor, current=NOW)

    def test_wrong_window_hash_denied(self):
        approval = self.approval(); approval['execution_window_sha256'] = '0' * 64
        with self.assertRaisesRegex(gate.GateStop, 'WINDOW_MISMATCH'):
            dispatcher.verify_execution_approval(approval, self.verified, self.anchor, current=NOW)

    def test_dispatch_deadline_is_earlier_than_mutation_deadline(self):
        dispatcher.verify_execution_approval(self.approval(), self.verified, self.anchor,
            current=NOW + timedelta(seconds=301), phase='mutation')
        with self.assertRaises(gate.GateStop):
            dispatcher.verify_execution_approval(self.approval(), self.verified, self.anchor,
                current=NOW + timedelta(seconds=301), phase='dispatch')

    def test_window_budget_and_counter_deadline_cannot_be_shortened_or_extended(self):
        counter = gate.load(self.root / 'evidence/COUNTER_EVIDENCE.json')
        for name, value in [('initial_dispatch_deadline_utc', (NOW + timedelta(seconds=601)).isoformat()),
            ('latest_dispatcher_start_utc', (NOW + timedelta(seconds=361)).isoformat()),
            ('latest_mutation_utc', (NOW + timedelta(seconds=1199)).isoformat()),
            ('decision_deadline_utc', (NOW + timedelta(seconds=4499)).isoformat()),
            ('end_ict', 'wrong')]:
            window = {**self.verified['window'], name: value}
            with self.subTest(name=name), self.assertRaises(gate.GateStop):
                gate.verify_window(window, counter, self.verified['manifest']['operation_id'], HEAD)

    def proof(self):
        authority = self.root.parent / 'synthetic-authority'
        profile = gate.load(self.root / 'RUNTIME_PROFILE.json')
        profile.update({'_package': str(self.root), 'owner_exception_receipt_sha256': '0' * 64,
            'fresh_backup_manifest_sha256': '0' * 64, 'rollback_bundle_manifest_sha256': '0' * 64,
            'source_main_sha': HEAD, '_approval_file_sha256': '0' * 64})
        approval = self.approval(); approval['owner_authorization_receipt_sha256'] = '0' * 64
        envelope = runner.envelope_for(self.verified, profile, self.anchor, str(uuid4()), approval)
        primary = {'status': 'PASS', 'operation_id': profile['operation_id'], 'package_manifest_sha256': self.anchor,
            'candidate_head': HEAD, 'snapshot_sha256': self.verified['manifest']['snapshot_sha256'],
            'protected_services_sha256': self.baseline, 'counter_evidence_sha256': profile['counter_evidence_sha256'],
            'safety_counters': self.verified['snapshot']['safety_counters']}
        write(authority / 'FINAL_READONLY_PREFLIGHT.json', primary)
        envelope.update({'final_readonly_preflight_status': 'PASS',
            'final_readonly_preflight_sha256': gate.sha(authority / 'FINAL_READONLY_PREFLIGHT.json')})
        write(authority / 'DISPATCH_CLAIM.json', envelope)
        write(authority / 'REMOTE_CLAIM.json', {'status': 'CLAIMED', 'operation_id': profile['operation_id'],
            'claim_id': envelope['invocation_id'], 'claimed_at': (NOW + timedelta(seconds=50)).isoformat()})
        raw = json.dumps(primary, sort_keys=True).encode() + b'\n'
        capture = {'binding_id': profile['operation_id'], 'invocation_id': str(uuid4()),
            'child_returncode': 0, 'timed_out': False, 'stderr': {'length_bytes': 0},
            'stdout': {'length_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()},
            'stdin': {'sha256': self.verified['bindings']['dependency_hashes']['remote_runtime.py']},
            'started_at_utc': (NOW + timedelta(seconds=10)).isoformat(),
            'completed_at_utc': (NOW + timedelta(seconds=40)).isoformat()}
        write(authority / 'captures/capture-synthetic.json', capture)
        write(authority / 'INITIAL_DISPATCH_CAPTURE.json', {'capture_name': 'capture-synthetic.json',
            'sha256': gate.sha(authority / 'captures/capture-synthetic.json')})
        return authority

    def test_stale_receipt_never_starts_new_dispatch_but_owned_recovery_remains_verifiable(self):
        authority = self.proof(); current = NOW + timedelta(seconds=3600)
        with self.assertRaisesRegex(gate.GateStop, 'STALE'):
            gate.verify_package(self.root, self.anchor, HEAD, self.baseline, current=current)
        verified = runner.verify_followup_package(self.root, self.anchor, HEAD, self.baseline, authority, current=current)
        dispatcher.verify_execution_approval(self.approval(), verified, self.anchor, current=current, phase='recovery')
        with self.assertRaises(gate.GateStop):
            dispatcher.verify_execution_approval(self.approval(), verified, self.anchor,
                current=NOW + timedelta(seconds=7200), phase='recovery')

    def test_missing_or_changed_owned_proof_denies(self):
        authority = self.proof()
        for filename in ('DISPATCH_CLAIM.json', 'REMOTE_CLAIM.json', 'FINAL_READONLY_PREFLIGHT.json',
                         'INITIAL_DISPATCH_CAPTURE.json'):
            path = authority / filename; raw = path.read_bytes(); path.unlink()
            with self.subTest(filename=filename), self.assertRaises(gate.GateStop):
                runner.verify_followup_package(self.root, self.anchor, HEAD, self.baseline, authority, current=NOW+timedelta(seconds=3600))
            path.write_bytes(raw)
        previous = gate.load(authority / 'DISPATCH_CLAIM.json'); previous['runner_sha256'] = '0'*64
        write(authority / 'DISPATCH_CLAIM.json', previous)
        with self.assertRaisesRegex(gate.GateStop, 'DEPENDENCY'):
            runner.verify_followup_package(self.root, self.anchor, HEAD, self.baseline, authority, current=NOW+timedelta(seconds=3600))

    def test_late_initial_claim_cannot_be_used_as_recovery_proof(self):
        authority = self.proof(); claimed = gate.load(authority / 'REMOTE_CLAIM.json')
        claimed['claimed_at'] = (NOW+timedelta(seconds=601)).isoformat(); write(authority/'REMOTE_CLAIM.json', claimed)
        with self.assertRaisesRegex(gate.GateStop, 'STALE'):
            runner.verify_followup_package(self.root,self.anchor,HEAD,self.baseline,authority,current=NOW+timedelta(seconds=3600))

    def test_remote_initial_claim_expiry_denies_before_baseline_or_write(self):
        spec=importlib.util.spec_from_file_location('synthetic_window_runtime',TEMPLATE)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with patch.multiple(module, NOT_BEFORE=NOW, LATEST_MUTATION=NOW+timedelta(seconds=1200),
            INITIAL_DISPATCH_DEADLINE=(NOW+timedelta(seconds=600)).isoformat()), \
            patch.object(module,'utc_now',return_value=NOW+timedelta(seconds=601)), \
            patch.object(module,'verify_baseline',side_effect=AssertionError('observation reached')):
            with self.assertRaisesRegex(module.GateStop,'EXPIRED'): module.claim({})

    def test_remote_approval_window_must_equal_rendered_package_window(self):
        authority=self.proof();envelope=gate.load(authority/'DISPATCH_CLAIM.json')
        spec=importlib.util.spec_from_file_location('synthetic_remote_window_parser',TEMPLATE)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        mapping={'OPERATION':'operation_id','TOKEN_SHA':'confirmation_token_sha256',
            'FRESH_BACKUP_MANIFEST_SHA':'fresh_backup_manifest_sha256','ROLLBACK_BUNDLE_MANIFEST_SHA':'rollback_bundle_manifest_sha256',
            'MAIN_SHA':'main_sha','CANDIDATE_HEAD':'candidate_head','SNAPSHOT_SHA':'snapshot_sha256',
            'COUNTER_EVIDENCE_SHA':'counter_evidence_sha256','BASELINE_PROTECTED_SHA':'protected_services_sha256',
            'OWNER_EXCEPTION_SHA':'owner_exception_receipt_sha256','EXECUTION_WINDOW_SHA':'execution_window_sha256'}
        with patch.multiple(module,**{key:envelope[field] for key,field in mapping.items()},
            BOUND_WINDOW_JSON=json.dumps(envelope['window'],sort_keys=True,separators=(',',':'))), \
            patch.object(module,'run',side_effect=AssertionError('remote action reached')):
            module.parse_envelope(runner.encode(envelope))
            envelope['window']['start_utc']=(NOW+timedelta(seconds=1)).isoformat()
            with self.assertRaisesRegex(module.GateStop,'PACKAGE_MISMATCH'): module.parse_envelope(runner.encode(envelope))

if __name__ == '__main__': unittest.main()
