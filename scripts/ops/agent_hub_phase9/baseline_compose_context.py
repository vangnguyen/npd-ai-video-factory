"""Exact recovered compose provenance, never permission to reuse its operation."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
from uuid import UUID
from operation_identity import RECOVERED_TERMINAL_OPERATION, parse_operation_id

COMPOSE_BINDING_SCHEMA = 'npd.agent-hub.phase9.recovered-compose-binding.v1'
COMPOSE_BASE_PATH = '/opt/npd-ai-video-factory-releases/400899ba82501beeea469f4a33dc169a9a09bb8e/deploy/phase5/docker-compose.agent-hub.prod.yml'
COMPOSE_CLAIM_ROOT = '/var/lib/npd-ai/agent-hub-deployments/phase9-limited-pilot'
COMPOSE_ROLLBACK_CONFIG = 'sha256:470810b2dbb2c525df971129b6bcf8cf31f4f2b7a4167721989a9bec01537041'

class ComposeBindingError(ValueError):
    pass

def bc_require(condition, reason):
    if condition is not True:
        raise ComposeBindingError(reason)

def validate_compose_binding(value, base_compose, claim_root, rollback_config):
    keys = {'schema', 'provenance_only', 'execution_authorized', 'operation_id', 'attempt_id',
        'terminal_state', 'claim_state', 'rollback_image_config', 'container_id',
        'target_signature_sha256', 'config_files', 'metadata_sha256',
        'recovery_receipt_sha256', 'source_observation_sha256'}
    bc_require(isinstance(value, dict) and set(value) == keys, 'COMPOSE_BASELINE_BINDING_INVALID')
    bc_require(value['schema'] == COMPOSE_BINDING_SCHEMA and value['provenance_only'] is True
        and value['execution_authorized'] is False, 'COMPOSE_BASELINE_AUTHORITY_FORBIDDEN')
    bc_require(value['operation_id'] == RECOVERED_TERMINAL_OPERATION, 'COMPOSE_BASELINE_HISTORY_INVALID')
    parse_operation_id(value['operation_id'])  # Custody parsing only, never fresh execution validation.
    try:
        attempt = UUID(value['attempt_id'])
        bc_require(str(attempt) == value['attempt_id'] and attempt.version == 4, 'COMPOSE_BASELINE_ATTEMPT_INVALID')
    except (ValueError, TypeError, AttributeError):
        raise ComposeBindingError('COMPOSE_BASELINE_ATTEMPT_INVALID') from None
    bc_require(value['terminal_state'] == 'ROLLED_BACK_VERIFIED' and value['claim_state'] == 'CLAIMED',
        'COMPOSE_BASELINE_NOT_RECOVERED')
    bc_require(value['rollback_image_config'] == rollback_config, 'COMPOSE_BASELINE_IMAGE_MISMATCH')
    root = PurePosixPath(str(claim_root)); base = PurePosixPath(str(base_compose))
    bc_require(root.is_absolute() and base.is_absolute() and '..' not in root.parts + base.parts,
        'COMPOSE_BASELINE_PATH_INVALID')
    operation = value['operation_id']; directory = root / 'attempts' / operation
    paths = [str(base), str(directory / 'rollback-override.json')]
    bc_require(value['config_files'] == paths, 'COMPOSE_BASELINE_PATH_MISMATCH')
    expected = {str(directory / 'rollback-override.json'), str(directory / 'state.json'),
        str(root / 'operations' / (operation + '.json'))}
    hashes = value['metadata_sha256']
    bc_require(isinstance(hashes, dict) and set(hashes) == expected, 'COMPOSE_BASELINE_CUSTODY_SET_INVALID')
    digests = [value[k] for k in ('container_id', 'target_signature_sha256',
        'recovery_receipt_sha256', 'source_observation_sha256')] + list(hashes.values())
    bc_require(all(isinstance(h, str) and re.fullmatch('[0-9a-f]{64}', h) is not None for h in digests),
        'COMPOSE_BASELINE_DIGEST_INVALID')
    return value

def bc_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            bc_require(key not in result, 'COMPOSE_BASELINE_DUPLICATE_JSON_KEY'); result[key] = value
        return result
    try:
        bc_require(type(raw) is bytes and not raw.startswith(b'\xef\xbb\xbf'), 'COMPOSE_BASELINE_ENCODING_INVALID')
        return json.loads(raw.decode('utf-8'), object_pairs_hook=unique,
            parse_constant=lambda _: (_ for _ in ()).throw(ComposeBindingError('COMPOSE_BASELINE_JSON_INVALID')))
    except (ValueError, UnicodeError, TypeError):
        raise ComposeBindingError('COMPOSE_BASELINE_JSON_INVALID') from None

def read_compose_custody(value, claim_root):
    """Read exact owned private bytes, with no symlink or writable ancestor."""
    root = Path(claim_root); result = {}
    for name, wanted in value['metadata_sha256'].items():
        path = Path(name)
        bc_require(path.is_relative_to(root) and path.resolve() == path, 'COMPOSE_BASELINE_CUSTODY_PATH_UNSAFE')
        for directory in (root, *path.relative_to(root).parents):
            directory = directory if directory == root else root / directory
            info = directory.lstat()
            bc_require(stat.S_ISDIR(info.st_mode) and info.st_uid == info.st_gid == 0
                and stat.S_IMODE(info.st_mode) == 0o700 and not directory.is_symlink(),
                'COMPOSE_BASELINE_CUSTODY_UNSAFE')
        info = path.lstat()
        bc_require(stat.S_ISREG(info.st_mode) and info.st_uid == info.st_gid == 0
            and stat.S_IMODE(info.st_mode) == 0o600, 'COMPOSE_BASELINE_CUSTODY_UNSAFE')
        raw = path.read_bytes()
        bc_require(hashlib.sha256(raw).hexdigest() == wanted, 'COMPOSE_BASELINE_CUSTODY_HASH_MISMATCH')
        result[name] = raw
    return result

def verify_recovered_compose(value, item, config_files, base_compose, claim_root,
        rollback_config, rollback_tag, signature_sha256, custody_reader=read_compose_custody):
    value = validate_compose_binding(value, base_compose, claim_root, rollback_config)
    bc_require(item.get('Id') == value['container_id'] and item.get('Image') == rollback_config
        and item.get('Config', {}).get('Image') == rollback_tag
        and signature_sha256 == value['target_signature_sha256'], 'COMPOSE_BASELINE_TARGET_MISMATCH')
    bc_require(config_files == value['config_files'], 'COMPOSE_BASELINE_PATH_MISMATCH')
    raw = custody_reader(value, claim_root)
    bc_require(set(raw) == set(value['metadata_sha256']), 'COMPOSE_BASELINE_CUSTODY_SET_INVALID')
    for name, wanted in value['metadata_sha256'].items():
        bc_require(type(raw[name]) is bytes and hashlib.sha256(raw[name]).hexdigest() == wanted,
            'COMPOSE_BASELINE_CUSTODY_HASH_MISMATCH')
    directory = PurePosixPath(str(claim_root)) / 'attempts' / value['operation_id']
    override = bc_json(raw[str(directory / 'rollback-override.json')])
    state = bc_json(raw[str(directory / 'state.json')])
    claim = bc_json(raw[str(PurePosixPath(str(claim_root)) / 'operations' / (value['operation_id'] + '.json'))])
    bc_require(override == {'services': {'agent-hub': {'image': rollback_tag}}}, 'COMPOSE_BASELINE_OVERRIDE_INVALID')
    bc_require(claim.get('operation_id') == state.get('operation_id') == value['operation_id']
        and claim.get('claim_id') == claim.get('invocation_id') == state.get('invocation_id') == value['attempt_id'],
        'COMPOSE_BASELINE_OWNERSHIP_MISMATCH')
    bc_require(claim.get('status') == 'CLAIMED' and state.get('status') == 'ROLLED_BACK_VERIFIED'
        and state.get('target_mutation_attempted') is True
        and claim.get('reset_for_retry_allowed') is False and state.get('candidate_deployment_retry_allowed') is False,
        'COMPOSE_BASELINE_NOT_RECOVERED')
    bc_require((state.get('rollback_verification') or {}).get('target', {}).get('image_id') == rollback_config,
        'COMPOSE_BASELINE_RECOVERY_IMAGE_MISMATCH')
    return True
