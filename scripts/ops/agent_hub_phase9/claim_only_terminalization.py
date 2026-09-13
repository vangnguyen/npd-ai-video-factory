"""Metadata-only terminalization of the exact consumed RCA06 orphan.

ABORTED_BEFORE_STAGE is a NEW local contract in RCA-08, not a deployed state.
No remote invocation is made here. Production use needs separately issued
Owner authority, an exact tool digest and live read-only verification.
Original claim/state bytes are retained; a partial close fails execution shut.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
from uuid import UUID, uuid4

from operation_identity import CONSUMED_ABORTED_OPERATION, parse_operation_id

ROOT_PATH = '/var/lib/npd-ai/agent-hub-deployments/phase9-limited-pilot'
PLAN_SCHEMA = 'npd.phase9.claim-only-terminalization.plan.v1'
EXPECTED_STATE = 'CLAIMED'
TERMINAL_STATE = 'ABORTED_BEFORE_STAGE'
RECEIPT_NAME = 'claim-only-terminalization.json'

class TerminalizationStop(ValueError):
    pass

def require(value, reason):
    if value is not True: raise TerminalizationStop(reason)

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')

def sha(raw): return hashlib.sha256(raw).hexdigest()
def plan_digest(plan): return sha(canonical(plan) + b'\n')

def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'DUPLICATE_JSON_KEY'); result[key] = value
    return result

def decode(raw):
    return json.loads(raw, object_pairs_hook=unique,
        parse_constant=lambda value: (_ for _ in ()).throw(TerminalizationStop('NONFINITE_JSON')))

def utc(value):
    try: result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (ValueError, AttributeError, TypeError): raise TerminalizationStop('UTC_INVALID') from None
    require(result.utcoffset() == timezone.utc.utcoffset(result), 'UTC_NOT_UTC')
    return result

def allowed_paths(operation):
    return sorted([f'operations/{operation}.json', f'attempts/{operation}/state.json',
        f'attempts/{operation}/claim-before-terminalization.json',
        f'attempts/{operation}/state-before-terminalization.json',
        f'attempts/{operation}/{RECEIPT_NAME}'])

def verify_plan(plan):
    require(isinstance(plan, dict) and plan.get('schema') == PLAN_SCHEMA, 'PLAN_SCHEMA_INVALID')
    require(parse_operation_id(plan.get('operation_id')) == CONSUMED_ABORTED_OPERATION, 'OPERATION_NOT_EXACT_ORPHAN')
    try: identifier = UUID(plan.get('attempt_id'))
    except (ValueError, TypeError, AttributeError): raise TerminalizationStop('ATTEMPT_INVALID') from None
    require(str(identifier) == plan['attempt_id'] and identifier.version == 4, 'ATTEMPT_INVALID')
    require(plan.get('root_path') == ROOT_PATH, 'ROOT_BINDING_INVALID')
    require(plan.get('expected_current_state') == EXPECTED_STATE and plan.get('terminal_state') == TERMINAL_STATE,
        'STATE_CONTRACT_INVALID')
    require(plan.get('local_disposition') == 'ABORTED_BEFORE_STAGE_NOT_REUSABLE'
        and plan.get('pilot_execution_authorized') is False and plan.get('new_claim_authorized') is False,
        'SCOPE_INVALID')
    require(plan.get('allowed_metadata_paths') == allowed_paths(plan['operation_id']), 'METADATA_SCOPE_INVALID')
    for name in ('claim_sha256', 'state_sha256', 'claim_evidence_sha256', 'no_stage_no_deploy_evidence_sha256',
        'local_disposition_sha256', 'terminalization_tool_sha256', 'identity_contract_sha256',
        'approved_remote_runtime_sha256', 'approved_runtime_profile_sha256', 'candidate_ci_evidence_sha256', 'protected_services_sha256',
        'terminalization_entry_sha256', 'terminalization_contract_sha256', 'strict_transport_sha256'):
        value = plan.get(name)
        require(isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value),
            'PLAN_HASH_INVALID:' + name)
    head = plan.get('source_head')
    require(isinstance(head, str) and len(head) == 40 and all(c in '0123456789abcdef' for c in head), 'SOURCE_HEAD_INVALID')
    require(utc(plan['observed_at_utc']) < utc(plan['deadline_utc']), 'PLAN_DEADLINE_INVALID')
    require(utc(plan['old_mutation_deadline_utc']) <= utc(plan['observed_at_utc']), 'OLD_EXECUTION_WINDOW_STILL_OPEN')
    return plan

def approval_text(plan):
    verify_plan(plan)
    fields = [
        ('WORKSTREAM', 'Agent Hub ONLY'), ('REPO', 'vangnguyen/npd-ai-video-factory'),
        ('BRANCH', 'fix/agent-hub-p9-preflight-capture-20260912'), ('SOURCE HEAD', plan['source_head']),
        ('OLD OPERATION ID', plan['operation_id']), ('EXACT ATTEMPT / CLAIM ID', plan['attempt_id']),
        ('EXPECTED CURRENT CLAIM AND STATE', EXPECTED_STATE), ('EXACT TERMINAL STATE', TERMINAL_STATE),
        ('PLAN SHA-256', plan_digest(plan)), ('REMOTE CLAIM EVIDENCE SHA-256', plan['claim_evidence_sha256']),
        ('CURRENT CLAIM SHA-256', plan['claim_sha256']), ('CURRENT STATE SHA-256', plan['state_sha256']),
        ('NO-STAGE / NO-SCP / NO-DEPLOY EVIDENCE SHA-256', plan['no_stage_no_deploy_evidence_sha256']),
        ('LOCAL ABORT DISPOSITION SHA-256', plan['local_disposition_sha256']),
        ('TERMINALIZATION TOOL SHA-256', plan['terminalization_tool_sha256']),
        ('LOCAL EXACT-APPROVAL ENTRY SHA-256', plan['terminalization_entry_sha256']),
        ('TERMINALIZATION SOURCE CONTRACT SHA-256', plan['terminalization_contract_sha256']),
        ('PINNED SSH TRANSPORT SHA-256', plan['strict_transport_sha256']),
        ('PINNED RUNTIME PROFILE SHA-256', plan['approved_runtime_profile_sha256']),
        ('CANONICAL IDENTITY CONTRACT SHA-256', plan['identity_contract_sha256']),
        ('READ-ONLY RUNTIME VERIFIER SHA-256', plan['approved_remote_runtime_sha256']),
        ('EXACT CANDIDATE CI EVIDENCE SHA-256', plan['candidate_ci_evidence_sha256']),
        ('PROTECTED BASELINE SHA-256', plan['protected_services_sha256']),
        ('OBSERVED UTC', plan['observed_at_utc']), ('EXECUTION DEADLINE UTC (exclusive)', plan['deadline_utc']),
        ('ALLOWED METADATA PATHS ONLY', json.dumps(plan['allowed_metadata_paths'], separators=(',', ':')))]
    return ('TÔI, OWNER, CẤP EXPLICIT CLAIM-ONLY TERMINALIZATION APPROVAL CHO ĐÚNG ORPHAN OPERATION DƯỚI ĐÂY.\n'
        + '\n'.join(name + ': ' + value for name, value in fields) + '\n'
        + 'I authorize exactly one metadata-only close after fresh live read-only checks and exact claim/state hash comparison. Preserve original claim/state bytes in the bound custody files; write the terminal receipt and transition only this owned claim/state to ABORTED_BEFORE_STAGE. No retry, reactivation, new claim, stage, SCP, deploy, UAT, rollback, pilot execution or new JIT gate is authorized.\n'
        + 'No Agent Hub image/protected-service/Caddy/Redis/config/network/mount/volume/port change; no Video Factory change; no workflow/job/provider/customer/CRM/Sales/scheduler/automation/Run Now action or spend. The four Video Factory counters may only be read by the existing read-only verifier.\n'
        + 'The old pilot approval is consumed and cannot authorize this close or any execution. If ownership, bytes, state, inventory, live baseline or deadline differs, stop fail-closed. A partial close is terminal custody requiring review, never permission to retry the pilot.\n'
        + 'This separate approval takes effect only when explicitly issued verbatim by Owner before its deadline. Preparation alone is NOT_GRANTED.\n')

def verify_approval(plan, approval, *, current=None):
    verify_plan(plan)
    require(isinstance(approval, dict) and approval.get('kind') == 'OWNER_CLAIM_ONLY_TERMINALIZATION_APPROVAL'
        and approval.get('decision') == 'APPROVED' and approval.get('fresh_explicit_owner_approval') is True,
        'OWNER_TERMINALIZATION_APPROVAL_NOT_GRANTED')
    expected = {'plan_sha256': plan_digest(plan), 'operation_id': plan['operation_id'], 'attempt_id': plan['attempt_id'],
        'source_head': plan['source_head'], 'terminalization_tool_sha256': plan['terminalization_tool_sha256'],
        'owner_verbatim_sha256': sha(approval_text(plan).encode('utf-8')),
        'pilot_execution_authorized': False, 'new_claim_authorized': False}
    require(all(approval.get(name) == value for name, value in expected.items()), 'OWNER_TERMINALIZATION_BINDING_MISMATCH')
    now = current or datetime.now(timezone.utc)
    require(utc(plan['observed_at_utc']) <= now < utc(plan['deadline_utc']), 'TERMINALIZATION_OUTSIDE_WINDOW')
    return approval

def check_path(path, *, directory=False, root_metadata=True):
    info = path.lstat()
    require(not path.is_symlink() and (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)),
        'UNSAFE_PATH_TYPE')
    if root_metadata:
        require(info.st_uid == 0 and info.st_gid == 0 and stat.S_IMODE(info.st_mode) == (0o700 if directory else 0o600),
            'UNSAFE_ROOT_METADATA')

def observe_claim(root, plan, *, root_metadata=True):
    verify_plan(plan); root = Path(root)
    if root_metadata: require(str(root) == ROOT_PATH and os.name == 'posix', 'PRODUCTION_ROOT_INVALID')
    operation = plan['operation_id']; attempt = root / 'attempts' / operation; claim = root / 'operations' / (operation + '.json')
    for parent in (root, root/'operations', root/'attempts', attempt):check_path(parent,directory=True,root_metadata=root_metadata)
    state = attempt/'state.json'
    for path in (claim, state):check_path(path,root_metadata=root_metadata)
    require(sorted(p.name for p in attempt.iterdir()) == ['state.json'], 'STAGE_DEPLOY_OR_CUSTODY_FILE_PRESENT')
    claim_raw, state_raw = claim.read_bytes(), state.read_bytes()
    require(sha(claim_raw) == plan['claim_sha256'] and sha(state_raw) == plan['state_sha256'], 'CLAIM_STATE_HASH_MISMATCH')
    cv, sv = decode(claim_raw), decode(state_raw)
    for value in (cv, sv):
        require(value.get('operation_id') == operation and value.get('invocation_id') == plan['attempt_id'], 'CLAIM_ATTEMPT_OWNERSHIP_MISMATCH')
        require(value.get('status') == EXPECTED_STATE, 'CLAIM_STATE_NOT_ELIGIBLE')
    require(cv.get('claim_id') == plan['attempt_id'] and cv.get('reset_for_retry_allowed') is False, 'CLAIM_RETRY_OR_ATTEMPT_INVALID')
    require(cv.get('claimed_at') == sv.get('claimed_at') == plan['expected_claimed_at_utc'], 'CLAIM_TIMESTAMP_MISMATCH')
    require((cv.get('window') or {}).get('latest_mutation_utc') == plan['old_mutation_deadline_utc']
        and utc(plan['old_mutation_deadline_utc']) <= utc(plan['observed_at_utc']), 'OLD_WINDOW_BINDING_MISMATCH')
    require(sv.get('target_mutation_attempted') is False and sv.get('candidate_deployment_retry_allowed') is False,
        'TARGET_MUTATION_OR_RETRY_PRESENT')
    require(sv.get('before') == plan['expected_target'] and sv.get('protected_services_sha256') == plan['protected_services_sha256'], 'STATE_BASELINE_MISMATCH')
    require(sv.get('baseline_safety_counters') == plan['expected_safety_counters'] and sv.get('baseline_namespace_key_count') == plan['expected_namespace_key_count'], 'STATE_COUNTER_BINDING_MISMATCH')
    return claim, state, claim_raw, state_raw, cv, sv

def verify_live(plan, value):
    require(isinstance(value,dict) and value.get('status') == 'PASS_READONLY_BASELINE', 'LIVE_BASELINE_NOT_PASS')
    require(value.get('target') == plan['expected_target'] and value.get('protected_services_sha256') == plan['protected_services_sha256'], 'LIVE_TARGET_OR_PROTECTED_DRIFT')
    require(value.get('safety_counters') == plan['expected_safety_counters'] and value.get('namespace_key_count') == plan['expected_namespace_key_count'], 'LIVE_COUNTER_DRIFT')
    require(value.get('cohort_review_count') == 0 and value.get('writes') == 0, 'LIVE_READONLY_SCOPE_INVALID')
    return value

def create_private(path, raw):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, 'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())

def replace_owned(path, raw, expected_sha):
    require(sha(path.read_bytes()) == expected_sha and not path.is_symlink(), 'COMPARE_AND_SWAP_MISMATCH')
    temporary = path.parent / ('.terminalizing-' + str(uuid4()))
    create_private(temporary, raw)
    try:
        require(sha(path.read_bytes()) == expected_sha and not path.is_symlink(), 'COMPARE_AND_SWAP_MISMATCH')
        os.replace(temporary, path)
        if os.name == 'posix':
            directory = os.open(path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
            try:os.fsync(directory)
            finally:os.close(directory)
    finally:
        if temporary.exists():temporary.unlink()

def terminalize(root, plan, approval, *, tool_sha256, verify_runtime, current=None, root_metadata=True):
    """Only owned metadata; root_metadata=False is for explicit local fixtures."""
    verify_approval(plan, approval, current=current)
    require(tool_sha256 == plan['terminalization_tool_sha256'], 'TOOL_HASH_MISMATCH')
    claim, state, claim_raw, state_raw, cv, sv = observe_claim(root,plan,root_metadata=root_metadata)
    verify_live(plan, verify_runtime(plan))
    # Re-read both bytes/inventory immediately after the live observations.
    observe_claim(root,plan,root_metadata=root_metadata)
    verify_approval(plan, approval, current=current)
    attempt = state.parent; timestamp = (current or datetime.now(timezone.utc)).isoformat()
    transition = {'status': 'TERMINALIZATION_INTENT', 'operation_id': plan['operation_id'], 'attempt_id': plan['attempt_id'],
        'expected_state': EXPECTED_STATE, 'terminal_state': TERMINAL_STATE, 'terminalized_at_utc': timestamp,
        'plan_sha256': plan_digest(plan), 'tool_sha256': tool_sha256, 'original_claim_sha256': sha(claim_raw),
        'original_state_sha256': sha(state_raw), 'pilot_retry_allowed': False, 'image_switches': 0, 'provider_calls': 0, 'video_factory_writes': 0}
    create_private(attempt/'claim-before-terminalization.json',claim_raw)
    create_private(attempt/'state-before-terminalization.json',state_raw)
    receipt = attempt/RECEIPT_NAME; intent_raw = canonical(transition)+b'\n';create_private(receipt,intent_raw)
    for value in (cv,sv):
        value.update({'status':TERMINAL_STATE,'terminalized_at_utc':timestamp,'terminalization_plan_sha256':plan_digest(plan),
            'terminalization_tool_sha256':tool_sha256,'original_claim_sha256':sha(claim_raw),'original_state_sha256':sha(state_raw),
            'reset_for_retry_allowed':False,'candidate_deployment_retry_allowed':False,'target_mutation_attempted':False})
    # State first: if interrupted, sealed deploy/UAT/rollback cannot run from CLAIMED.
    verify_approval(plan, approval, current=current)
    require(sha(claim.read_bytes()) == plan['claim_sha256'], 'CLAIM_CHANGED_BEFORE_TERMINAL_STATE')
    state_terminal = canonical(sv)+b'\n';replace_owned(state,state_terminal,plan['state_sha256'])
    claim_terminal = canonical(cv)+b'\n';replace_owned(claim,claim_terminal,plan['claim_sha256'])
    require(state.read_bytes() == state_terminal and claim.read_bytes() == claim_terminal, 'TERMINAL_READBACK_MISMATCH')
    verify_live(plan, verify_runtime(plan));verify_approval(plan,approval,current=current)
    transition.update({'status':'TERMINALIZATION_COMPLETE_VERIFIED','claim_sha256':sha(claim_terminal),'state_sha256':sha(state_terminal)})
    replace_owned(receipt,canonical(transition)+b'\n',sha(intent_raw))
    return transition
