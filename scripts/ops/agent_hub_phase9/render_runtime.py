"""Render operation-specific constants without executing the audited template."""
import ast
from pathlib import Path

BINDINGS = {'OPERATION': 'operation_id', 'TOKEN_SHA': 'confirmation_token_sha256',
    'FRESH_BACKUP_MANIFEST_SHA': 'fresh_backup_manifest_sha256', 'ROLLBACK_BUNDLE_MANIFEST_SHA': 'rollback_bundle_manifest_sha256',
    'BASELINE_PROTECTED_SHA': 'protected_services_sha256', 'CANDIDATE_HEAD': 'candidate_head',
    'SNAPSHOT_SHA': 'snapshot_sha256', 'COUNTER_EVIDENCE_SHA': 'counter_evidence_sha256',
    'OWNER_EXCEPTION_SHA': 'owner_exception_receipt_sha256', 'CANDIDATE_TAG': 'candidate_tag',
    'CANDIDATE_ARCHIVE_SHA': 'candidate_archive_sha256', 'CANDIDATE_ARCHIVE_SIZE': 'candidate_archive_size'}

def render(template, profile):
    tree = ast.parse(Path(template).read_text(encoding='utf-8'))
    found = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in BINDINGS:
                    value = profile[BINDINGS[target.id]]
                    if value is None: raise ValueError('RUNTIME_PROFILE_UNBOUND')
                    node.value = ast.Constant(value); found.add(target.id)
    if found != set(BINDINGS): raise ValueError('RUNTIME_TEMPLATE_BINDINGS_INCOMPLETE')
    ast.fix_missing_locations(tree)
    output = ast.unparse(tree) + '\n'
    compile(output, 'fresh_remote_runtime', 'exec')
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            if any(isinstance(t, ast.Name) and t.id.endswith('_PROBE') for t in node.targets):
                compile(node.value.value, 'embedded_readonly_probe', 'exec')
    return output.encode()
