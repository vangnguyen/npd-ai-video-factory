"""Mandatory full-binding verification before and after fresh read-only preflight."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gate_bindings import GateStop, WINDOW_FIELDS, fresh, require, sha, utc_time, verify_package
from remote_preflight_capture import invoke_preflight

def dispatch_preflight(invoker, argv, *, package, expected_manifest, expected_head,
        expected_baseline, input_bytes, evidence_directory, timeout=90, current=None):
    verified = verify_package(package, expected_manifest, expected_head, expected_baseline, current=current)
    operation = verified['manifest']['operation_id']
    expected = {'candidate_head': expected_head, 'snapshot_sha256': verified['manifest']['snapshot_sha256'],
        'protected_services_sha256': expected_baseline,
        'counter_evidence_sha256': verified['snapshot']['dependencies']['counter_receipt']['sha256'],
        'package_manifest_sha256': expected_manifest, 'operation_id': operation,
        'safety_counters': verified['snapshot']['safety_counters']}
    def verifier(value):
        # Recheck files and freshness after the remote child returns as well.
        verify_package(package, expected_manifest, expected_head, expected_baseline, current=current)
        fresh(value.get('checked_at'), current or datetime.now(timezone.utc))
        return all(value.get(key) == wanted for key, wanted in expected.items())
    return invoke_preflight(invoker, argv, input_bytes=input_bytes, timeout=timeout,
        evidence_directory=Path(evidence_directory), binding_id=operation, success_verifier=verifier)

def verify_execution_approval(approval, verified, expected_manifest, *, current=None, phase='mutation'):
    require(isinstance(approval, dict) and approval.get('kind') == 'OWNER_EXECUTION_APPROVAL'
        and approval.get('decision') == 'APPROVED' and approval.get('fresh_explicit_owner_execution_approval') is True,
        'OWNER_EXECUTION_APPROVAL_NOT_GRANTED')
    bindings = verified['bindings']
    for name, value in {'operation_id': bindings['operation_id'], 'candidate_head': bindings['candidate_head'],
        'package_manifest_sha256': expected_manifest, 'snapshot_sha256': bindings['snapshot_sha256'],
        'counter_evidence_sha256': verified['snapshot']['dependencies']['counter_receipt']['sha256'],
        'dependency_hashes': bindings['dependency_hashes']}.items():
        require(approval.get(name) == value, 'EXECUTION_APPROVAL_BINDING_MISMATCH:' + name)
    require(approval.get('preparation_disposition_used_as_execution_approval') is False, 'PREPARATION_IS_NOT_EXECUTION_APPROVAL')
    window = approval.get('window')
    require(approval.get('execution_window_sha256') == bindings['dependency_hashes']['EXECUTION_WINDOW.json']
        and window == {name: verified['window'][name] for name in WINDOW_FIELDS}, 'EXECUTION_APPROVAL_WINDOW_MISMATCH')
    require(isinstance(window, dict) and set(window) == {'start_utc', 'latest_mutation_utc', 'decision_deadline_utc', 'recovery_deadline_utc'},
        'FRESH_EXECUTION_WINDOW_UNBOUND')
    try:
        times = [datetime.fromisoformat(window[name].replace('Z', '+00:00')) for name in
            ['start_utc', 'latest_mutation_utc', 'decision_deadline_utc', 'recovery_deadline_utc']]
        require(all(t.utcoffset() == timezone.utc.utcoffset(t) for t in times), 'EXECUTION_WINDOW_NOT_UTC')
        now = current or datetime.now(timezone.utc)
        require(phase in {'dispatch', 'mutation', 'decision', 'recovery'}, 'EXECUTION_PHASE_INVALID')
        limit = utc_time(verified['window']['latest_dispatcher_start_utc']) if phase == 'dispatch' else times[{'mutation': 1, 'decision': 2, 'recovery': 3}[phase]]
        require(times[0] < times[1] < times[2] < times[3] and times[0] <= now < limit, 'EXECUTION_OUTSIDE_FRESH_WINDOW')
    except (TypeError, ValueError, AttributeError): raise GateStop('FRESH_EXECUTION_WINDOW_INVALID') from None
    return approval
