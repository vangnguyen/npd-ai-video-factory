"""Local exact-approval entry; verify-prepared never grants authority or calls SSH."""

from custody_file_contract import custody_file_writer
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from uuid import uuid4

import claim_only_terminalization as contract
from pilot_transport import strict_argv

def checked_inputs(plan_path, tool_path, profile_path):
    plan_raw=Path(plan_path).read_bytes();plan=contract.decode(plan_raw);contract.verify_plan(plan)
    contract.require(contract.sha(plan_raw)==contract.plan_digest(plan),'PLAN_FILE_BYTES_NONCANONICAL')
    repo=Path(__file__).resolve().parents[3]
    result=subprocess.run(['git','-C',str(repo),'rev-parse','HEAD'],capture_output=True,shell=False,timeout=15)
    contract.require(result.returncode==0 and result.stdout.decode().strip()==plan['source_head'],'LOCAL_SOURCE_HEAD_DRIFT')
    for name,key in [('claim_terminalization_entry.py','terminalization_entry_sha256'),
        ('claim_only_terminalization.py','terminalization_contract_sha256'),('operation_identity.py','identity_contract_sha256'),
        ('pilot_transport.py','strict_transport_sha256')]:
        path=Path(__file__).with_name(name)
        contract.require(path.is_file() and not path.is_symlink() and contract.sha(path.read_bytes())==plan[key],
            'LOCAL_EXECUTABLE_SOURCE_DRIFT:'+name)
    tool=Path(tool_path);contract.require(tool.is_file() and not tool.is_symlink(),'TOOL_PATH_UNSAFE')
    tool_raw=tool.read_bytes();contract.require(contract.sha(tool_raw)==plan['terminalization_tool_sha256'],'TOOL_HASH_MISMATCH')
    profile_raw=Path(profile_path).read_bytes()
    contract.require(contract.sha(profile_raw)==plan['approved_runtime_profile_sha256'],'TRUST_PROFILE_HASH_MISMATCH')
    return plan,tool_raw,contract.decode(profile_raw)

def exact_owner_approval(plan, raw):
    contract.require(raw==contract.approval_text(plan).encode('utf-8'),'OWNER_MESSAGE_NOT_VERBATIM')
    approval={'kind':'OWNER_CLAIM_ONLY_TERMINALIZATION_APPROVAL','decision':'APPROVED','fresh_explicit_owner_approval':True,
        'plan_sha256':contract.plan_digest(plan),'operation_id':plan['operation_id'],'attempt_id':plan['attempt_id'],
        'source_head':plan['source_head'],'terminalization_tool_sha256':plan['terminalization_tool_sha256'],
        'owner_verbatim_sha256':contract.sha(raw),'pilot_execution_authorized':False,'new_claim_authorized':False}
    contract.verify_approval(plan,approval)
    return approval

@custody_file_writer
def execute(plan,tool_raw,profile,owner_raw,authority,*,invoker=subprocess.run):
    # Only a subsequent actual Owner message may be supplied to this execution path.
    approval=exact_owner_approval(plan,owner_raw)
    contract.require(contract.sha(tool_raw)==plan['terminalization_tool_sha256'],'TOOL_HASH_MISMATCH')
    contract.require(not Path(authority).exists(),'TERMINALIZATION_AUTHORITY_ALREADY_USED')
    argv=strict_argv(profile,['python3','-B','-'])
    # Verify the exact transported code bytes before loading them server-side.
    payload=("import base64,hashlib,json\nraw=base64.b64decode("+repr(base64.b64encode(tool_raw).decode())+")\nassert hashlib.sha256(raw).hexdigest()=="+repr(plan['terminalization_tool_sha256'])+"\nscope={'__name__':'exact_owner_terminalization_tool'}\nexec(compile(raw,'bound_terminalization_tool','exec'),scope)\nplan=json.loads("+repr(json.dumps(plan,sort_keys=True))+ ")\napproval=json.loads("+repr(json.dumps(approval,sort_keys=True))+")\ntry:\n result=scope['run_bound_terminalization'](plan,approval,hashlib.sha256(raw).hexdigest())\n print(json.dumps(result,sort_keys=True))\nexcept Exception as error:\n safe=isinstance(error,(scope['TerminalizationStop'],scope['OperationIdentityError']))\n print(json.dumps({'status':'FAIL_CLOSED','reason':str(error) if safe else 'REDACTED_'+type(error).__name__,'operation_id':plan['operation_id'],'retry_allowed':False},sort_keys=True))\n raise SystemExit(2)\n").encode()
    Path(authority).mkdir(exist_ok=False)
    @custody_file_writer
    def save(name,raw):
        with (Path(authority)/name).open('xb') as stream:stream.write(raw);stream.flush();__import__('os').fsync(stream.fileno())
    save('OWNER_RECEIVED_TERMINALIZATION_APPROVAL.txt',owner_raw)
    save('OWNER_TERMINALIZATION_APPROVAL.json',contract.canonical(approval)+b'\n')
    identifier=str(uuid4());started=datetime.now(timezone.utc).isoformat()
    try:
        result=invoker(argv,input=payload,capture_output=True,shell=False,timeout=240)
        stdout,stderr,code,error=result.stdout,result.stderr,result.returncode,None
    except subprocess.TimeoutExpired as issue:stdout,stderr,code,error=issue.stdout or b'',issue.stderr or b'',None,'TIMEOUT'
    except OSError as issue:stdout,stderr,code,error=b'',b'',None,type(issue).__name__
    completed=datetime.now(timezone.utc).isoformat()
    save('TERMINALIZATION.stdout.txt',stdout);save('TERMINALIZATION.stderr.txt',stderr)
    save('TERMINALIZATION_CAPTURE.json',contract.canonical({'capture_uuid':identifier,'operation_id':plan['operation_id'],'attempt_id':plan['attempt_id'],
        'started_at_utc':started,'completed_at_utc':completed,'child_returncode':code,'transport_error':error,'stdout_sha256':contract.sha(stdout),
        'stderr_sha256':contract.sha(stderr),'stdout_bytes':len(stdout),'stderr_bytes':len(stderr),'payload_sha256':contract.sha(payload),'shell':False,
        'strict_host_key_checking':'yes','argv_or_authorization_persisted':False})+b'\n')
    contract.require(code==0 and error is None and not stderr,'TERMINALIZATION_REMOTE_FAILED_CAPTURE_PRESERVED')
    value=contract.decode(stdout)
    contract.require(value.get('status')=='TERMINALIZATION_COMPLETE_VERIFIED' and value.get('operation_id')==plan['operation_id']
        and value.get('attempt_id')==plan['attempt_id'] and value.get('terminal_state')==contract.TERMINAL_STATE,'TERMINALIZATION_RESULT_BINDING_MISMATCH')
    save('TERMINALIZATION_RESULT.json',contract.canonical(value)+b'\n')
    return value

def main():
    parser=argparse.ArgumentParser();mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--verify-prepared',action='store_true');mode.add_argument('--execute',action='store_true')
    for name in ('plan','tool','profile'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--owner-text');parser.add_argument('--authority');args=parser.parse_args()
    plan,tool,profile=checked_inputs(args.plan,args.tool,args.profile)
    if args.verify_prepared:
        print(json.dumps({'status':'PREPARED_FOR_OWNER_REVIEW','operation_id':plan['operation_id'],'owner_terminalization_approval':'NOT_GRANTED','remote_writes':0}));return
    contract.require(args.owner_text is not None and args.authority is not None,'ACTUAL_OWNER_MESSAGE_AND_FRESH_AUTHORITY_REQUIRED')
    value=execute(plan,tool,profile,Path(args.owner_text).read_bytes(),args.authority)
    print(json.dumps({'status':value['status'],'operation_id':plan['operation_id'],'terminal_state':value['terminal_state']}))

if __name__=='__main__':main()
