"""Fail-closed production runtime for one exact Agent-Hub-only pilot operation.

The file is transported in memory over strict-host-key SSH. It never prints
environment values, tokens, customer payloads, Redis keys, or raw HTTP bodies.
"""
from __future__ import annotations
import base64
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tarfile
import time
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
OPERATION = 'UNBOUND'
PROJECT = 'npd-agent-hub-prod'
SERVICE = 'agent-hub'
SUBJECT = 'opportunity:6a881aa4bb9606e32'
BASE_COMPOSE = Path('/opt/npd-ai-video-factory-releases/400899ba82501beeea469f4a33dc169a9a09bb8e/deploy/phase5/docker-compose.agent-hub.prod.yml')
BASE_COMPOSE_SHA = '789b126b2f02d23c978ca82f0944739eff93d82e23ef82a2b9c1ab5d5189cab8'
ENV_FILE = Path('/etc/npd-ai/agent-hub.env')
ENV_SHA = '86a95f5c613fbacf851d5a7a56a28225fb9a5b7c33945cd8919ecec230997d18'
CADDY_FILE = Path('/opt/n8n/Caddyfile')
CADDY_SHA = '1c16a2ccb2cbfd8e77977ff2d9e4b341602ca82fe130ef05c4c93a43efe7d545'
CADDY_CONTAINER = 'n8n-marketing-caddy-1'
MAIN_SHA = '43a1cca354d12893ee33b6e43cd9117794f78e04'
CANDIDATE_TAG = None
CANDIDATE_ARCHIVE_SHA = None
CANDIDATE_ARCHIVE_SIZE = None
CANDIDATE_OCI_INDEX = 'sha256:59019b49de03d16b7ab6d7aaf11ab2d9d28cd8d9b2900e64cbf753eb11f9c96a'
CANDIDATE_MANIFEST = 'sha256:9bc567c0f0b381f6cdc12bf7d4b73c6110d41d4fa5f354addda1a9818e61700b'
CANDIDATE_CONFIG = 'sha256:5f114c43c1ed18d71de18ed35956a8f56cf15c23f3c821d0514f94aa0e78c60e'
CANDIDATE_RUNTIME_IDS = {CANDIDATE_CONFIG, CANDIDATE_OCI_INDEX}
ROLLBACK_CONFIG = 'sha256:470810b2dbb2c525df971129b6bcf8cf31f4f2b7a4167721989a9bec01537041'
ROLLBACK_TAG = 'npd-agent-hub:phase5'
TOKEN_SHA = None
FRESH_BACKUP_MANIFEST_SHA = None
ROLLBACK_BUNDLE_MANIFEST_SHA = None
GOVERNANCE_HASH_FIELDS = ('owner_gate_sha256', 'payload_manifest_sha256', 'package_manifest_sha256', 'approval_file_sha256', 'approval_verbatim_sha256', 'runner_sha256', 'rollback_dispatcher_sha256', 'finalizer_sha256', 'remote_runtime_sha256', 'snapshot_sha256', 'counter_evidence_sha256', 'execution_scope_sha256', 'artifact_manifest_sha256', 'dispatcher_sha256', 'verifier_sha256', 'confirmation_contract_sha256', 'operation_bindings_sha256', 'execution_window_sha256')
BASELINE_TARGET_ID = '60116e3f6ebe9220d25a764531b4742ec57e99cdd08819284636e71735b68b64'
BASELINE_TARGET_SIGNATURE_SHA = '10231d87a7d1a7a50b4b8826e9fc542013ae3a5dc629538f0e684371244c9d2c'
BASELINE_PROTECTED_SHA = None
EXPECTED_ROLE_HASHES = {'owner': '5ab4dcd725f0c7d2c1b1382711b111ca006be117dbe067d2deb64ab866a283c5', 'operator': '757035455e2103f92f5594e59f3792aad0b4af84f6223b6123794982f1110f1c', 'viewer': 'b6961d1370893a87c2f575eb855d2ae062ea699def66c7543d99d5315c5a9d08'}
EXPECTED_STATIC_SUBJECT_HASHES = {role: hashlib.sha256(role.encode()).hexdigest() for role in EXPECTED_ROLE_HASHES}
NOT_BEFORE = None
LATEST_MUTATION = None
DECISION_DEADLINE = None
RECOVERY_DEADLINE = None
CLAIM_ROOT = Path('/var/lib/npd-ai/agent-hub-deployments/phase9-limited-pilot')
RECEIPT_ROOT = Path('/var/lib/npd-ai/agent-hub-deployments')
CLAIM_PATH = CLAIM_ROOT / 'operations' / (OPERATION + '.json')
ATTEMPT_DIR = CLAIM_ROOT / 'attempts' / OPERATION
STATE_PATH = ATTEMPT_DIR / 'state.json'
STAGE_PATH = ATTEMPT_DIR / 'candidate.oci.tar'
OVERRIDE_PATH = ATTEMPT_DIR / 'candidate-override.json'
ROLLBACK_OVERRIDE_PATH = ATTEMPT_DIR / 'rollback-override.json'
UPSERT = ['up', '-d', '--no-deps', '--no-build', '--pull', 'never', '--force-recreate', SERVICE]
RELEVANT_PATTERN = re.compile('agent|redis|caddy|n8n|espo|wordpress|salehub|people|(?:^|[-_])hr(?:[-_]|$)|api|worker|renderer', re.I)
SAFETY_COUNTERS = ('cohort_task_count', 'tool_execution_total', 'execution_audit_count', 'video_tool_execution_count', 'video_execution_audit_count', 'video_factory_job_count', 'video_factory_queue_count', 'video_factory_processing_count', 'video_factory_in_flight_count', 'planned_video_action_count', 'forbidden_context_count')
CANDIDATE_HEAD = None
SNAPSHOT_SHA = None
COUNTER_EVIDENCE_SHA = None
OWNER_EXCEPTION_SHA = None
BOUND_WINDOW_JSON = None
EXECUTION_WINDOW_SHA = None
COUNTER_OBSERVED_AT = None
INITIAL_DISPATCH_DEADLINE = None
LATEST_DISPATCHER_START = None

class GateStop(Exception):
    pass

def require(condition: object, reason: str) -> None:
    if not condition:
        raise GateStop(reason)

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def mutation_start_allowed(value):
    return NOT_BEFORE is not None and LATEST_MUTATION is not None and (NOT_BEFORE <= value < LATEST_MUTATION)

def recovery_allowed(value):
    return RECOVERY_DEADLINE is not None and value < RECOVERY_DEADLINE

def iso(value: datetime | None=None) -> str:
    return (value or utc_now()).isoformat().replace('+00:00', 'Z')

def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()

def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()

def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()

def digest(value: object) -> str:
    return sha_bytes(canonical(value))

def normalized(value: object) -> object:
    if isinstance(value, dict):
        return {key: normalized(item) for key, item in value.items()}
    if isinstance(value, list):
        items = [normalized(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True))
    return value

def run(args: list[str], *, data: bytes | None=None, env: dict[str, str] | None=None, timeout: int=30) -> bytes:
    try:
        result = subprocess.run(args, input=data, capture_output=True, env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise GateStop('COMMAND_TIMEOUT_' + '_'.join(args[:2]).upper()) from None
    if result.returncode:
        raise GateStop('COMMAND_FAILED_' + '_'.join(args[:2]).upper())
    return result.stdout

def protected_file(path: Path, expected_sha: str, exact_mode: int | None=None) -> bytes:
    metadata = path.lstat()
    require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == 0 and (not metadata.st_mode & 18), 'PROTECTED_FILE_METADATA_UNSAFE')
    if exact_mode is not None:
        require(stat.S_IMODE(metadata.st_mode) == exact_mode and metadata.st_gid == 0, 'PROTECTED_FILE_MODE_DRIFT')
    raw = path.read_bytes()
    require(sha_bytes(raw) == expected_sha, 'PROTECTED_FILE_SHA_DRIFT')
    return raw

def create_exclusive(path: Path, raw: bytes, mode: int=384) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), mode)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())

def replace_private(path: Path, value: object) -> None:
    pending = path.with_name(path.name + '.pending')
    require(not pending.exists(), 'STATE_PENDING_CONFLICT')
    create_exclusive(pending, json.dumps(value, indent=2, sort_keys=True).encode() + b'\n')
    os.replace(pending, path)
    if hasattr(os, 'O_DIRECTORY'):
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

def env_map(values: list[str]) -> dict[str, str]:
    output: dict[str, str] = {}
    for row in values:
        key, separator, value = row.partition('=')
        require(bool(separator) and key not in output, 'CONTAINER_ENV_INVALID')
        output[key] = value
    return output

def inspect_all() -> list[dict[str, object]]:
    identifiers = run(['docker', 'ps', '-q', '--no-trunc']).decode().split()
    require(bool(identifiers), 'NO_RUNNING_CONTAINERS')
    return json.loads(run(['docker', 'inspect', *identifiers], timeout=60))

def target(items: list[dict[str, object]]) -> dict[str, object]:
    matches = [item for item in items if (item.get('Config', {}).get('Labels') or {}).get('com.docker.compose.project') == PROJECT and (item.get('Config', {}).get('Labels') or {}).get('com.docker.compose.service') == SERVICE]
    require(len(matches) == 1, 'EXACTLY_ONE_TARGET_REQUIRED')
    return matches[0]

def sanitized_container(item: dict[str, object]) -> dict[str, object]:
    labels = item.get('Config', {}).get('Labels') or {}
    state = item.get('State') or {}
    mounts = [{'type': row.get('Type'), 'source': row.get('Source'), 'destination': row.get('Destination'), 'rw': row.get('RW')} for row in item.get('Mounts') or []]
    return {'name': str(item.get('Name', '')).lstrip('/'), 'id': item.get('Id'), 'image_id': item.get('Image'), 'compose_project': labels.get('com.docker.compose.project'), 'compose_service': labels.get('com.docker.compose.service'), 'status': state.get('Status'), 'running': state.get('Running'), 'health': (state.get('Health') or {}).get('Status'), 'restart_count': item.get('RestartCount'), 'networks': sorted((item.get('NetworkSettings', {}).get('Networks') or {}).keys()), 'ports': item.get('HostConfig', {}).get('PortBindings') or {}, 'mounts': mounts}

def container_signature(item: dict[str, object]) -> dict[str, object]:
    clean = sanitized_container(item)
    return {key: normalized(clean.get(key)) for key in ('compose_project', 'compose_service', 'id', 'image_id', 'mounts', 'name', 'networks', 'ports', 'restart_count', 'running', 'status', 'health')}

def protected_signature(items: list[dict[str, object]]) -> dict[str, object]:
    output = {}
    for item in items:
        labels = item.get('Config', {}).get('Labels') or {}
        if labels.get('com.docker.compose.project') == PROJECT and labels.get('com.docker.compose.service') == SERVICE:
            continue
        identity = ' '.join((str(item.get('Name', '')), str(labels.get('com.docker.compose.project', '')), str(labels.get('com.docker.compose.service', ''))))
        if RELEVANT_PATTERN.search(identity):
            clean = sanitized_container(item)
            output[clean['name']] = container_signature(item)
    return output

def topology(item: dict[str, object]) -> dict[str, object]:
    networks = {}
    identifier = str(item.get('Id', ''))
    for name, value in (item.get('NetworkSettings', {}).get('Networks') or {}).items():
        aliases = sorted((alias for alias in value.get('Aliases') or [] if alias not in (identifier, identifier[:12])))
        networks[name] = {'aliases': aliases, 'IPAMConfig': value.get('IPAMConfig')}
    return {'host_config': item.get('HostConfig'), 'mounts': sorted(item.get('Mounts') or [], key=lambda row: str(row.get('Destination'))), 'networks': networks}

def target_shape(item: dict[str, object]) -> dict[str, object]:
    config = copy.deepcopy(item.get('Config') or {})
    config.pop('Hostname', None)
    config.pop('Image', None)
    config['Env'] = env_map(config.get('Env') or [])
    labels = config.setdefault('Labels', {})
    config['Labels'] = {key: value for key, value in labels.items() if key.startswith('com.docker.compose.') and key not in {'com.docker.compose.config-hash', 'com.docker.compose.replace', 'com.docker.compose.project.config_files', 'com.docker.compose.image'}}
    return {'config': config, 'topology': topology(item)}

def public_identity(item: dict[str, object]) -> dict[str, object]:
    state = item.get('State') or {}
    return {'container_id': item.get('Id'), 'image_id': item.get('Image'), 'restart_count': item.get('RestartCount'), 'running': state.get('Running'), 'health': (state.get('Health') or {}).get('Status'), 'target_shape_sha256': digest(target_shape(item)), 'topology_sha256': digest(topology(item))}

def http_json(path: str, token: str | None=None) -> object:
    headers = {'Authorization': 'Bearer ' + token} if token else {}
    with urlopen(Request('http://127.0.0.1:8010' + path, headers=headers), timeout=8) as response:
        require(response.status == 200, 'HTTP_READ_FAILED')
        return json.loads(response.read(2000000))
SAFETY_PROBE = '\nimport hashlib,json\nfrom urllib.parse import urlsplit,urlunsplit\nfrom redis import Redis\nimport npd_agent_hub.auth as auth\nimport npd_agent_hub.config as config\nimport npd_agent_hub.maintenance as maintenance\np=json.load(__import__(\'sys\').stdin);s=config.HubSettings.from_env();a=auth.StaticTokenAuthorizer(s)\ndef text(v):return v.decode() if isinstance(v,bytes) else v\ndef dh(v):return hashlib.sha256(v.encode()).hexdigest()\ngroups={r:{e.strip().lower() for e in getattr(s,r+\'_emails\')} for r in (\'owner\',\'operator\',\'viewer\')}\nroles={}\nfor role,wanted in p[\'roles\'].items():\n matches={e for g in groups.values() for e in g if dh(e)==wanted}; memberships=sorted(r for r,g in groups.items() if matches&g)\n resolved=a.role_for_email(next(iter(matches))) if len(matches)==1 else None; actual=resolved.name.lower() if isinstance(resolved,auth.Role) else \'not_allowlisted\'\n roles[role]={\'actual_role\':actual,\'matching_allowlists\':memberships,\'match_count\':len(matches),\'matches_expected\':actual==role and memberships==[role]}\nc=maintenance._client();ns=s.store_namespace.strip(\':\');namespace_key_count=sum(1 for _ in c.scan_iter(match=ns+\':*\'));planned=forbidden=cohort=0\nfor key in c.scan_iter(match=ns+\':report:*\'):\n raw=c.get(key)\n if raw:\n  for report in (json.loads(text(raw)).get(\'reports\') or []):\n   planned+=sum(1 for action in (report.get(\'actions\') or []) if action.get(\'tool\')==\'video.jobs.create\')\nfor key in c.scan_iter(match=ns+\':task:*\'):\n raw=c.get(key)\n if raw:\n  task=json.loads(text(raw));ctx=json.dumps(task.get(\'context\') or {},sort_keys=True,separators=(\',\',\':\'))\n  forbidden+=int(any(x in ctx for x in (\'video_job\',\'render_request\',\'publish_request\',\'tool_execution\',\'external_action\')))\n  cohort+=int(p[\'subject\'] in ctx)\nexecutions=videoexec=0\nfor key in c.scan_iter(match=ns+\':executions:*\'):\n rows=c.lrange(key,0,-1);executions+=len(rows);videoexec+=sum(1 for row in rows if json.loads(text(row)).get(\'tool\')==\'video.jobs.create\')\naudit=c.lrange(ns+\':audit:global\',0,-1); exaudit=sum(1 for row in audit if json.loads(text(row)).get(\'event_type\') in (\'execution_started\',\'execution_succeeded\',\'execution_failed\')); vaudit=sum(1 for row in audit if \'video.jobs.create\' in text(row))\nkind,subject_id=p[\'subject\'].split(\':\',1);touchpoint_index=ns+\':attribution-os:\'+kind+\':\'+subject_id+\':touchpoints\';event_ids=c.zrange(touchpoint_index,0,-1);events=[]\nfor event_id in event_ids:\n raw=c.get(ns+\':attribution-os:touchpoint:\'+text(event_id))\n if raw:\n  event=json.loads(text(raw))\n  if event.get(kind+\'_id\')==subject_id:events.append(event)\njourney=\'anonymous\'\nfor event in events:\n evidence=(event.get(\'metadata\') or {}).get(\'journey_evidence\') or {}\n state=evidence.get(\'state\') if isinstance(evidence,dict) else None\n if state==\'negotiation\' or event.get(\'event_type\')==\'opportunity_stage_changed\':journey=\'negotiation\'\nreview_subject_hash=hashlib.sha256(p[\'subject\'].encode()).hexdigest()[:24]\nreview_count=int(c.zcard(ns+\':phase9-os:nba-review:subject:\'+review_subject_hash+\':reviews\'))\nLUA="local cursor=\'0\'\\nlocal seen={}\\nlocal keys={}\\nrepeat\\n  local page=redis.call(\'SCAN\',cursor,\'MATCH\',\'npd:video-job:*\',\'COUNT\',1000)\\n  cursor=page[1]\\n  for _,key in ipairs(page[2]) do\\n    if not seen[key] then seen[key]=true;table.insert(keys,key) end\\n  end\\nuntil cursor==\'0\'\\nlocal inflight=0\\nlocal terminal={awaiting_review=true,completed=true,failed=true,cancelled=true}\\nfor _,key in ipairs(keys) do\\n  local raw=redis.call(\'GET\',key)\\n  if raw then\\n    local ok,job=pcall(cjson.decode,raw)\\n    if not ok or type(job)~=\'table\' then\\n      inflight=inflight+1\\n    elseif not terminal[job.status] and not terminal[job.stage] then\\n      inflight=inflight+1\\n    end\\n  end\\nend\\nlocal queue=redis.call(\'LLEN\',\'npd:video-jobs:queue\')\\nlocal processing=redis.call(\'LLEN\',\'npd:video-jobs:processing\')\\nreturn {#keys,queue,processing,inflight}\\n"\nCOUNTER_IDS=[\'video_factory_job_count\', \'video_factory_queue_count\', \'video_factory_processing_count\', \'video_factory_in_flight_count\']\nfrom datetime import datetime,timezone\nimport hashlib,json,socket,ssl\nfrom urllib.parse import urlsplit,urlunsplit,unquote\nfrom npd_agent_hub.config import HubSettings\n\ndef resp(args):\n values=[str(arg).encode() for arg in args]\n return b\'*\'+str(len(values)).encode()+b\'\\r\\n\'+b\'\'.join(b\'$\'+str(len(v)).encode()+b\'\\r\\n\'+v+b\'\\r\\n\' for v in values)\ndef reply(reader):\n marker=reader.read(1);line=reader.readline()\n if not line.endswith(b\'\\r\\n\'):raise RuntimeError(\'RESP_TRUNCATED\')\n value=line[:-2]\n if marker==b\'+\':return value.decode()\n if marker==b\':\':return int(value)\n if marker==b\'-\':raise RuntimeError(\'READONLY_COUNTER_COMMAND_REJECTED\')\n if marker==b\'*\':\n  size=int(value)\n  if not 0<=size<=4:raise RuntimeError(\'RESP_ARRAY_INVALID\')\n  return [reply(reader) for _ in range(size)]\n raise RuntimeError(\'RESP_TYPE_INVALID\')\ns=HubSettings.from_env();u=urlsplit(s.agent_redis_url)\nif u.scheme not in (\'redis\',\'rediss\') or not u.hostname:raise RuntimeError(\'REDIS_REFERENCE_INVALID\')\ndb0=urlunsplit((u.scheme,u.netloc,\'/0\',u.query,u.fragment))\nconnection=socket.create_connection((u.hostname,u.port or 6379),timeout=20)\nif u.scheme==\'rediss\':connection=ssl.create_default_context().wrap_socket(connection,server_hostname=u.hostname)\nconnection.settimeout(30)\nreader=connection.makefile(\'rb\')\ntry:\n if u.password:\n  auth=[\'AUTH\',unquote(u.username),unquote(u.password)] if u.username else [\'AUTH\',unquote(u.password)]\n  connection.sendall(resp(auth))\n  if reply(reader)!=\'OK\':raise RuntimeError(\'AUTH_HANDSHAKE_FAILED\')\n connection.sendall(resp([\'EVAL_RO\',LUA,0]));values=reply(reader)\n if not isinstance(values,list) or len(values)!=4 or any(type(v) is not int or v<0 for v in values):raise RuntimeError(\'COUNTER_VALUES_INVALID\')\n jobs,q,processing,inflight=values\nfinally:\n reader.close();connection.close()\nc.close()\n\nprint(json.dumps({\'namespace\':ns,\'namespace_key_count\':namespace_key_count,\'store_backend\':s.store_backend,\'external_executor_configured\':bool(s.n8n_executor_webhook_url),\'configuration_valid\':not a.configuration_errors(),\'configuration_errors_count\':len(a.configuration_errors()),\'browser_login_enabled\':bool(a.browser_login_enabled),\'allowlist_counts\':{r:len(g) for r,g in groups.items()},\'allowlist_hashes\':{r:sorted(dh(e) for e in g) for r,g in groups.items()},\'roles\':roles,\'planned_video_action_count\':planned,\'forbidden_context_count\':forbidden,\'cohort_task_count\':cohort,\'cohort_journey_state\':journey,\'cohort_touchpoint_count\':len(events),\'cohort_review_count\':review_count,\'tool_execution_total\':executions,\'video_tool_execution_count\':videoexec,\'execution_audit_count\':exaudit,\'video_execution_audit_count\':vaudit,\'video_factory_job_count\':jobs,\'video_factory_queue_count\':q,\'video_factory_processing_count\':processing,\'video_factory_in_flight_count\':inflight,\'raw_values_emitted\':False},sort_keys=True))\n'

def safety(item: dict[str, object], *, allow_namespace_growth: bool=False) -> dict[str, object]:
    result = json.loads(run(['docker', 'exec', '-i', str(item['Id']), 'python', '-B', '-c', SAFETY_PROBE], data=json.dumps({'roles': EXPECTED_ROLE_HASHES, 'subject': SUBJECT}).encode(), timeout=120))
    expected_hashes = {role: [value] for role, value in EXPECTED_ROLE_HASHES.items()}
    require(result.get('namespace') == 'npd:agent-hub:v1' and result.get('store_backend') == 'redis', 'REDIS_NAMESPACE_OR_BACKEND_DRIFT')
    namespace_count = result.get('namespace_key_count')
    require(isinstance(namespace_count, int) and (not isinstance(namespace_count, bool)) and (namespace_count >= 10692 if allow_namespace_growth else namespace_count == 10692), 'FRESH_BACKUP_KEY_COUNT_DRIFT')
    require(result.get('configuration_valid') is True and result.get('configuration_errors_count') == 0, 'ROLE_CONFIGURATION_INVALID')
    require(result.get('browser_login_enabled') is True and result.get('external_executor_configured') is False, 'AUTH_OR_EXTERNAL_EXECUTOR_DRIFT')
    require(result.get('allowlist_counts') == {'owner': 1, 'operator': 1, 'viewer': 1}, 'ROLE_COUNT_DRIFT')
    require(result.get('allowlist_hashes') == expected_hashes and all((row.get('matches_expected') is True for row in result.get('roles', {}).values())), 'ROLE_IDENTITY_DRIFT')
    require(result.get('planned_video_action_count') == 0 and result.get('forbidden_context_count') == 0, 'FORBIDDEN_ACTION_CONTEXT_PRESENT')
    require(result.get('video_tool_execution_count') == 0 and result.get('video_execution_audit_count') == 0, 'VIDEO_TOOL_INVOCATION_PRESENT')
    require(result.get('video_factory_queue_count') == 0 and result.get('video_factory_processing_count') == 0 and (result.get('video_factory_in_flight_count') == 0), 'VIDEO_FACTORY_NOT_IDLE')
    require(result.get('cohort_journey_state') == 'negotiation' and result.get('cohort_touchpoint_count') == 1, 'COHORT_READ_MODEL_DRIFT')
    require(isinstance(result.get('cohort_review_count'), int), 'COHORT_REVIEW_COUNT_INVALID')
    require(result.get('raw_values_emitted') is False, 'SAFETY_PROBE_SANITIZATION_FAILED')
    return result

def verify_routes(item: dict[str, object], safety_result: dict[str, object]) -> dict[str, object]:
    state = item.get('State') or {}
    require(state.get('Running') is True and (state.get('Health') or {}).get('Status') == 'healthy', 'TARGET_CONTAINER_NOT_HEALTHY')
    require(item.get('RestartCount') == 0, 'TARGET_RESTART_COUNT_NONZERO')
    health = http_json('/health')
    ready = http_json('/readyz')
    require(health.get('status') == 'ok' and ready.get('status') == 'ready', 'HEALTH_OR_READYZ_FAILED')
    env = env_map(item.get('Config', {}).get('Env') or [])
    whoami = {}
    for role in ('owner', 'operator', 'viewer'):
        token = env.get('AGENT_' + role.upper() + '_TOKEN', '')
        require(bool(token), 'STATIC_ROLE_TOKEN_MISSING')
        payload = http_json('/api/v1/whoami', token)
        whoami[role] = payload.get('role') == role and sha_bytes(str(payload.get('subject', '')).strip().lower().encode()) == EXPECTED_STATIC_SUBJECT_HASHES[role]
    require(all(whoami.values()), 'STATIC_WHOAMI_ROLE_MISMATCH')
    capabilities = http_json('/api/v1/tools/capabilities', env['AGENT_VIEWER_TOKEN'])
    campaign = http_json('/api/v1/integrations/campaign/status', env['AGENT_VIEWER_TOKEN'])
    writes = [{'name': row.get('name'), 'mode': row.get('mode'), 'execution_state': row.get('execution_state'), 'requires_approval': row.get('requires_approval')} for row in capabilities if isinstance(row, dict) and row.get('mode') == 'write']
    video = [row for row in writes if row.get('name') == 'video.jobs.create']
    require(video == [{'name': 'video.jobs.create', 'mode': 'write', 'execution_state': 'enabled', 'requires_approval': False}], 'LEGACY_VIDEO_DESCRIPTOR_DRIFT')
    require(all((row.get('execution_state') == 'disabled' for row in writes if row.get('name') != 'video.jobs.create')), 'EXTERNAL_WRITE_CAPABILITY_ENABLED')
    providers = {'email', 'google_ads', 'meta_ads', 'web_landing', 'zalo_zbs'}
    require(set(campaign) == providers and all((isinstance(campaign[name], dict) and campaign[name].get('live_execution_enabled') is False for name in providers)), 'CAMPAIGN_LIVE_EXECUTION_ENABLED')
    if item.get('Image') == ROLLBACK_CONFIG:
        journey_state = safety_result['cohort_journey_state']
        review_count = safety_result['cohort_review_count']
        phase9_read_contract = 'DIRECT_REDIS_READONLY_ROLLBACK_ROUTE_404'
    else:
        journey = http_json('/api/v1/journeys/' + quote(SUBJECT, safe=''), env['AGENT_VIEWER_TOKEN'])
        review_summary = http_json('/api/v1/next-best-actions/reviews/sales/summary?' + urlencode({'subject_ref': SUBJECT}), env['AGENT_VIEWER_TOKEN'])
        require(journey.get('current_state') == 'negotiation', 'COHORT_JOURNEY_STATE_DRIFT')
        require(isinstance(review_summary.get('total_reviews'), int), 'COHORT_REVIEW_COUNT_INVALID')
        journey_state = journey['current_state']
        review_count = review_summary['total_reviews']
        phase9_read_contract = 'CANDIDATE_HTTP_ROUTES'
    return {'health': 'PASS', 'readyz': 'PASS', 'static_whoami': 'PASS_3_OF_3', 'write_capability_boundary': 'PASS', 'cohort_review_count': review_count, 'journey_state': journey_state, 'phase9_read_contract': phase9_read_contract}

def compose_context(item: dict[str, object], image_reference: str) -> tuple[list[str], dict[str, str], dict[str, object]]:
    labels = item.get('Config', {}).get('Labels') or {}
    config_paths = str(labels.get('com.docker.compose.project.config_files', '')).split(',')
    if item.get('Image') == ROLLBACK_CONFIG:
        allowed_paths = ([str(BASE_COMPOSE)], [str(BASE_COMPOSE), str(ROLLBACK_OVERRIDE_PATH)])
    elif item.get('Image') in CANDIDATE_RUNTIME_IDS:
        allowed_paths = ([str(BASE_COMPOSE), str(OVERRIDE_PATH)],)
    else:
        allowed_paths = ()
    require(config_paths in allowed_paths, 'COMPOSE_FILE_LABEL_DRIFT')
    require(Path(str(labels.get('com.docker.compose.project.working_dir', ''))).is_absolute(), 'COMPOSE_WORKDIR_INVALID')
    protected_file(BASE_COMPOSE, BASE_COMPOSE_SHA)
    env = env_map(item.get('Config', {}).get('Env') or [])
    mounts = {row.get('Destination'): row for row in item.get('Mounts') or []}
    require(set(mounts) == {'/run/secrets/ga4-service-account.json', '/run/secrets/agent-attribution-verification-keys.json'}, 'SECRET_MOUNT_SET_DRIFT')
    require(all((row.get('Type') == 'bind' and row.get('RW') is False and (row.get('Source') != '/dev/null') for row in mounts.values())), 'SECRET_MOUNT_CONFIGURATION_DRIFT')
    require(set(item.get('NetworkSettings', {}).get('Networks') or {}) == {'npd-ai-video-factory_default', 'n8n-marketing_n8n_net'}, 'NETWORK_SET_DRIFT')
    require(item.get('HostConfig', {}).get('PortBindings') == {'8010/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '8010'}]}, 'PORT_BINDING_DRIFT')
    launch = {'PATH': os.environ['PATH'], 'HOME': '/root', 'AGENT_HUB_IMAGE': image_reference, 'AGENT_HUB_ENV_FILE': str(ENV_FILE), 'AGENT_HUB_PORT': '8010', 'VIDEO_API_URL': env['VIDEO_API_URL'], 'AGENT_REDIS_URL': env['AGENT_REDIS_URL'], 'AGENT_STORE_NAMESPACE': env['AGENT_STORE_NAMESPACE'], 'GA4_SERVICE_ACCOUNT_HOST_FILE': str(mounts['/run/secrets/ga4-service-account.json']['Source']), 'AGENT_ATTRIBUTION_VERIFICATION_KEYS_HOST_FILE': str(mounts['/run/secrets/agent-attribution-verification-keys.json']['Source']), 'NPD_DOCKER_NETWORK': 'npd-ai-video-factory_default', 'N8N_DOCKER_NETWORK': 'n8n-marketing_n8n_net'}
    command = ['docker', 'compose', '--project-directory', str(labels['com.docker.compose.project.working_dir']), '--project-name', PROJECT, '--file', str(BASE_COMPOSE)]
    base = json.loads(run(command + ['config', '--format', 'json'], env={**launch, 'AGENT_HUB_IMAGE': str(item.get('Config', {}).get('Image'))}))
    require(set(base.get('services', {})) == {SERVICE}, 'BASE_COMPOSE_TARGET_SET_DRIFT')
    return (command, launch, base)

def verify_baseline(*, exact_container: bool) -> dict[str, object]:
    protected_file(ENV_FILE, ENV_SHA, 384)
    protected_file(CADDY_FILE, CADDY_SHA)
    run(['docker', 'exec', CADDY_CONTAINER, 'caddy', 'validate', '--config', '/etc/caddy/Caddyfile'], timeout=30)
    require(run(['docker', 'compose', 'version', '--short']).decode().strip() == '2.35.1', 'COMPOSE_VERSION_DRIFT')
    items = inspect_all()
    current = target(items)
    if exact_container:
        require(current.get('Id') == BASELINE_TARGET_ID and current.get('Image') == ROLLBACK_CONFIG, 'TARGET_BASELINE_DRIFT')
        require(current.get('Config', {}).get('Image') == ROLLBACK_TAG, 'TARGET_ROLLBACK_TAG_DRIFT')
        require(digest(container_signature(current)) == BASELINE_TARGET_SIGNATURE_SHA, 'TARGET_BASELINE_SIGNATURE_DRIFT')
    require(len(protected_signature(items)) == 18 and digest(protected_signature(items)) == BASELINE_PROTECTED_SHA, 'PROTECTED_SERVICE_DRIFT')
    safety_result = safety(current)
    routes = verify_routes(current, safety_result)
    command, launch, rendered = compose_context(current, str(current.get('Config', {}).get('Image')))
    require(rendered['services'][SERVICE].get('image') == current.get('Config', {}).get('Image'), 'RENDERED_IMAGE_NOT_CURRENT')
    return {'items': items, 'target': current, 'routes': routes, 'safety': safety_result, 'command': command, 'launch': launch, 'rendered': rendered}

def inspect_oci_archive(path: Path) -> dict[str, object]:
    require(path.stat().st_size == CANDIDATE_ARCHIVE_SIZE and sha_file(path) == CANDIDATE_ARCHIVE_SHA, 'CANDIDATE_ARCHIVE_HASH_OR_SIZE_MISMATCH')
    with tarfile.open(path, 'r') as archive:
        index_raw = archive.extractfile('index.json').read()
        index = json.loads(index_raw)
        require(len(index.get('manifests') or []) == 1 and index['manifests'][0].get('digest') == CANDIDATE_OCI_INDEX, 'OCI_INDEX_BINDING_MISMATCH')
        index_blob_name = 'blobs/sha256/' + CANDIDATE_OCI_INDEX.split(':', 1)[1]
        index_blob = archive.extractfile(index_blob_name).read()
        require(sha_bytes(index_blob) == CANDIDATE_OCI_INDEX.split(':', 1)[1], 'OCI_INDEX_BLOB_HASH_MISMATCH')
        platform_index = json.loads(index_blob)
        matching = [row for row in platform_index.get('manifests') or [] if row.get('platform') == {'architecture': 'amd64', 'os': 'linux'}]
        require(len(matching) == 1 and matching[0].get('digest') == CANDIDATE_MANIFEST, 'OCI_PLATFORM_MANIFEST_MISMATCH')
        manifest_blob = archive.extractfile('blobs/sha256/' + CANDIDATE_MANIFEST.split(':', 1)[1]).read()
        require(sha_bytes(manifest_blob) == CANDIDATE_MANIFEST.split(':', 1)[1], 'OCI_MANIFEST_HASH_MISMATCH')
        manifest = json.loads(manifest_blob)
        require(manifest.get('config', {}).get('digest') == CANDIDATE_CONFIG, 'OCI_CONFIG_BINDING_MISMATCH')
        config_blob = archive.extractfile('blobs/sha256/' + CANDIDATE_CONFIG.split(':', 1)[1]).read()
        require(sha_bytes(config_blob) == CANDIDATE_CONFIG.split(':', 1)[1], 'OCI_CONFIG_HASH_MISMATCH')
        config = json.loads(config_blob)
        labels = config.get('config', {}).get('Labels') or {}
        require(config.get('architecture') == 'amd64' and config.get('os') == 'linux', 'OCI_PLATFORM_CONFIG_MISMATCH')
        require(labels.get('org.opencontainers.image.revision') == MAIN_SHA, 'OCI_SOURCE_REVISION_MISMATCH')
    return {'archive_sha256': CANDIDATE_ARCHIVE_SHA, 'oci_index': CANDIDATE_OCI_INDEX, 'manifest': CANDIDATE_MANIFEST, 'config': CANDIDATE_CONFIG, 'platform': 'linux/amd64'}

def validate_oci_archive(path: Path) -> dict[str, object]:
    metadata = path.lstat()
    require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == 0 and (not metadata.st_mode & 18), 'CANDIDATE_STAGE_METADATA_UNSAFE')
    return inspect_oci_archive(path)

def parse_envelope(value, *, require_preflight=True):
    try:
        envelope = json.loads(base64.urlsafe_b64decode(value.encode()))
    except Exception:
        raise GateStop('AUTHORIZATION_ENVELOPE_INVALID') from None
    require(OPERATION != 'UNBOUND' and envelope.get('schema') == 'npd.phase9.limited-pilot-rca05.dispatch.v1', 'FRESH_PROFILE_UNBOUND_OR_SCHEMA_INVALID')
    require(envelope.get('operation_id') == OPERATION, 'AUTHORIZATION_OPERATION_MISMATCH')
    require(re.fullmatch('[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}', str(envelope.get('invocation_id', ''))) is not None, 'INVOCATION_ID_INVALID')
    expected = {'confirmation_token_sha256': TOKEN_SHA, 'fresh_backup_manifest_sha256': FRESH_BACKUP_MANIFEST_SHA, 'rollback_bundle_manifest_sha256': ROLLBACK_BUNDLE_MANIFEST_SHA, 'main_sha': MAIN_SHA, 'candidate_head': CANDIDATE_HEAD, 'snapshot_sha256': SNAPSHOT_SHA, 'counter_evidence_sha256': COUNTER_EVIDENCE_SHA, 'protected_services_sha256': BASELINE_PROTECTED_SHA, 'owner_exception_receipt_sha256': OWNER_EXCEPTION_SHA}
    require(all((isinstance(wanted, str) and envelope.get(key) == wanted for key, wanted in expected.items())), 'AUTHORIZATION_BINDING_MISMATCH')
    require(EXECUTION_WINDOW_SHA is not None and envelope.get('execution_window_sha256') == EXECUTION_WINDOW_SHA, 'EXECUTION_WINDOW_HASH_MISMATCH')
    require(all((re.fullmatch('[0-9a-f]{64}', str(envelope.get(key, ''))) for key in GOVERNANCE_HASH_FIELDS)), 'GOVERNANCE_HASH_INVALID')
    if require_preflight:
        require(envelope.get('fresh_explicit_owner_execution_approval') is True and envelope.get('execution_approval') == 'APPROVED', 'OWNER_EXECUTION_APPROVAL_NOT_GRANTED')
        require(envelope.get('scope') == 'AGENT_HUB_ONLY_NO_PROVIDER_NO_VIDEO_FACTORY_EXECUTION', 'EXECUTION_SCOPE_INVALID')
        window = envelope.get('window')
        require(BOUND_WINDOW_JSON is not None and window == json.loads(BOUND_WINDOW_JSON), 'EXECUTION_WINDOW_PACKAGE_MISMATCH')
        require(isinstance(window, dict) and set(window) == {'start_utc', 'latest_mutation_utc', 'decision_deadline_utc', 'recovery_deadline_utc'}, 'FRESH_EXECUTION_WINDOW_UNBOUND')
        try:
            times = [datetime.fromisoformat(window[key].replace('Z', '+00:00')) for key in ('start_utc', 'latest_mutation_utc', 'decision_deadline_utc', 'recovery_deadline_utc')]
            require(all((t.utcoffset() == timezone.utc.utcoffset(t) for t in times)) and times[0] < times[1] < times[2] < times[3], 'FRESH_EXECUTION_WINDOW_INVALID')
        except (ValueError, TypeError, AttributeError):
            raise GateStop('FRESH_EXECUTION_WINDOW_INVALID') from None
        global NOT_BEFORE, LATEST_MUTATION, DECISION_DEADLINE, RECOVERY_DEADLINE
        NOT_BEFORE, LATEST_MUTATION, DECISION_DEADLINE, RECOVERY_DEADLINE = times
        require(envelope.get('final_readonly_preflight_status') == 'PASS' and re.fullmatch('[0-9a-f]{64}', str(envelope.get('final_readonly_preflight_sha256', ''))), 'FINAL_READONLY_PREFLIGHT_NOT_PASS')
    else:
        require(envelope.get('preflight_readonly') is True, 'READONLY_PREFLIGHT_REQUIRED')
    return envelope

def read_claim(invocation_id: str, envelope: dict[str, object] | None=None) -> dict[str, object]:
    require(CLAIM_PATH.is_file() and (not CLAIM_PATH.is_symlink()), 'CLAIM_MISSING_OR_UNSAFE')
    claim = json.loads(CLAIM_PATH.read_text())
    require(claim.get('operation_id') == OPERATION and claim.get('invocation_id') == invocation_id and (claim.get('claim_id') == invocation_id), 'CLAIM_OWNERSHIP_MISMATCH')
    require(claim.get('status') == 'CLAIMED' and claim.get('reset_for_retry_allowed') is False, 'CLAIM_STATUS_INVALID')
    require(claim.get('candidate_config') == CANDIDATE_CONFIG and claim.get('rollback_config') == ROLLBACK_CONFIG, 'CLAIM_BINDING_MISMATCH')
    if envelope is not None:
        require(all((claim.get(key) == envelope.get(key) for key in GOVERNANCE_HASH_FIELDS)), 'CLAIM_GOVERNANCE_BINDING_MISMATCH')
    return claim

def read_state(invocation_id: str) -> dict[str, object]:
    require(STATE_PATH.is_file() and (not STATE_PATH.is_symlink()), 'OPERATION_STATE_MISSING_OR_UNSAFE')
    state = json.loads(STATE_PATH.read_text())
    require(state.get('operation_id') == OPERATION and state.get('invocation_id') == invocation_id, 'OPERATION_STATE_OWNERSHIP_MISMATCH')
    return state

def prepare_claim_parents() -> None:
    require(RECEIPT_ROOT.is_dir() and (not RECEIPT_ROOT.is_symlink()), 'RECEIPT_ROOT_MISSING_OR_UNSAFE')
    metadata = RECEIPT_ROOT.lstat()
    require(metadata.st_uid == 0 and metadata.st_gid == 0 and (stat.S_IMODE(metadata.st_mode) == 448), 'RECEIPT_ROOT_PERMISSIONS_DRIFT')
    for path in (CLAIM_ROOT, CLAIM_PATH.parent, ATTEMPT_DIR.parent):
        path.mkdir(mode=448, exist_ok=True)
        current = path.lstat()
        require(stat.S_ISDIR(current.st_mode) and current.st_uid == 0 and (current.st_gid == 0) and (not current.st_mode & 18) and (not path.is_symlink()), 'CLAIM_DIRECTORY_UNSAFE')

def command_context(before: dict[str, object], override: Path, image_ref: str) -> tuple[list[str], dict[str, str], dict[str, object]]:
    command, launch, rendered = compose_context(before, image_ref)
    merged_command = command + ['--file', str(override)]
    candidate_model = json.loads(run(merged_command + ['config', '--format', 'json'], env=launch))
    expected = copy.deepcopy(rendered)
    expected['services'][SERVICE]['image'] = image_ref
    require(candidate_model == expected, 'IMAGE_ONLY_COMPOSE_DELTA_FAILED')
    run(merged_command + ['--dry-run', *UPSERT], env=launch, timeout=60)
    return (merged_command, launch, candidate_model)

def wait_ready(timeout_seconds: int) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    last: dict[str, object] | None = None
    while time.monotonic() < deadline:
        items = inspect_all()
        current = target(items)
        last = current
        state = current.get('State') or {}
        if state.get('Running') is True and (state.get('Health') or {}).get('Status') == 'healthy':
            return current
        time.sleep(2)
    raise GateStop('TARGET_HEALTH_TIMEOUT' if last is not None else 'TARGET_UNOBSERVABLE')

def verify_after(before_shape_sha256: str, expected_image: str, *, allow_namespace_growth: bool=False) -> dict[str, object]:
    protected_file(ENV_FILE, ENV_SHA, 384)
    protected_file(BASE_COMPOSE, BASE_COMPOSE_SHA)
    protected_file(CADDY_FILE, CADDY_SHA)
    run(['docker', 'exec', CADDY_CONTAINER, 'caddy', 'validate', '--config', '/etc/caddy/Caddyfile'], timeout=30)
    current = wait_ready(180)
    require(current.get('Image') == expected_image, 'TARGET_IMAGE_NOT_EXPECTED')
    require(digest(target_shape(current)) == before_shape_sha256, 'TARGET_NON_IMAGE_CONFIGURATION_DRIFT')
    current_items = inspect_all()
    require(len(protected_signature(current_items)) == 18 and digest(protected_signature(current_items)) == BASELINE_PROTECTED_SHA, 'PROTECTED_SERVICE_DRIFT_AFTER_MUTATION')
    safety_result = safety(current, allow_namespace_growth=allow_namespace_growth)
    routes = verify_routes(current, safety_result)
    return {'target': public_identity(current), 'routes': routes, 'safety': safety_result, 'protected_services_unchanged': True}

def verify_no_write_delta(before_safety: dict[str, object], before_routes: dict[str, object], after: dict[str, object]) -> None:
    require(all((after['safety'].get(name) == before_safety.get(name) for name in SAFETY_COUNTERS)), 'WRITE_OR_EXTERNAL_COUNTER_CHANGED_DURING_DEPLOYMENT')
    require(after['routes'].get('cohort_review_count') == before_routes.get('cohort_review_count'), 'REVIEW_COUNT_CHANGED_DURING_DEPLOYMENT')

def uat_detail(container: dict[str, object], task_id: str, review_id: str) -> dict[str, object]:
    require(re.fullmatch('agt_[0-9a-f]{16}', task_id) is not None, 'UAT_TASK_ID_INVALID')
    require(re.fullmatch('nbar_[0-9a-f]{24}', review_id) is not None, 'UAT_REVIEW_ID_INVALID')
    env = env_map(container.get('Config', {}).get('Env') or [])
    token = env.get('AGENT_VIEWER_TOKEN', '')
    require(bool(token), 'STATIC_VIEWER_TOKEN_MISSING')
    report = http_json('/api/v1/agent-tasks/' + quote(task_id, safe=''), token)
    reviews = http_json('/api/v1/next-best-actions/reviews/sales?' + urlencode({'subject_ref': SUBJECT, 'limit': 1000}), token)
    summary = http_json('/api/v1/next-best-actions/reviews/sales/summary?' + urlencode({'subject_ref': SUBJECT}), token)
    journey = http_json('/api/v1/journeys/' + quote(SUBJECT, safe=''), token)
    require(isinstance(report, dict) and isinstance(reviews, list), 'UAT_READ_MODEL_INVALID')
    matches = [row for row in reviews if isinstance(row, dict) and row.get('review_id') == review_id]
    require(len(matches) == 1, 'UAT_REVIEW_NOT_UNIQUE')
    review = matches[0]
    answer = report.get('answer') or {}
    items = answer.get('items') or []
    require(len(items) == 1 and isinstance(items[0], dict), 'UAT_REPORT_ITEM_COUNT_INVALID')
    report_item = items[0]
    details = report_item.get('details') or {}
    metrics = answer.get('metrics') or {}
    allowed_details = ('evaluation_status', 'journey_state', 'lead_score', 'recommendation_version', 'recommended_action_code', 'confidence', 'first_response_sla', 'visit_booking_sla', 'completeness_proof_status', 'completeness_verified', 'source_complete', 'internal_review_minutes', 'missing_inputs', 'shadow_mode', 'execution_enabled', 'customer_contact_enabled')
    return {'schema': 'npd.phase9.limited-pilot-rca05.uat-api-detail.v1', 'operation_id': OPERATION, 'captured_at_utc': iso(), 'task_id': report.get('task_id'), 'review_id': review.get('review_id'), 'subject_ref_sha256': sha_bytes(SUBJECT.encode()), 'target': public_identity(container), 'report': {'selected_agents': report.get('selected_agents'), 'report_agents': [row.get('agent') for row in report.get('reports') or [] if isinstance(row, dict)], 'report_action_count': sum((len(row.get('actions') or []) for row in report.get('reports') or [] if isinstance(row, dict))), 'approval_count': len(report.get('approvals_required') or []), 'answer_status': answer.get('status'), 'workflow_version': metrics.get('workflow_version'), 'metrics': {key: metrics.get(key) for key in ('requested_cases', 'unique_subjects', 'duplicate_cases', 'evaluated_subjects', 'failed_subjects', 'missing_context_subjects', 'verified_sla_subjects', 'verified_breach_subjects', 'high_priority_reviews', 'shadow_mode', 'external_writes_enabled', 'customer_contact_enabled', 'execution_enabled')}, 'item': {'entity_id_sha256': sha_bytes(str(report_item.get('entity_id', '')).encode()), 'priority': report_item.get('priority'), 'reason_present': bool(report_item.get('reason')), 'recommended_action_present': bool(report_item.get('recommended_action')), 'details': {key: details.get(key) for key in allowed_details}}}, 'review': {key: review.get(key) for key in ('recommendation_version', 'journey_state', 'lead_score', 'disposition', 'false_positive', 'reviewer_role', 'reviewed_at', 'shadow_mode', 'recommendation_executed', 'execution_enabled', 'external_writes_enabled', 'customer_contact_enabled', 'contains_raw_pii')}, 'summary': {key: summary.get(key) for key in ('total_reviews', 'relevant', 'not_relevant', 'needs_more_context', 'shadow_mode', 'execution_enabled', 'customer_contact_enabled')}, 'journey_state': journey.get('current_state'), 'production_mutation': False, 'business_system_write': False, 'raw_customer_payload_or_pii_emitted': False}

def do_rollback(state: dict[str, object], reason: str) -> dict[str, object]:
    require(state.get('target_mutation_attempted') is True, 'ROLLBACK_WITHOUT_TARGET_MUTATION_FORBIDDEN')
    require(recovery_allowed(utc_now()), 'RECOVERY_DEADLINE_EXCEEDED')
    current_items = inspect_all()
    current = target(current_items)
    rollback_ref = str(state.get('rollback_image_reference', ''))
    require(bool(rollback_ref), 'ROLLBACK_IMAGE_REFERENCE_MISSING')
    image = json.loads(run(['docker', 'image', 'inspect', rollback_ref], timeout=30))[0]
    require(image.get('Id') == ROLLBACK_CONFIG, 'ROLLBACK_IMAGE_REFERENCE_DRIFT')
    raw = json.dumps({'services': {SERVICE: {'image': rollback_ref}}}, separators=(',', ':')).encode()
    if not ROLLBACK_OVERRIDE_PATH.exists():
        create_exclusive(ROLLBACK_OVERRIDE_PATH, raw)
    else:
        require(ROLLBACK_OVERRIDE_PATH.read_bytes() == raw, 'ROLLBACK_OVERRIDE_CONFLICT')
    command, launch, _ = command_context(current, ROLLBACK_OVERRIDE_PATH, rollback_ref)
    state['rollback_started_at'] = iso()
    state['rollback_reason'] = reason
    state['status'] = 'ROLLBACK_IN_PROGRESS'
    replace_private(STATE_PATH, state)
    run(command + UPSERT, env=launch, timeout=600)
    verification = verify_after(str(state['before_target_shape_sha256']), ROLLBACK_CONFIG)
    require(recovery_allowed(utc_now()), 'RECOVERY_VERIFICATION_AFTER_DEADLINE')
    state['status'] = 'ROLLED_BACK_VERIFIED'
    state['rollback_verified_at'] = iso()
    state['rollback_verification'] = verification
    replace_private(STATE_PATH, state)
    return {'status': 'ROLLED_BACK_VERIFIED', 'rollback_verified_at': state['rollback_verified_at'], 'target': verification['target'], 'protected_services_unchanged': True}

def preflight(envelope: dict[str, object]) -> dict[str, object]:
    require(not CLAIM_PATH.exists() and (not ATTEMPT_DIR.exists()), 'OPERATION_ALREADY_CLAIMED_OR_ATTEMPTED')
    baseline = verify_baseline(exact_container=True)
    require(not CLAIM_PATH.exists() and (not ATTEMPT_DIR.exists()), 'OPERATION_RACED_DURING_PREFLIGHT')
    return {'status': 'PASS', 'checked_at': iso(), 'target': public_identity(baseline['target']), 'protected_services_sha256': BASELINE_PROTECTED_SHA, 'routes': baseline['routes'], 'safety_counters': {name: baseline['safety'].get(name) for name in SAFETY_COUNTERS}, 'claim_absent': True, 'candidate_staged': False, 'production_mutation': False, 'business_system_write': False, 'candidate_head': CANDIDATE_HEAD, 'snapshot_sha256': SNAPSHOT_SHA, 'counter_evidence_sha256': COUNTER_EVIDENCE_SHA, 'package_manifest_sha256': envelope['package_manifest_sha256']}

def claim(envelope: dict[str, object]) -> dict[str, object]:
    now = utc_now()
    require(mutation_start_allowed(now), 'CLAIM_OUTSIDE_MUTATION_START_WINDOW')
    require(INITIAL_DISPATCH_DEADLINE is not None and now < datetime.fromisoformat(INITIAL_DISPATCH_DEADLINE), 'INITIAL_COUNTER_RECEIPT_EXPIRED')
    require(not CLAIM_PATH.exists() and (not ATTEMPT_DIR.exists()), 'OPERATION_ALREADY_CLAIMED_OR_ATTEMPTED')
    baseline = verify_baseline(exact_container=True)
    prepare_claim_parents()
    require(mutation_start_allowed(utc_now()), 'CLAIM_WINDOW_EXCEEDED_DURING_PREFLIGHT')
    require(utc_now() < datetime.fromisoformat(INITIAL_DISPATCH_DEADLINE), 'INITIAL_COUNTER_RECEIPT_EXPIRED_DURING_PREFLIGHT')
    require(not CLAIM_PATH.exists() and (not ATTEMPT_DIR.exists()), 'OPERATION_RACED_BEFORE_CLAIM')
    claim_id = str(envelope['invocation_id'])
    claim_value = {'schema': 'npd.phase9.limited-pilot-rca05.operation-claim.v1', 'status': 'CLAIMED', 'operation_id': OPERATION, 'claim_id': claim_id, 'invocation_id': claim_id, 'operator': 'Codex', 'claimed_at': iso(now), 'target': PROJECT + '/' + SERVICE, 'owner_gate_sha256': envelope['owner_gate_sha256'], 'payload_manifest_sha256': envelope['payload_manifest_sha256'], 'package_manifest_sha256': envelope['package_manifest_sha256'], 'approval_file_sha256': envelope['approval_file_sha256'], 'approval_verbatim_sha256': envelope['approval_verbatim_sha256'], 'runner_sha256': envelope['runner_sha256'], 'rollback_dispatcher_sha256': envelope['rollback_dispatcher_sha256'], 'finalizer_sha256': envelope['finalizer_sha256'], 'remote_runtime_sha256': envelope['remote_runtime_sha256'], 'confirmation_token_sha256': TOKEN_SHA, 'fresh_backup_manifest_sha256': FRESH_BACKUP_MANIFEST_SHA, 'rollback_bundle_manifest_sha256': ROLLBACK_BUNDLE_MANIFEST_SHA, 'main_sha': MAIN_SHA, 'candidate_manifest': CANDIDATE_MANIFEST, 'candidate_config': CANDIDATE_CONFIG, 'candidate_archive_sha256': CANDIDATE_ARCHIVE_SHA, 'rollback_config': ROLLBACK_CONFIG, 'cohort': SUBJECT, 'final_readonly_preflight_sha256': envelope['final_readonly_preflight_sha256'], 'plaintext_credential_present': False, 'reset_for_retry_allowed': False, 'snapshot_sha256': envelope['snapshot_sha256'], 'counter_evidence_sha256': envelope['counter_evidence_sha256'], 'execution_scope_sha256': envelope['execution_scope_sha256'], 'artifact_manifest_sha256': envelope['artifact_manifest_sha256'], 'dispatcher_sha256': envelope['dispatcher_sha256'], 'verifier_sha256': envelope['verifier_sha256'], 'confirmation_contract_sha256': envelope['confirmation_contract_sha256'], 'operation_bindings_sha256': envelope['operation_bindings_sha256']}
    claim_value['execution_window_sha256'] = envelope['execution_window_sha256']
    claim_value['window'] = envelope['window']
    create_exclusive(CLAIM_PATH, json.dumps(claim_value, indent=2, sort_keys=True).encode() + b'\n')
    require(read_claim(claim_id, envelope) == claim_value, 'CLAIM_READBACK_MISMATCH')
    ATTEMPT_DIR.mkdir(mode=448)
    state = {'schema': 'npd.phase9.limited-pilot-fresh.runtime-state.v1', 'operation_id': OPERATION, 'invocation_id': claim_id, 'status': 'CLAIMED', 'claimed_at': claim_value['claimed_at'], 'before': public_identity(baseline['target']), 'before_target_shape_sha256': digest(target_shape(baseline['target'])), 'baseline_safety_counters': {name: baseline['safety'].get(name) for name in SAFETY_COUNTERS}, 'baseline_cohort_review_count': baseline['routes'].get('cohort_review_count'), 'baseline_namespace_key_count': baseline['safety'].get('namespace_key_count'), 'protected_services_sha256': BASELINE_PROTECTED_SHA, 'rollback_image_reference': baseline['target'].get('Config', {}).get('Image'), 'target_mutation_attempted': False, 'candidate_deployment_retry_allowed': False}
    replace_private(STATE_PATH, state)
    return {'status': 'CLAIMED', 'claim_id': claim_id, 'claimed_at': claim_value['claimed_at'], 'stage_path': str(STAGE_PATH), 'before': state['before']}

def deploy(envelope: dict[str, object]) -> dict[str, object]:
    invocation_id = str(envelope['invocation_id'])
    read_claim(invocation_id, envelope)
    state = read_state(invocation_id)
    require(state.get('status') == 'CLAIMED' and state.get('target_mutation_attempted') is False, 'DEPLOYMENT_STATE_NOT_CLAIMED')
    require(mutation_start_allowed(utc_now()), 'DEPLOYMENT_START_WINDOW_EXCEEDED')
    baseline = verify_baseline(exact_container=True)
    require(public_identity(baseline['target']) == state.get('before'), 'TARGET_DRIFT_SINCE_CLAIM')
    oci = validate_oci_archive(STAGE_PATH)
    existing = subprocess.run(['docker', 'image', 'inspect', CANDIDATE_TAG], capture_output=True, timeout=30)
    if existing.returncode == 0:
        require(json.loads(existing.stdout)[0].get('Id') in CANDIDATE_RUNTIME_IDS, 'PREEXISTING_CANDIDATE_TAG_DRIFT')
    run(['docker', 'image', 'load', '--input', str(STAGE_PATH)], timeout=600)
    loaded = json.loads(run(['docker', 'image', 'inspect', CANDIDATE_TAG], timeout=30))[0]
    server_platform = run(['docker', 'version', '--format', '{{.Server.Os}}/{{.Server.Arch}}'], timeout=30).decode().strip()
    require(loaded.get('Id') in CANDIDATE_RUNTIME_IDS and server_platform == 'linux/amd64' and (loaded.get('Architecture') in (None, '', 'amd64')) and (loaded.get('Os') in (None, '', 'linux')), 'LOADED_CANDIDATE_ID_OR_PLATFORM_MISMATCH')
    labels = loaded.get('Config', {}).get('Labels') or {}
    require(labels.get('org.opencontainers.image.revision') == MAIN_SHA, 'LOADED_CANDIDATE_SOURCE_MISMATCH')
    raw_override = json.dumps({'services': {SERVICE: {'image': CANDIDATE_TAG}}}, separators=(',', ':')).encode()
    create_exclusive(OVERRIDE_PATH, raw_override)
    command, launch, _ = command_context(baseline['target'], OVERRIDE_PATH, CANDIDATE_TAG)
    require(utc_now() < LATEST_MUTATION, 'LATEST_TARGET_MUTATION_START_EXCEEDED')
    final_baseline = verify_baseline(exact_container=True)
    require(public_identity(final_baseline['target']) == state.get('before'), 'TARGET_DRIFT_IMMEDIATELY_BEFORE_MUTATION')
    state['oci_verification'] = oci
    state['candidate_loaded_at'] = iso()
    state['target_mutation_attempted'] = True
    state['target_mutation_started_at'] = iso()
    state['status'] = 'TARGET_MUTATION_IN_PROGRESS'
    replace_private(STATE_PATH, state)
    try:
        run(command + UPSERT, env=launch, timeout=600)
        verification = verify_after(str(state['before_target_shape_sha256']), str(loaded['Id']))
        verify_no_write_delta(baseline['safety'], baseline['routes'], verification)
        require(utc_now() < DECISION_DEADLINE, 'POST_DEPLOY_VERIFICATION_AFTER_DECISION_DEADLINE')
        state['status'] = 'DEPLOYED_VERIFIED_UAT_PENDING'
        state['health_verified_at'] = iso()
        state['deployment_verification'] = verification
        replace_private(STATE_PATH, state)
        return {'status': state['status'], 'target_mutation_started_at': state['target_mutation_started_at'], 'health_verified_at': state['health_verified_at'], 'before': state['before'], 'after': verification['target'], 'loaded_runtime_image_id': loaded['Id'], 'verified_oci_config': CANDIDATE_CONFIG, 'verified_linux_amd64_manifest': CANDIDATE_MANIFEST, 'baseline_safety_counters': state['baseline_safety_counters'], 'baseline_cohort_review_count': state['baseline_cohort_review_count'], 'baseline_namespace_key_count': state['baseline_namespace_key_count'], 'postdeploy_safety_counters': {name: verification['safety'].get(name) for name in SAFETY_COUNTERS}, 'postdeploy_cohort_review_count': verification['routes'].get('cohort_review_count'), 'postdeploy_namespace_key_count': verification['safety'].get('namespace_key_count'), 'protected_services_unchanged': True}
    except Exception as error:
        reason = str(error) if isinstance(error, GateStop) else 'REDACTED_' + type(error).__name__
        try:
            return do_rollback(state, reason)
        except Exception as recovery_error:
            state['status'] = 'RECOVERY_UNVERIFIED'
            state['failure_reason'] = reason
            state['recovery_reason'] = str(recovery_error) if isinstance(recovery_error, GateStop) else 'REDACTED_' + type(recovery_error).__name__
            replace_private(STATE_PATH, state)
            return {'status': 'RECOVERY_UNVERIFIED', 'failure_reason': reason, 'recovery_reason': state['recovery_reason']}

def rollback(envelope: dict[str, object]) -> dict[str, object]:
    invocation_id = str(envelope['invocation_id'])
    read_claim(invocation_id, envelope)
    state = read_state(invocation_id)
    require(state.get('status') == 'DEPLOYED_VERIFIED_UAT_PENDING', 'ROLLBACK_STATE_NOT_ELIGIBLE')
    return do_rollback(state, 'MANDATORY_UAT_OR_SAFETY_GATE_FAILED')

def uat(envelope: dict[str, object]) -> dict[str, object]:
    invocation_id = str(envelope['invocation_id'])
    read_claim(invocation_id, envelope)
    state = read_state(invocation_id)
    require(state.get('status') == 'DEPLOYED_VERIFIED_UAT_PENDING', 'UAT_STATE_NOT_ELIGIBLE')
    require(utc_now() < DECISION_DEADLINE, 'FORWARD_UAT_DECISION_DEADLINE_EXCEEDED')
    task_id = str(envelope.get('task_id', ''))
    review_id = str(envelope.get('review_id', ''))
    deployed = state.get('deployment_verification') or {}
    deployed_target = deployed.get('target') or {}
    expected_image = str(deployed_target.get('image_id', ''))
    require(expected_image in CANDIDATE_RUNTIME_IDS, 'UAT_CANDIDATE_IMAGE_BINDING_INVALID')
    verification = verify_after(str(state['before_target_shape_sha256']), expected_image, allow_namespace_growth=True)
    before_counters = state.get('baseline_safety_counters') or {}
    after_counters = verification['safety']
    stable_names = tuple((name for name in SAFETY_COUNTERS if name != 'cohort_task_count'))
    require(all((after_counters.get(name) == before_counters.get(name) for name in stable_names)), 'FORBIDDEN_COUNTER_CHANGED_DURING_UAT')
    require(after_counters.get('cohort_task_count') == int(before_counters.get('cohort_task_count', -1)) + 1, 'UAT_COHORT_TASK_DELTA_NOT_ONE')
    require(verification['routes'].get('cohort_review_count') == int(state.get('baseline_cohort_review_count', -1)) + 1, 'UAT_REVIEW_DELTA_NOT_ONE')
    require(isinstance(after_counters.get('namespace_key_count'), int) and after_counters['namespace_key_count'] >= int(state.get('baseline_namespace_key_count', 10 ** 18)), 'UAT_NAMESPACE_KEY_COUNT_REGRESSED')
    current = target(inspect_all())
    require(public_identity(current) == verification['target'], 'TARGET_DRIFT_DURING_UAT_CAPTURE')
    detail = uat_detail(current, task_id, review_id)
    require(detail.get('task_id') == task_id and detail.get('review_id') == review_id, 'UAT_RECORD_BINDING_MISMATCH')
    require(utc_now() < DECISION_DEADLINE, 'UAT_CAPTURE_AFTER_DECISION_DEADLINE')
    return {'status': 'PASS', 'invocation_id': invocation_id, 'captured_at_utc': iso(), 'target': verification['target'], 'routes': verification['routes'], 'safety_counters': {name: after_counters.get(name) for name in SAFETY_COUNTERS}, 'namespace_key_count': after_counters.get('namespace_key_count'), 'detail': detail, 'protected_services_unchanged': True, 'production_mutation': False, 'business_system_write': False}

def main() -> None:
    mode = sys.argv[1] if len(sys.argv) >= 2 else ''
    require(mode in {'preflight', 'claim', 'deploy', 'uat', 'rollback'} and len(sys.argv) == 3, 'USAGE_INVALID')
    envelope = parse_envelope(sys.argv[2], require_preflight=mode != 'preflight')
    if mode == 'preflight':
        result = preflight(envelope)
    elif mode == 'claim':
        result = claim(envelope)
    elif mode == 'deploy':
        result = deploy(envelope)
    elif mode == 'uat':
        result = uat(envelope)
    else:
        result = rollback(envelope)
    result.update({'operation_id': OPERATION, 'mode': mode, 'raw_secrets_accounts_keys_values_or_pii_emitted': False})
    print(json.dumps(result, indent=2, sort_keys=True))
if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        reason = str(error) if isinstance(error, GateStop) else 'REDACTED_' + type(error).__name__
        print(json.dumps({'status': 'ABORTED_FAIL_CLOSED', 'reason': reason, 'operation_id': OPERATION, 'raw_sensitive_output': False}, sort_keys=True))
        raise SystemExit(2)
