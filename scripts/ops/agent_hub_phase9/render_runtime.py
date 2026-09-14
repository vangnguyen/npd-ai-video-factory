"""Render operation-specific constants without executing the audited template."""
import ast
import json
from pathlib import Path
from operation_identity import validate_fresh_operation_id
from baseline_compose_context import validate_compose_binding, COMPOSE_BASE_PATH, COMPOSE_CLAIM_ROOT, COMPOSE_ROLLBACK_CONFIG

BINDINGS = {'OPERATION': 'operation_id', 'TOKEN_SHA': 'confirmation_token_sha256',
    'FRESH_BACKUP_MANIFEST_SHA': 'fresh_backup_manifest_sha256', 'ROLLBACK_BUNDLE_MANIFEST_SHA': 'rollback_bundle_manifest_sha256',
    'BASELINE_PROTECTED_SHA': 'protected_services_sha256', 'CANDIDATE_HEAD': 'candidate_head',
    'SNAPSHOT_SHA': 'snapshot_sha256', 'COUNTER_EVIDENCE_SHA': 'counter_evidence_sha256',
    'OWNER_EXCEPTION_SHA': 'owner_exception_receipt_sha256', 'CANDIDATE_TAG': 'candidate_tag',
    'CANDIDATE_ARCHIVE_SHA': 'candidate_archive_sha256', 'CANDIDATE_ARCHIVE_SIZE': 'candidate_archive_size',
    'BOUND_WINDOW_JSON': 'bound_window_json', 'EXECUTION_WINDOW_SHA': 'execution_window_sha256',
    'COUNTER_OBSERVED_AT': 'counter_observed_at_utc', 'INITIAL_DISPATCH_DEADLINE': 'initial_dispatch_deadline_utc',
    'LATEST_DISPATCHER_START': 'latest_dispatcher_start_utc'}

def render(template, profile):
    validate_fresh_operation_id(profile.get('operation_id'))
    tree = ast.parse(Path(template).read_text(encoding='utf-8'))
    # Inline the same canonical source for the standalone stdin remote runtime.
    contract = ast.parse(Path(__file__).with_name('operation_identity.py').read_text(encoding='utf-8'))
    contract_nodes = [node for node in contract.body if not (isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str))]
    compose = ast.parse(Path(__file__).with_name('baseline_compose_context.py').read_text(encoding='utf-8'))
    compose_nodes = [n for n in compose.body if not (isinstance(n, ast.ImportFrom) and n.module == 'operation_identity')
        and not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str))]
    custody = ast.parse(Path(__file__).with_name('custody_file_contract.py').read_text(encoding='utf-8'))
    custody_nodes = [n for n in custody.body if not (isinstance(n, ast.Expr)
        and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str))]
    expanded = []; imports = 0; compose_imports = 0; custody_imports = 0
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == 'operation_identity':
            expanded.extend(contract_nodes); imports += 1
        elif isinstance(node, ast.ImportFrom) and node.module == 'baseline_compose_context':
            expanded.extend(compose_nodes); compose_imports += 1
        elif isinstance(node, ast.ImportFrom) and node.module == 'custody_file_contract':
            expanded.extend(custody_nodes); custody_imports += 1
        else: expanded.append(node)
    if imports != 1: raise ValueError('CANONICAL_OPERATION_CONTRACT_IMPORT_INVALID')
    if compose_imports != 1: raise ValueError('COMPOSE_BASELINE_CONTRACT_IMPORT_INVALID')
    if custody_imports != 1: raise ValueError('FILE_CUSTODY_CONTRACT_IMPORT_INVALID')
    tree.body = expanded
    found = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in BINDINGS:
                    value = profile[BINDINGS[target.id]]
                    if value is None: raise ValueError('RUNTIME_PROFILE_UNBOUND')
                    node.value = ast.Constant(value); found.add(target.id)
    if found != set(BINDINGS): raise ValueError('RUNTIME_TEMPLATE_BINDINGS_INCOMPLETE')
    context = profile.get('baseline_compose_binding')
    if context is not None:
        validate_compose_binding(context, COMPOSE_BASE_PATH, COMPOSE_CLAIM_ROOT, COMPOSE_ROLLBACK_CONFIG)
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                updates = {'BASELINE_COMPOSE_BINDING_JSON':json.dumps(context, sort_keys=True, separators=(',', ':')),
                    'BASELINE_TARGET_ID':context['container_id'], 'BASELINE_TARGET_SIGNATURE_SHA':context['target_signature_sha256']}
                if name in updates: node.value = ast.Constant(updates[name])
    ast.fix_missing_locations(tree)
    output = ast.unparse(tree) + '\n'
    compile(output, 'fresh_remote_runtime', 'exec')
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            if any(isinstance(t, ast.Name) and t.id.endswith('_PROBE') for t in node.targets):
                compile(node.value.value, 'embedded_readonly_probe', 'exec')
    return output.encode()
