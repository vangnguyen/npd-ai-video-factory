"""Verify a fresh Phase 9 preparation package; this module performs no writes."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from uuid import UUID

COUNTERS = ('video_factory_job_count', 'video_factory_queue_count',
            'video_factory_processing_count', 'video_factory_in_flight_count')
AGENT_COUNTERS = ('cohort_task_count', 'tool_execution_total', 'execution_audit_count',
                 'video_tool_execution_count', 'video_execution_audit_count',
                 'planned_video_action_count', 'forbidden_context_count')
MAX_COUNTER_AGE_SECONDS = 600
REQUIRED_PILOT_FILES = {'runner.py', 'dispatcher.py', 'verifier.py', 'remote_runtime.py', 'rollback.py',
    'finalizer.py', 'ssh_path_contract.py', 'remote_preflight_capture.py', 'CONFIRMATION_CONTRACT.json',
    'ARTIFACT_MANIFEST.json', 'EXECUTION_SCOPE.json', 'PILOT_PAYLOAD.json',
    'RUNTIME_PROFILE.json', 'OWNER_GATE.md', 'candidate.oci.tar', 'ROLLBACK_CUSTODY_MANIFEST.json',
    'gate_bindings.py', 'pilot_dispatcher.py', 'pilot_transport.py',
    'evidence/FULL_EXECUTION_SNAPSHOT.json', 'evidence/COUNTER_EVIDENCE.json', 'evidence/PROTECTED_BASELINE.json'}
HASH = re.compile(r'[0-9a-f]{64}')
HEAD = re.compile(r'[0-9a-f]{40}')

class GateStop(ValueError):
    pass

def require(condition, reason):
    if condition is not True: raise GateStop(reason)

def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''): digest.update(chunk)
    return digest.hexdigest()

def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'DUPLICATE_JSON_KEY'); result[key] = value
    return result

def load(path):
    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(GateStop('NONFINITE_JSON')))

def canonical_digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, allow_nan=False,
        sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def fresh(timestamp, current):
    try: observed = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    except (TypeError, ValueError, AttributeError): raise GateStop('COUNTER_TIMESTAMP_INVALID') from None
    require(observed.utcoffset() == timezone.utc.utcoffset(observed), 'COUNTER_TIMESTAMP_NOT_UTC')
    require(-5 <= (current - observed).total_seconds() <= MAX_COUNTER_AGE_SECONDS, 'COUNTER_RECEIPT_STALE_OR_FUTURE')

def safe_file(directory, relative):
    require(isinstance(relative, str) and bool(relative), 'DEPENDENCY_PATH_INVALID')
    parts = PurePosixPath(relative).parts
    require(not PurePosixPath(relative).is_absolute() and not any(p in {'.', '..'} for p in parts)
        and '\\' not in relative and ':' not in relative, 'DEPENDENCY_PATH_INVALID')
    path = directory / relative
    require(not any((directory / Path(*parts[:i])).is_symlink() for i in range(1, len(parts) + 1)), 'DEPENDENCY_SYMLINK')
    require(path.resolve(strict=True).is_relative_to(directory), 'DEPENDENCY_PATH_ESCAPE')
    return path

def verify_snapshot(directory, expected_head, expected_baseline, *, current=None):
    directory = Path(directory).resolve(strict=True)
    current = current or datetime.now(timezone.utc)
    require(bool(HEAD.fullmatch(expected_head)), 'EXPECTED_HEAD_INVALID')
    require(bool(HASH.fullmatch(expected_baseline)), 'EXPECTED_BASELINE_INVALID')
    snapshot = load(directory / 'FULL_EXECUTION_SNAPSHOT.json')
    require(snapshot.get('status') == 'PASS' and snapshot.get('full_execution_snapshot_complete') is True,
        'FULL_EXECUTION_SNAPSHOT_INCOMPLETE')
    require(snapshot.get('candidate_head') == expected_head, 'SNAPSHOT_HEAD_MISMATCH')
    require(snapshot.get('agent_hub_counter_names') == list(AGENT_COUNTERS), 'AGENT_COUNTER_CONTRACT_MISMATCH')
    require(snapshot.get('protected_canonical_sha256') == expected_baseline, 'SNAPSHOT_BASELINE_MISMATCH')
    dependencies = snapshot.get('dependencies')
    required = {'baseline', 'counter_receipt', 'counter_transport', 'exception_receipt', 'query_spec',
                'roles', 'backup', 'restore', 'backup_restore'}
    require(isinstance(dependencies, dict) and set(dependencies) == required, 'SNAPSHOT_DEPENDENCY_SET_INVALID')
    values = {}
    for name, entry in dependencies.items():
        require(isinstance(entry, dict) and bool(HASH.fullmatch(entry.get('sha256', ''))), 'DEPENDENCY_HASH_INVALID')
        path = safe_file(directory, entry.get('path'))
        require(sha(path) == entry['sha256'], 'DEPENDENCY_HASH_MISMATCH:' + name)
        values[name] = load(path)
    baseline, receipt, roles = values['baseline'], values['counter_receipt'], values['roles']
    exception = values['exception_receipt']
    require(exception.get('status') == 'OWNER_ACCEPTED_EVIDENCE_ONLY_EXCEPTION'
        and exception.get('exact_counter_identifiers') == list(COUNTERS)
        and exception.get('counter_ids_extracted_from_existing_contract') is True
        and exception.get('execution_approval') == 'NOT_GRANTED'
        and exception.get('video_factory_workstream_opened') is False, 'OWNER_EXCEPTION_SCOPE_INVALID')
    require(baseline.get('protected_sha256') == expected_baseline and baseline.get('protected_count') == 18,
        'PROTECTED_BASELINE_MISMATCH')
    require(isinstance(baseline.get('protected_signatures'), dict) and len(baseline['protected_signatures']) == 18,
        'PROTECTED_SERVICE_COUNT_INVALID')
    require(canonical_digest(baseline.get('protected_signatures')) == expected_baseline, 'PROTECTED_SIGNATURE_MISMATCH')
    require(baseline.get('candidate_head') == expected_head, 'BASELINE_HEAD_MISMATCH')
    require(baseline.get('claim_absent') is True and baseline.get('production_mutation') is False, 'BASELINE_NOT_READONLY')
    require(receipt.get('candidate_head') == expected_head, 'COUNTER_HEAD_MISMATCH')
    require(receipt.get('status') == 'PASS', 'COUNTER_RECEIPT_NOT_PASS')
    require(receipt.get('protected_canonical_sha256') == expected_baseline, 'COUNTER_BASELINE_MISMATCH')
    require(receipt.get('source_agent_hub_container_id') == baseline.get('target', {}).get('id'), 'COUNTER_TARGET_MISMATCH')
    require(receipt.get('owner_exception_receipt_sha256') == dependencies['exception_receipt']['sha256'], 'COUNTER_EXCEPTION_MISMATCH')
    require(receipt.get('query_spec_sha256') == dependencies['query_spec']['sha256'], 'COUNTER_QUERY_SPEC_MISMATCH')
    require(receipt.get('query_lua_sha256') == values['query_spec'].get('lua_sha256')
        and receipt.get('sanitized_command_fingerprint') == canonical_digest(values['query_spec']), 'COUNTER_COMMAND_FINGERPRINT_MISMATCH')
    require(receipt.get('server_enforced_readonly') is True and receipt.get('query_command') == 'EVAL_RO'
        and receipt.get('redis_reference', {}).get('db') == 0, 'COUNTER_NOT_SERVER_READONLY_DB0')
    require(receipt.get('production_mutation') is False and receipt.get('video_factory_writes') == 0
        and receipt.get('raw_keys_values_credentials_or_job_payloads_emitted') is False, 'COUNTER_SCOPE_INVALID')
    counters = receipt.get('counters')
    require(isinstance(counters, dict) and set(counters) == set(COUNTERS), 'COUNTER_SET_INVALID')
    require(all(type(value) is int and value >= 0 for value in counters.values()), 'COUNTER_VALUE_INVALID')
    require(all(counters[name] == 0 for name in COUNTERS[1:]), 'VIDEO_FACTORY_NOT_IDLE')
    fresh(receipt.get('observed_at_utc'), current)
    transport = values['counter_transport']
    require(transport.get('child_returncode') == 0 and type(transport.get('child_returncode')) is int
        and transport.get('stderr', {}).get('length_bytes') == 0 and transport.get('timed_out') is False
        and transport.get('binding_id') == receipt.get('operation_id'), 'COUNTER_TRANSPORT_INVALID')
    try: require(str(UUID(transport.get('invocation_id'))) == transport.get('invocation_id'), 'COUNTER_UUID_INVALID')
    except (ValueError, TypeError, AttributeError): raise GateStop('COUNTER_UUID_INVALID') from None
    raw = json.dumps(receipt, sort_keys=True).encode() + b'\n'
    require(transport.get('stdout', {}).get('sha256') == hashlib.sha256(raw).hexdigest()
        and transport.get('stdout', {}).get('length_bytes') == len(raw), 'COUNTER_PRIMARY_CAPTURE_MISMATCH')
    safety = roles.get('role_config_and_redis_safety', {})
    require(roles.get('candidate_head') == expected_head, 'ROLE_HEAD_MISMATCH')
    require(set(safety.get('role_assignments', {})) == {'owner', 'operator', 'viewer'}
        and all(row.get('matches_expected') is True for row in safety['role_assignments'].values()), 'ROLE_BINDING_INVALID')
    require(set(roles.get('role_whoami', {})) == {'owner', 'operator', 'viewer'}
        and all(row.get('role_match') is True for row in roles['role_whoami'].values()), 'WHOAMI_INVALID')
    require(safety.get('configuration_valid') is True and safety.get('external_executor_configured') is False,
        'SAFETY_CONFIGURATION_INVALID')
    require(safety.get('namespace_key_count') == values['backup'].get('source_validation', {}).get('key_count'), 'BACKUP_NAMESPACE_COUNT_MISMATCH')
    require(values['backup'].get('status') == 'PASS' and values['restore'].get('status') == 'PASS', 'BACKUP_RESTORE_NOT_PASS')
    require(values['restore'].get('fresh_backup_manifest_sha256') == dependencies['backup']['sha256'], 'RESTORE_BACKUP_BINDING_MISMATCH')
    require(values['restore'].get('redis_values_types_and_ttls_verified') == safety.get('namespace_key_count'), 'RESTORE_KEY_COUNT_MISMATCH')
    require(values['backup_restore'].get('status') == 'PASS'
        and values['backup_restore'].get('backup_manifest_sha256') == dependencies['backup']['sha256']
        and values['backup_restore'].get('restore_sha256') == dependencies['restore']['sha256'], 'BACKUP_RESTORE_SUMMARY_MISMATCH')
    require(all(type(safety.get(name)) is int and safety[name] >= 0 for name in AGENT_COUNTERS), 'AGENT_COUNTER_VALUE_INVALID')
    require(all(safety.get(name) == 0 and type(safety.get(name)) is int for name in
        ['planned_video_action_count', 'forbidden_context_count', 'video_tool_execution_count', 'video_execution_audit_count']), 'FORBIDDEN_ACTION_COUNTER')
    require(snapshot.get('safety_counters') == {**{name: safety[name] for name in snapshot['agent_hub_counter_names']}, **counters},
        'SNAPSHOT_COUNTER_BINDING_MISMATCH')
    return snapshot

def verify_package(directory, expected_manifest, expected_head, expected_baseline, *, current=None):
    directory = Path(directory).resolve(strict=True)
    require(bool(HASH.fullmatch(expected_manifest)), 'EXTERNAL_MANIFEST_ANCHOR_INVALID')
    path = directory / 'PACKAGE_MANIFEST.json'
    require(sha(path) == expected_manifest, 'PACKAGE_MANIFEST_MISMATCH')
    manifest = load(path)
    require(manifest.get('candidate_head') == expected_head, 'PACKAGE_HEAD_MISMATCH')
    require(manifest.get('status') == 'PREPARED_FOR_OWNER_REVIEW' and manifest.get('execution_approval') == 'NOT_GRANTED',
        'PREPARATION_AUTHORITY_INVALID')
    operation = manifest.get('operation_id', '')
    prefix = 'PHASE9-LIMITED-PILOT-RCA05-'
    require(operation.startswith(prefix), 'OPERATION_ID_INVALID')
    try: require(str(UUID(operation[len(prefix):])) == operation[len(prefix):], 'OPERATION_ID_INVALID')
    except (ValueError, TypeError, AttributeError): raise GateStop('OPERATION_ID_INVALID') from None
    listed = set()
    for entry in manifest['artifacts']:
        name = entry['path']; require(name.casefold() not in {p.casefold() for p in listed}, 'DUPLICATE_ARTIFACT')
        listed.add(name); artifact = safe_file(directory, name)
        require(type(entry['length_bytes']) is int and artifact.stat().st_size == entry['length_bytes']
            and sha(artifact) == entry['sha256'], 'ARTIFACT_HASH_MISMATCH:' + name)
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file() and p != path}
    require(actual == listed and bool(listed), 'ARTIFACT_INVENTORY_MISMATCH')
    snapshot = verify_snapshot(directory / 'evidence', expected_head, expected_baseline, current=current)
    require(manifest.get('snapshot_sha256') == sha(directory / 'evidence/FULL_EXECUTION_SNAPSHOT.json'), 'PACKAGE_SNAPSHOT_MISMATCH')
    bindings = load(directory / 'OPERATION_BINDINGS.json')
    require(bindings.get('operation_id') == operation and bindings.get('candidate_head') == expected_head, 'OPERATION_BINDING_MISMATCH')
    require(bindings.get('snapshot_sha256') == manifest['snapshot_sha256'], 'OPERATION_SNAPSHOT_MISMATCH')
    payload = load(directory / 'PILOT_PAYLOAD.json')
    require(payload.get('operation_id') == operation and payload.get('candidate_head') == expected_head
        and payload.get('snapshot_sha256') == manifest['snapshot_sha256'], 'PAYLOAD_BINDING_MISMATCH')
    require(isinstance(bindings.get('dependency_hashes'), dict) and REQUIRED_PILOT_FILES <= set(bindings['dependency_hashes']),
        'PILOT_DEPENDENCY_SET_INCOMPLETE')
    for name, expected in bindings['dependency_hashes'].items():
        require(sha(safe_file(directory, name)) == expected, 'OPERATION_DEPENDENCY_MISMATCH:' + name)
    artifacts = load(directory / 'ARTIFACT_MANIFEST.json')
    require(artifacts.get('artifact_hashes') == {name: value for name, value in bindings['dependency_hashes'].items()
        if name != 'ARTIFACT_MANIFEST.json'}, 'ARTIFACT_MANIFEST_BINDING_MISMATCH')
    require(payload.get('counter_evidence_sha256') == snapshot['dependencies']['counter_receipt']['sha256']
        and payload.get('execution_scope_sha256') == bindings['dependency_hashes']['EXECUTION_SCOPE.json'], 'PAYLOAD_SCOPE_COUNTER_MISMATCH')
    contract = load(directory / 'CONFIRMATION_CONTRACT.json')
    profile = load(directory / 'RUNTIME_PROFILE.json')
    for value, reason in ((contract, 'CONFIRMATION_BINDING_MISMATCH'), (profile, 'RUNTIME_PROFILE_BINDING_MISMATCH')):
        require(value.get('operation_id') == operation and value.get('candidate_head') == expected_head
            and value.get('snapshot_sha256') == manifest['snapshot_sha256']
            and value.get('counter_evidence_sha256') == snapshot['dependencies']['counter_receipt']['sha256']
            and value.get('protected_services_sha256') == expected_baseline, reason)
    require(bool(HASH.fullmatch(contract.get('confirmation_token_sha256', '')))
        and bool(HASH.fullmatch(contract.get('private_dpapi_blob_sha256', '')))
        and profile.get('confirmation_token_sha256') == contract['confirmation_token_sha256'], 'CONFIRMATION_CONTRACT_INVALID')
    require(profile.get('candidate_archive_sha256') == bindings['dependency_hashes']['candidate.oci.tar']
        and profile.get('candidate_archive_size') == (directory / 'candidate.oci.tar').stat().st_size, 'CANDIDATE_ARCHIVE_PROFILE_MISMATCH')
    return {'manifest': manifest, 'snapshot': snapshot, 'bindings': bindings, 'payload': payload}
