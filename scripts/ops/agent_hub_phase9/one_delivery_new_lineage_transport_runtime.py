"""Sealed transport profile and rendered read-only collector for review.

This module renders bytes and argv only.  It has no process, socket, SSH,
network, credential-loading, or command-execution entry point.  Runtime use is
fail-closed until a separately trusted read scope or execution gate exists.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Mapping

import one_delivery_new_lineage as lineage
import one_delivery_new_lineage_readonly_evidence as readonly


PROFILE_SCHEMA = "npd.agent-hub.phase9.one-delivery-transport-profile.v1"
COLLECTOR_SCHEMA = "npd.agent-hub.phase9.one-delivery-rendered-collector.v1"
COMMAND_SCHEMA = "npd.agent-hub.phase9.one-delivery-strict-argv.v1"
SOURCE_ONLY_MODE = "SOURCE_ONLY_RUNTIME_DISABLED"
HOST = re.compile(r"^[A-Za-z0-9.-]{1,253}$")
USER = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
CONTAINER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
PATH_TOKEN_IDENTITY = "<IDENTITY_PATH_FROM_TRUSTED_GATE>"
PATH_TOKEN_KNOWN_HOSTS = "<KNOWN_HOSTS_PATH_FROM_TRUSTED_GATE>"


DB0_LUA = """local cursor='0'
local seen={}
local keys={}
repeat
  local page=redis.call('SCAN',cursor,'MATCH','npd:video-job:*','COUNT',1000)
  cursor=page[1]
  for _,key in ipairs(page[2]) do
    if not seen[key] then seen[key]=true;table.insert(keys,key) end
  end
until cursor=='0'
local inflight=0
local terminal={awaiting_review=true,completed=true,failed=true,cancelled=true}
for _,key in ipairs(keys) do
  local raw=redis.call('GET',key)
  if raw then
    local ok,job=pcall(cjson.decode,raw)
    if not ok or type(job)~='table' then
      inflight=inflight+1
    elseif not terminal[job.status] and not terminal[job.stage] then
      inflight=inflight+1
    end
  end
end
return {#keys,redis.call('LLEN','npd:video-jobs:queue'),redis.call('LLEN','npd:video-jobs:processing'),inflight}
"""


def _exact(value: object, fields: set[str], reason: str) -> Mapping[str, object]:
    lineage.require(isinstance(value, Mapping) and set(value) == fields, reason)
    return value


def _hash(value: object, reason: str) -> str:
    lineage.require(
        isinstance(value, str) and bool(lineage.HASH.fullmatch(value)), reason
    )
    return value


def _remote_path(value: object, reason: str) -> str:
    lineage.require(isinstance(value, str) and bool(value), reason)
    path = PurePosixPath(value)
    lineage.require(
        path.is_absolute()
        and ".." not in path.parts
        and str(path).startswith("/var/lib/npd-agent-hub-phase9/"),
        reason,
    )
    return value


def _target_descriptor(profile: Mapping[str, object]) -> dict[str, object]:
    return {
        "host": profile["host"],
        "port": profile["port"],
        "user": profile["user"],
        "host_key_fingerprint_sha256": profile[
            "host_key_fingerprint_sha256"
        ],
    }


def verify_transport_profile(value: object) -> Mapping[str, object]:
    """Verify one exact, non-executable source-review transport profile."""
    profile = _exact(
        value,
        {
            "schema",
            "lineage",
            "mode",
            "host",
            "port",
            "user",
            "pinned_target_sha256",
            "host_key_fingerprint_sha256",
            "ssh_executable_sha256",
            "known_hosts_bytes_sha256",
            "identity_public_fingerprint_sha256",
            "target_container_name",
            "compose_project",
            "compose_service",
            "protected_container_names",
            "candidate_archive_path",
            "rollback_archive_path",
            "candidate_custody_manifest_path",
            "rollback_custody_manifest_path",
            "claim_path",
            "stage_path",
            "delivery_receipt_path",
            "connection_attempts",
            "connect_timeout_seconds",
            "batch_mode",
            "strict_host_key_checking",
            "identities_only",
            "password_authentication",
            "kbd_interactive_authentication",
            "clear_all_forwardings",
            "request_tty",
            "read_scope_authority",
            "execution_authority",
        },
        "TRANSPORT_PROFILE_SCHEMA_INVALID",
    )
    for field in (
        "pinned_target_sha256",
        "host_key_fingerprint_sha256",
        "ssh_executable_sha256",
        "known_hosts_bytes_sha256",
        "identity_public_fingerprint_sha256",
    ):
        _hash(profile.get(field), "TRANSPORT_PROFILE_HASH_INVALID")
    for field in (
        "candidate_archive_path",
        "rollback_archive_path",
        "candidate_custody_manifest_path",
        "rollback_custody_manifest_path",
        "claim_path",
        "stage_path",
        "delivery_receipt_path",
    ):
        _remote_path(profile.get(field), "TRANSPORT_PROFILE_PATH_INVALID")
    lineage.require(
        profile.get("schema") == PROFILE_SCHEMA
        and profile.get("lineage") == lineage.LINEAGE
        and profile.get("mode") == SOURCE_ONLY_MODE
        and isinstance(profile.get("host"), str)
        and bool(HOST.fullmatch(profile["host"]))
        and type(profile.get("port")) is int
        and 1 <= profile["port"] <= 65535
        and isinstance(profile.get("user"), str)
        and bool(USER.fullmatch(profile["user"]))
        and isinstance(profile.get("target_container_name"), str)
        and bool(CONTAINER.fullmatch(profile["target_container_name"]))
        and profile.get("compose_project") == "npd-agent-hub-prod"
        and profile.get("compose_service") == "agent-hub"
        and isinstance(profile.get("protected_container_names"), list)
        and len(profile["protected_container_names"]) == 18
        and len(set(profile["protected_container_names"])) == 18
        and profile["protected_container_names"]
        == sorted(profile["protected_container_names"])
        and all(
            isinstance(name, str) and bool(CONTAINER.fullmatch(name))
            for name in profile["protected_container_names"]
        )
        and profile.get("target_container_name")
        not in profile["protected_container_names"]
        and profile.get("connection_attempts") == 1
        and type(profile.get("connection_attempts")) is int
        and type(profile.get("connect_timeout_seconds")) is int
        and 1 <= profile["connect_timeout_seconds"] <= 15
        and profile.get("batch_mode") is True
        and profile.get("strict_host_key_checking") is True
        and profile.get("identities_only") is True
        and profile.get("password_authentication") is False
        and profile.get("kbd_interactive_authentication") is False
        and profile.get("clear_all_forwardings") is True
        and profile.get("request_tty") is False
        and profile.get("read_scope_authority")
        == "NOT_GRANTED_STRUCTURAL_FIXTURE_ONLY"
        and profile.get("execution_authority") == "NOT_GRANTED",
        "TRANSPORT_PROFILE_BOUNDARY_INVALID",
    )
    lineage.require(
        profile.get("pinned_target_sha256")
        == lineage.canonical_digest(_target_descriptor(profile)),
        "TRANSPORT_PINNED_TARGET_MISMATCH",
    )
    lineage.require(
        len(
            {
                profile["candidate_archive_path"],
                profile["rollback_archive_path"],
                profile["candidate_custody_manifest_path"],
                profile["rollback_custody_manifest_path"],
                profile["claim_path"],
                profile["stage_path"],
                profile["delivery_receipt_path"],
            }
        )
        == 7,
        "TRANSPORT_REMOTE_PATH_COLLISION",
    )
    return profile


def render_readonly_collector(
    profile: object,
) -> bytes:
    """Render deterministic collector source; never execute it."""
    checked_profile = verify_transport_profile(profile)
    profile_json = lineage.canonical_bytes(checked_profile).decode("utf-8")
    lua_json = json.dumps(DB0_LUA, ensure_ascii=True)
    source = f'''# {COLLECTOR_SCHEMA}
import base64,hashlib,json,os,stat,subprocess,sys
from datetime import datetime,timezone
PROFILE=json.loads({json.dumps(profile_json)})
DB0_LUA={lua_json}
COUNTERS={json.dumps(list(readonly.COUNTER_NAMES), separators=(",", ":"))}
def canon(value):return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
def digest(value):return hashlib.sha256(canon(value)).hexdigest()
def run(argv,data=None,allow_absent=False):
 p=subprocess.run(argv,input=data,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False,shell=False,timeout=120)
 if p.returncode!=0:
  if allow_absent and p.returncode==1:return b""
  raise RuntimeError("READ_COMMAND_FAILED")
 if p.stderr:raise RuntimeError("READ_COMMAND_STDERR_NONEMPTY")
 return p.stdout
def file_hash(path):
 if not stat.S_ISREG(os.lstat(path).st_mode):raise RuntimeError("ARTIFACT_NOT_REGULAR_FILE")
 h=hashlib.sha256();size=0
 with open(path,"rb") as handle:
  while True:
   block=handle.read(1048576)
   if not block:break
   size+=len(block);h.update(block)
 return h.hexdigest(),size
def archive(identity,path):
 actual,size=file_hash(path)
 if actual!=identity["archive_sha256"] or size!=identity["archive_size_bytes"]:raise RuntimeError("ARCHIVE_BINDING_MISMATCH")
def custody(identity,path):
 actual,_=file_hash(path)
 if actual!=identity["custody_manifest_sha256"]:raise RuntimeError("CUSTODY_BINDING_MISMATCH")
if len(sys.argv)!=5 or sys.argv[1]!="readonly-evidence" or len(sys.argv[2])!=64 or len(sys.argv[3])!=64:raise RuntimeError("ARGV_BINDING_INVALID")
payload=sys.argv[4];payload+=\"=\"*((4-len(payload)%4)%4)
REQUEST=json.loads(base64.urlsafe_b64decode(payload.encode()).decode())
if hashlib.sha256(canon(REQUEST)).hexdigest()!=sys.argv[2] or REQUEST.get("collector_bytes_sha256")!=sys.argv[3] or REQUEST.get("transport_profile_sha256")!=digest(PROFILE) or REQUEST.get("pinned_target_sha256")!=PROFILE["pinned_target_sha256"]:raise RuntimeError("REQUEST_BINDING_INVALID")
target=json.loads(run(["docker","inspect","--type","container",PROFILE["target_container_name"]]))[0]
all_rows=json.loads(run(["docker","inspect"]+PROFILE["protected_container_names"]))
protected=[]
for row in all_rows:
 labels=(row.get("Config") or {{}}).get("Labels") or {{}}
 if labels.get("com.docker.compose.project")==PROFILE["compose_project"] and labels.get("com.docker.compose.service")==PROFILE["compose_service"]:continue
 protected.append({{"name":str(row.get("Name","")).lstrip("/"),"id":row.get("Id"),"image":row.get("Image"),"project":labels.get("com.docker.compose.project"),"service":labels.get("com.docker.compose.service"),"status":(row.get("State") or {{}}).get("Status"),"health":((row.get("State") or {{}}).get("Health") or {{}}).get("Status"),"restart_count":row.get("RestartCount")}})
protected=sorted(protected,key=lambda row:row["name"])
probe=''' + repr('''import json,os
from urllib.parse import unquote,urlsplit
from redis import Redis
lua=''' + repr(DB0_LUA) + '''
url=os.environ["AGENT_REDIS_URL"]
parts=urlsplit(url)
if parts.scheme not in ("redis","rediss") or not parts.hostname:raise RuntimeError("REDIS_REFERENCE_INVALID")
client=Redis(host=parts.hostname,port=parts.port or 6379,username=unquote(parts.username) if parts.username else None,password=unquote(parts.password) if parts.password else None,db=0,ssl=parts.scheme=="rediss",decode_responses=True)
try: values=client.eval_ro(lua,0)
finally: client.close()
if not isinstance(values,list) or len(values)!=4 or any(type(v) is not int or v<0 for v in values):raise RuntimeError("COUNTER_VALUES_INVALID")
print(json.dumps(values,separators=(",",":")))
''') + '''
values=json.loads(run(["docker","exec","-i",target["Id"],"python","-B","-c",probe]))
candidate=REQUEST["candidate_identity"];rollback=REQUEST["rollback_identity"]
archive(candidate,PROFILE["candidate_archive_path"]);archive(rollback,PROFILE["rollback_archive_path"])
custody(candidate,PROFILE["candidate_custody_manifest_path"]);custody(rollback,PROFILE["rollback_custody_manifest_path"])
candidate_loaded=run(["docker","image","inspect","sha256:"+candidate["oci_config_sha256"]],allow_absent=True)!=b""
rollback_present=run(["docker","image","inspect","sha256:"+rollback["oci_config_sha256"]],allow_absent=True)!=b""
state=target.get("State") or {{}};target_config=str(target.get("Image","")).removeprefix("sha256:")
observed=datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
evidence={{"schema":"{readonly.EVIDENCE_SCHEMA}","lineage":"{lineage.LINEAGE}","operation_id":REQUEST["operation_id"],"request_sha256":hashlib.sha256(canon(REQUEST)).hexdigest(),"observed_at_utc":observed,"agent_hub":{{"compose_project":PROFILE["compose_project"],"compose_service":PROFILE["compose_service"],"pinned_target_sha256":PROFILE["pinned_target_sha256"],"target_container_id":target["Id"],"target_image_config_sha256":target_config,"target_signature_sha256":digest({{"id":target["Id"],"image":target.get("Image"),"state":state,"restart_count":target.get("RestartCount")}}),"protected_service_count":len(protected),"protected_services_sha256":digest(protected),"healthy":((state.get("Health") or {{}}).get("Status")=="healthy"),"ready":state.get("Running") is True,"restart_count":target.get("RestartCount"),"runtime_mode":"phase9_creation","scheduler_enabled":False,"external_writes_enabled":False,"claim_absent":not os.path.lexists(PROFILE["claim_path"]),"candidate_staged":os.path.lexists(PROFILE["stage_path"]),"delivery_absent":not os.path.lexists(PROFILE["delivery_receipt_path"]) }},"candidate":{{"identity":candidate,"archive_verified":True,"custody_manifest_verified":True,"staged":os.path.lexists(PROFILE["stage_path"]),"loaded":candidate_loaded}},"rollback":{{"identity":rollback,"archive_verified":True,"custody_manifest_verified":True,"image_present":rollback_present,"current_target":target_config==rollback["oci_config_sha256"]}},"video_factory_db0":{{"scope_receipt_sha256":REQUEST["db0_scope_receipt_sha256"],"counter_names":COUNTERS,"counters":dict(zip(COUNTERS,values)),"query_command":"EVAL_RO","database":0,"server_enforced_readonly":True,"eval_fallback_used":False,"raw_keys_values_credentials_or_job_payloads_emitted":False,"video_factory_workstream_opened":False,"video_factory_writes":0}},"effects":{{"production_read_only":True,"production_mutation":False,"business_system_write":False,"claim_created":False,"stage_performed":False,"image_loaded":False,"delivery_posted":False,"provider_calls":0,"video_factory_writes":0}},"scope_authority_class":"{readonly.SCOPE_AUTHORITY_FIXTURE_ONLY}","human_owner_approval_source_verified":False,"production_execution_approval":"NOT_GRANTED"}}
sys.stdout.buffer.write(canon(evidence)+b"\\n")
'''
    return source.encode("utf-8")


def collector_digest(source: object) -> str:
    lineage.require(type(source) is bytes and len(source) > 0, "COLLECTOR_BYTES_INVALID")
    return hashlib.sha256(source).hexdigest()


def render_strict_argv_template(
    request: object,
    profile: object,
    collector_source: object,
) -> dict[str, object]:
    """Render a sealed argv template with gate-supplied path placeholders."""
    checked_request = readonly.verify_request_contract(request)
    checked_profile = verify_transport_profile(profile)
    source_sha256 = collector_digest(collector_source)
    lineage.require(
        collector_source == render_readonly_collector(checked_profile),
        "COLLECTOR_BYTES_NOT_CANONICAL",
    )
    lineage.require(
        checked_request.get("transport_profile_sha256")
        == lineage.canonical_digest(checked_profile)
        and checked_request.get("collector_bytes_sha256") == source_sha256
        and checked_request.get("pinned_target_sha256")
        == checked_profile.get("pinned_target_sha256"),
        "STRICT_ARGV_REQUEST_BINDING_MISMATCH",
    )
    request_sha256 = lineage.canonical_digest(checked_request)
    argv = [
        "<SSH_EXECUTABLE_MATCHING_PROFILE_SHA256>",
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={PATH_TOKEN_KNOWN_HOSTS}",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "PasswordAuthentication=no",
        "-o",
        "KbdInteractiveAuthentication=no",
        "-o",
        "ClearAllForwardings=yes",
        "-o",
        f"ConnectionAttempts={checked_profile['connection_attempts']}",
        "-o",
        f"ConnectTimeout={checked_profile['connect_timeout_seconds']}",
        "-i",
        PATH_TOKEN_IDENTITY,
        "-p",
        str(checked_profile["port"]),
        f"{checked_profile['user']}@{checked_profile['host']}",
        "python3",
        "-B",
        "-",
        "readonly-evidence",
        request_sha256,
        source_sha256,
        "<BASE64URL_CANONICAL_REQUEST>",
    ]
    return {
        "schema": COMMAND_SCHEMA,
        "lineage": lineage.LINEAGE,
        "mode": SOURCE_ONLY_MODE,
        "argv": argv,
        "stdin_sha256": source_sha256,
        "request_sha256": request_sha256,
        "request_payload_injected_only_by_trusted_gate": True,
        "request_payload_persisted": False,
        "transport_profile_sha256": lineage.canonical_digest(checked_profile),
        "pinned_target_sha256": checked_profile["pinned_target_sha256"],
        "identity_path_from_trusted_gate": True,
        "known_hosts_path_from_trusted_gate": True,
        "generated_command_executed": False,
        "read_scope_authority": "NOT_GRANTED_STRUCTURAL_FIXTURE_ONLY",
        "execution_authority": "NOT_GRANTED",
    }


def refuse_runtime_execution() -> None:
    """Keep real transport fail-closed until a trusted runtime is reviewed."""
    raise lineage.NewLineageStop("REAL_TRANSPORT_RUNTIME_NOT_AUTHORIZED")
