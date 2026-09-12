"""Synthetic package fixtures. They are never runtime observations or approvals."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_bindings as gate
import pilot_dispatcher as dispatcher
from remote_preflight_capture import CaptureStop

HEAD = '1' * 40
NOW = datetime(2026, 9, 12, 12, tzinfo=timezone.utc)

def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')

def fixture(root):
    """Build evidence in a temporary directory using explicitly synthetic values."""
    evidence = root / 'evidence'
    signatures = {f'synthetic-service-{i}': f'signature-{i}' for i in range(18)}
    baseline = gate.canonical_digest(signatures)
    specs = {'lua_sha256': '2' * 64, 'command': 'EVAL_RO', 'fixture_only': True}
    exception = {'status': 'OWNER_ACCEPTED_EVIDENCE_ONLY_EXCEPTION',
        'exact_counter_identifiers': list(gate.COUNTERS), 'counter_ids_extracted_from_existing_contract': True,
        'execution_approval': 'NOT_GRANTED', 'video_factory_workstream_opened': False}
    write(evidence / 'COUNTER_QUERY_SPEC.json', specs)
    write(evidence / 'OWNER_EVIDENCE_EXCEPTION.json', exception)
    counter = {'status': 'PASS', 'candidate_head': HEAD, 'protected_canonical_sha256': baseline,
        'source_agent_hub_container_id': 'synthetic-container', 'owner_exception_receipt_sha256': gate.sha(evidence / 'OWNER_EVIDENCE_EXCEPTION.json'),
        'query_spec_sha256': gate.sha(evidence / 'COUNTER_QUERY_SPEC.json'), 'query_lua_sha256': specs['lua_sha256'],
        'sanitized_command_fingerprint': gate.canonical_digest(specs), 'server_enforced_readonly': True,
        'query_command': 'EVAL_RO', 'redis_reference': {'db': 0}, 'production_mutation': False,
        'video_factory_writes': 0, 'raw_keys_values_credentials_or_job_payloads_emitted': False,
        'counters': dict(zip(gate.COUNTERS, (12, 0, 0, 0))), 'observed_at_utc': NOW.isoformat(),
        'operation_id': 'SYNTHETIC-COUNTER-' + str(uuid4())}
    write(evidence / 'COUNTER_EVIDENCE.json', counter)
    raw = json.dumps(counter, sort_keys=True).encode() + b'\n'
    transport = {'child_returncode': 0, 'stderr': {'length_bytes': 0}, 'timed_out': False,
        'binding_id': counter['operation_id'], 'invocation_id': str(uuid4()),
        'stdout': {'sha256': hashlib.sha256(raw).hexdigest(), 'length_bytes': len(raw)}}
    write(evidence / 'COUNTER_TRANSPORT.json', transport)
    write(evidence / 'PROTECTED_BASELINE.json', {'protected_sha256': baseline, 'protected_count': 18,
        'protected_signatures': signatures, 'candidate_head': HEAD, 'claim_absent': True,
        'production_mutation': False, 'target': {'id': 'synthetic-container'}})
    backup = {'status': 'PASS', 'source_validation': {'key_count': 10692}}
    write(evidence / 'BACKUP_MANIFEST.json', backup)
    write(evidence / 'RESTORE_VALIDATION.json', {'status': 'PASS', 'fresh_backup_manifest_sha256': gate.sha(evidence / 'BACKUP_MANIFEST.json'),
        'redis_values_types_and_ttls_verified': 10692})
    write(evidence / 'BACKUP_RESTORE.json', {'status': 'PASS', 'backup_manifest_sha256': gate.sha(evidence / 'BACKUP_MANIFEST.json'),
        'restore_sha256': gate.sha(evidence / 'RESTORE_VALIDATION.json')})
    safety = {name: 0 for name in gate.AGENT_COUNTERS}
    safety.update({'role_assignments': {r: {'matches_expected': True} for r in ('owner', 'operator', 'viewer')},
        'configuration_valid': True, 'external_executor_configured': False, 'namespace_key_count': 10692})
    write(evidence / 'ROLE_COUNTER_BINDINGS.json', {'candidate_head': HEAD, 'role_config_and_redis_safety': safety,
        'role_whoami': {r: {'role_match': True} for r in ('owner', 'operator', 'viewer')}})
    files = dict(zip(('baseline', 'counter_receipt', 'counter_transport', 'exception_receipt', 'query_spec', 'roles', 'backup', 'restore', 'backup_restore'),
        ('PROTECTED_BASELINE.json', 'COUNTER_EVIDENCE.json', 'COUNTER_TRANSPORT.json', 'OWNER_EVIDENCE_EXCEPTION.json', 'COUNTER_QUERY_SPEC.json',
         'ROLE_COUNTER_BINDINGS.json', 'BACKUP_MANIFEST.json', 'RESTORE_VALIDATION.json', 'BACKUP_RESTORE.json')))
    snapshot = {'status': 'PASS', 'full_execution_snapshot_complete': True, 'candidate_head': HEAD,
        'protected_canonical_sha256': baseline, 'agent_hub_counter_names': list(gate.AGENT_COUNTERS),
        'safety_counters': {**{name: safety[name] for name in gate.AGENT_COUNTERS}, **counter['counters']},
        'dependencies': {name: {'path': f, 'sha256': gate.sha(evidence / f)} for name, f in files.items()}}
    write(evidence / 'FULL_EXECUTION_SNAPSHOT.json', snapshot)
    operation = 'PHASE9-LIMITED-PILOT-RCA05-' + str(uuid4())
    for name in gate.REQUIRED_PILOT_FILES - {'ARTIFACT_MANIFEST.json', 'PILOT_PAYLOAD.json'}:
        if not (root / name).exists():
            write(root / name, {'fixture_only': True})
    payload = {'operation_id': operation, 'candidate_head': HEAD, 'snapshot_sha256': gate.sha(evidence / 'FULL_EXECUTION_SNAPSHOT.json'),
        'counter_evidence_sha256': gate.sha(evidence / 'COUNTER_EVIDENCE.json'),
        'execution_scope_sha256': gate.sha(root / 'EXECUTION_SCOPE.json')}
    write(root / 'PILOT_PAYLOAD.json', payload)
    identity = {**payload, 'protected_services_sha256': baseline, 'confirmation_token_sha256': '8' * 64}
    write(root / 'CONFIRMATION_CONTRACT.json', {**identity, 'private_dpapi_blob_sha256': '9' * 64})
    write(root / 'RUNTIME_PROFILE.json', {**identity, 'candidate_archive_sha256': gate.sha(root / 'candidate.oci.tar'),
        'candidate_archive_size': (root / 'candidate.oci.tar').stat().st_size})
    dependencies = {name: gate.sha(root / name) for name in gate.REQUIRED_PILOT_FILES - {'ARTIFACT_MANIFEST.json'}}
    write(root / 'ARTIFACT_MANIFEST.json', {'artifact_hashes': dependencies})
    dependencies['ARTIFACT_MANIFEST.json'] = gate.sha(root / 'ARTIFACT_MANIFEST.json')
    write(root / 'OPERATION_BINDINGS.json', {'operation_id': operation, 'candidate_head': HEAD,
        'snapshot_sha256': payload['snapshot_sha256'], 'dependency_hashes': dependencies})
    manifest = {'operation_id': operation, 'candidate_head': HEAD, 'snapshot_sha256': payload['snapshot_sha256'],
        'status': 'PREPARED_FOR_OWNER_REVIEW', 'execution_approval': 'NOT_GRANTED'}
    reseal_outer(root, manifest)
    return baseline, gate.sha(root / 'PACKAGE_MANIFEST.json')

def reseal_outer(root, manifest=None):
    manifest = manifest or gate.load(root / 'PACKAGE_MANIFEST.json')
    manifest['artifacts'] = [{'path': p.relative_to(root).as_posix(), 'length_bytes': p.stat().st_size, 'sha256': gate.sha(p)}
        for p in sorted(root.rglob('*')) if p.is_file() and p.name != 'PACKAGE_MANIFEST.json']
    write(root / 'PACKAGE_MANIFEST.json', manifest)

class BindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'package'; self.root.mkdir()
        self.baseline, self.anchor = fixture(self.root)

    def verify(self, **options):
        return gate.verify_package(self.root, options.pop('manifest', self.anchor), options.pop('head', HEAD),
            options.pop('baseline', self.baseline), current=options.pop('current', NOW), **options)

    def edit(self, name, **updates):
        value = gate.load(self.root / name); value.update(updates); write(self.root / name, value)

    def snapshot_edit(self, name, **updates):
        self.edit('evidence/' + name, **updates)
        snapshot = gate.load(self.root / 'evidence/FULL_EXECUTION_SNAPSHOT.json')
        for entry in snapshot['dependencies'].values(): entry['sha256'] = gate.sha(self.root / 'evidence' / entry['path'])
        write(self.root / 'evidence/FULL_EXECUTION_SNAPSHOT.json', snapshot)

    def test_complete_synthetic_package_passes(self): self.verify()
    def test_missing_evidence_denies(self):
        (self.root / 'evidence/COUNTER_EVIDENCE.json').unlink()
        with self.assertRaises((gate.GateStop, FileNotFoundError)): self.verify()
    def test_modified_evidence_denies(self):
        self.edit('evidence/COUNTER_EVIDENCE.json', counters={})
        with self.assertRaises(gate.GateStop): self.verify()
    def test_extra_file_denies(self):
        write(self.root / 'extra.json', {})
        with self.assertRaisesRegex(gate.GateStop, 'INVENTORY'): self.verify()
    def test_manifest_mismatch_denies(self):
        self.edit('PACKAGE_MANIFEST.json', operation_id='OLD')
        with self.assertRaisesRegex(gate.GateStop, 'MANIFEST_MISMATCH'): self.verify()
    def test_wrong_head_denies(self):
        with self.assertRaisesRegex(gate.GateStop, 'HEAD_MISMATCH'): self.verify(head='3' * 40)
    def test_wrong_baseline_denies(self):
        with self.assertRaisesRegex(gate.GateStop, 'BASELINE_MISMATCH'): self.verify(baseline='4' * 64)
    def test_wrong_snapshot_binding_denies_even_rehashed_manifest(self):
        self.edit('PACKAGE_MANIFEST.json', snapshot_sha256='5' * 64)
        with self.assertRaisesRegex(gate.GateStop, 'SNAPSHOT_MISMATCH'): self.verify(manifest=gate.sha(self.root / 'PACKAGE_MANIFEST.json'))
    def test_stale_and_future_counter_denies(self):
        for shift in (601, -6):
            with self.subTest(shift=shift), self.assertRaisesRegex(gate.GateStop, 'STALE_OR_FUTURE'):
                self.verify(current=NOW + timedelta(seconds=shift))
    def test_wrong_operation_identity_denies(self):
        self.edit('OPERATION_BINDINGS.json', operation_id='ABORTED-HISTORICAL-OPERATION')
        reseal_outer(self.root)
        with self.assertRaisesRegex(gate.GateStop, 'OPERATION_BINDING'): self.verify(manifest=gate.sha(self.root / 'PACKAGE_MANIFEST.json'))
    def test_wrong_dependency_hash_denies(self):
        value = gate.load(self.root / 'OPERATION_BINDINGS.json'); value['dependency_hashes']['runner.py'] = '6' * 64
        write(self.root / 'OPERATION_BINDINGS.json', value); reseal_outer(self.root)
        with self.assertRaisesRegex(gate.GateStop, 'DEPENDENCY_MISMATCH'): self.verify(manifest=gate.sha(self.root / 'PACKAGE_MANIFEST.json'))
    def test_missing_required_runner_denies_even_resealed_outer(self):
        value = gate.load(self.root / 'OPERATION_BINDINGS.json'); del value['dependency_hashes']['runner.py']
        write(self.root / 'OPERATION_BINDINGS.json', value); reseal_outer(self.root)
        with self.assertRaisesRegex(gate.GateStop, 'SET_INCOMPLETE'): self.verify(manifest=gate.sha(self.root / 'PACKAGE_MANIFEST.json'))
    def test_boolean_counter_denies(self):
        counter = gate.load(self.root / 'evidence/COUNTER_EVIDENCE.json'); counter['counters'][gate.COUNTERS[1]] = False
        self.snapshot_edit('COUNTER_EVIDENCE.json', **counter)
        with self.assertRaisesRegex(gate.GateStop, 'VALUE_INVALID'): gate.verify_snapshot(self.root / 'evidence', HEAD, self.baseline, current=NOW)
    def test_nonidle_counter_denies(self):
        counter = gate.load(self.root / 'evidence/COUNTER_EVIDENCE.json'); counter['counters'][gate.COUNTERS[1]] = 1
        self.snapshot_edit('COUNTER_EVIDENCE.json', **counter)
        with self.assertRaisesRegex(gate.GateStop, 'NOT_IDLE'): gate.verify_snapshot(self.root / 'evidence', HEAD, self.baseline, current=NOW)
    def test_non_readonly_eval_fallback_denies(self):
        self.snapshot_edit('COUNTER_EVIDENCE.json', query_command='EVAL')
        with self.assertRaisesRegex(gate.GateStop, 'NOT_SERVER_READONLY'): gate.verify_snapshot(self.root / 'evidence', HEAD, self.baseline, current=NOW)
    def test_counter_capture_primary_hash_denies(self):
        self.snapshot_edit('COUNTER_TRANSPORT.json', stdout={'sha256': '7' * 64, 'length_bytes': 1})
        with self.assertRaisesRegex(gate.GateStop, 'PRIMARY_CAPTURE'): gate.verify_snapshot(self.root / 'evidence', HEAD, self.baseline, current=NOW)
    def test_counter_nonzero_returncode_denies(self):
        self.snapshot_edit('COUNTER_TRANSPORT.json', child_returncode=2)
        with self.assertRaisesRegex(gate.GateStop, 'TRANSPORT_INVALID'): gate.verify_snapshot(self.root / 'evidence', HEAD, self.baseline, current=NOW)
    def test_non_utc_timestamp_denies(self):
        self.snapshot_edit('COUNTER_EVIDENCE.json', observed_at_utc='2026-09-12T19:00:00+07:00')
        with self.assertRaisesRegex(gate.GateStop, 'NOT_UTC'): gate.verify_snapshot(self.root / 'evidence', HEAD, self.baseline, current=NOW)
    def test_four_counter_exception_cannot_be_expanded(self):
        self.snapshot_edit('OWNER_EVIDENCE_EXCEPTION.json', exact_counter_identifiers=[*gate.COUNTERS, 'extra'])
        with self.assertRaisesRegex(gate.GateStop, 'EXCEPTION_SCOPE'): gate.verify_snapshot(self.root / 'evidence', HEAD, self.baseline, current=NOW)
    def test_json_duplicate_key_denies(self):
        path = self.root / 'duplicate.json'; path.write_bytes(b'{"a":1,"a":2}')
        with self.assertRaisesRegex(gate.GateStop, 'DUPLICATE'): gate.load(path)
    def test_path_escape_denies(self):
        for name in ('../outside', '/absolute', 'C:/outside', 'evidence\\a'):
            with self.subTest(name=name), self.assertRaises(gate.GateStop): gate.safe_file(self.root.resolve(), name)
    def test_execution_approval_absent_or_preparation_denies(self):
        verified = self.verify()
        for approval in (None, {}, {'kind': 'OWNER_EVIDENCE_ONLY_EXCEPTION', 'decision': 'APPROVED'}):
            with self.subTest(approval=approval), self.assertRaisesRegex(gate.GateStop, 'NOT_GRANTED'):
                dispatcher.verify_execution_approval(approval, verified, self.anchor, current=NOW)

class DispatcherTests(unittest.TestCase):
    setUp = BindingTests.setUp
    verify = BindingTests.verify
    def dispatch(self, changes=None, before=None, rc=0):
        verified = self.verify(); manifest, snapshot = verified['manifest'], verified['snapshot']
        value = {'status': 'PASS', 'operation_id': manifest['operation_id'], 'mode': 'preflight',
            'claim_absent': True, 'candidate_staged': False, 'production_mutation': False, 'business_system_write': False,
            'raw_secrets_accounts_keys_values_or_pii_emitted': False, 'candidate_head': HEAD,
            'snapshot_sha256': manifest['snapshot_sha256'], 'protected_services_sha256': self.baseline,
            'counter_evidence_sha256': snapshot['dependencies']['counter_receipt']['sha256'], 'package_manifest_sha256': self.anchor,
            'safety_counters': snapshot['safety_counters'], 'checked_at': NOW.isoformat()}
        value.update(changes or {})
        def invoker(argv, *, input_bytes, timeout):
            if before: before()
            return subprocess.CompletedProcess(argv, rc, json.dumps(value).encode(), b'')
        return dispatcher.dispatch_preflight(invoker, ['synthetic-ssh-never-launched'], package=self.root,
            expected_manifest=self.anchor, expected_head=HEAD, expected_baseline=self.baseline, input_bytes=b'synthetic',
            evidence_directory=Path(self.temp.name) / 'captures', current=NOW)
    def test_dispatcher_accepts_full_bindings_and_records_capture(self):
        value, path = self.dispatch(); self.assertEqual(value['status'], 'PASS')
        self.assertEqual(gate.load(path)['child_returncode'], 0)
    def test_dispatcher_rejects_every_wrong_remote_binding_after_capture(self):
        for key in ('candidate_head', 'snapshot_sha256', 'protected_services_sha256', 'counter_evidence_sha256', 'package_manifest_sha256', 'operation_id'):
            with self.subTest(key=key), self.assertRaises(CaptureStop) as caught: self.dispatch({key: 'WRONG'})
            self.assertTrue(caught.exception.capture_path.is_file())
    def test_dispatcher_rechecks_tampering_during_child(self):
        with self.assertRaises(CaptureStop) as caught: self.dispatch(before=lambda: write(self.root / 'extra.json', {}))
        self.assertTrue(caught.exception.capture_path.is_file())
    def test_dispatcher_nonzero_exit_does_not_pass(self):
        with self.assertRaises(CaptureStop) as caught: self.dispatch(rc=2)
        self.assertEqual(gate.load(caught.exception.capture_path)['child_returncode'], 2)
    def test_dispatcher_invalid_package_never_invokes_child(self):
        write(self.root / 'extra.json', {})
        def forbidden(*args, **kwargs): self.fail('child was invoked')
        with self.assertRaises(gate.GateStop): dispatcher.dispatch_preflight(forbidden, [], package=self.root,
            expected_manifest=self.anchor, expected_head=HEAD, expected_baseline=self.baseline,
            input_bytes=b'', evidence_directory=Path(self.temp.name) / 'captures', current=NOW)

if __name__ == '__main__': unittest.main()
