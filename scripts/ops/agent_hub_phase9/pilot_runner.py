"""Fresh Phase 9 runner. Preparation authority never permits execution."""
from datetime import datetime, timezone
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gate_bindings import GateStop, HASH, load, require, sha, verify_package
from pilot_dispatcher import dispatch_preflight, verify_execution_approval
import remote_preflight_capture as capture
from pilot_transport import invoke, strict_argv, stage_argv

def encode(value): return base64.urlsafe_b64encode(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).decode()

def publish(directory, name, value):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    with path.open('xb') as handle:
        handle.write(json.dumps(value, indent=2, sort_keys=True).encode() + b'\n'); handle.flush(); os.fsync(handle.fileno())
    return path

def confirmation_entropy(contract):
    return ('npd.agent-hub.rca05.confirmation.v1|' + contract['operation_id'] + '|' + contract['candidate_head']
        + '|' + contract['snapshot_sha256']).encode()

def dpapi(raw, entropy, *, decrypt):
    import ctypes
    from ctypes import wintypes
    class Blob(ctypes.Structure): _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_byte))]
    a = ctypes.create_string_buffer(raw); b = ctypes.create_string_buffer(entropy)
    input_blob=Blob(len(raw),ctypes.cast(a,ctypes.POINTER(ctypes.c_byte)))
    entropy_blob=Blob(len(entropy),ctypes.cast(b,ctypes.POINTER(ctypes.c_byte))); output=Blob()
    crypt = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    crypt.argtypes=[ctypes.POINTER(Blob),wintypes.LPWSTR,ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    crypt.restype=wintypes.BOOL
    require(bool(crypt(ctypes.byref(input_blob),None,ctypes.byref(entropy_blob),None,None,1,ctypes.byref(output))), 'CONFIRMATION_DPAPI_INVALID')
    free=ctypes.windll.kernel32.LocalFree;free.argtypes=[ctypes.c_void_p];free.restype=ctypes.c_void_p
    try: return ctypes.string_at(output.pbData, output.cbData)
    finally: free(output.pbData)

def unprotect(raw, entropy): return dpapi(raw, entropy, decrypt=True)
def protect(raw, entropy): return dpapi(raw, entropy, decrypt=False)

def authorize(package, verified, anchor, approval_path, confirmation_path, *, current=None, phase='mutation'):
    require(approval_path is not None and Path(approval_path).is_file(), 'OWNER_EXECUTION_APPROVAL_NOT_GRANTED')
    approval=verify_execution_approval(load(approval_path),verified,anchor,current=current,phase=phase)
    contract=load(package/'CONFIRMATION_CONTRACT.json')
    require(confirmation_path is not None and Path(confirmation_path).is_file()
        and not Path(confirmation_path).is_symlink(), 'FRESH_CONFIRMATION_CUSTODY_MISSING')
    require(sha(confirmation_path)==contract['private_dpapi_blob_sha256'], 'CONFIRMATION_CUSTODY_HASH_MISMATCH')
    entropy=confirmation_entropy(contract)
    require(hashlib.sha256(entropy).hexdigest()==contract['dpapi_entropy_sha256'], 'CONFIRMATION_ENTROPY_MISMATCH')
    token=unprotect(Path(confirmation_path).read_bytes(),entropy)
    require(len(token)==32 and hashlib.sha256(token).hexdigest()==contract['confirmation_token_sha256'], 'FRESH_CONFIRMATION_INVALID')
    return approval

def envelope_for(verified, profile, anchor, invocation, approval=None):
    deps=verified['bindings']['dependency_hashes']
    envelope={'schema':'npd.phase9.limited-pilot-rca05.dispatch.v1', 'operation_id':profile['operation_id'],
        'invocation_id':invocation, 'candidate_head':profile['candidate_head'], 'snapshot_sha256':profile['snapshot_sha256'],
        'counter_evidence_sha256':profile['counter_evidence_sha256'], 'protected_services_sha256':profile['protected_services_sha256'],
        'owner_exception_receipt_sha256':profile['owner_exception_receipt_sha256'],
        'confirmation_token_sha256':profile['confirmation_token_sha256'], 'fresh_backup_manifest_sha256':profile['fresh_backup_manifest_sha256'],
        'rollback_bundle_manifest_sha256':profile['rollback_bundle_manifest_sha256'], 'main_sha':profile['source_main_sha'],
        'owner_gate_sha256':deps['OWNER_GATE.md'], 'payload_manifest_sha256':deps['ARTIFACT_MANIFEST.json'], 'package_manifest_sha256':anchor,
        'approval_file_sha256':'0'*64, 'approval_verbatim_sha256':'0'*64, 'runner_sha256':deps['runner.py'],
        'rollback_dispatcher_sha256':deps['rollback.py'], 'finalizer_sha256':deps['finalizer.py'], 'remote_runtime_sha256':deps['remote_runtime.py'],
        'execution_scope_sha256':deps['EXECUTION_SCOPE.json'], 'artifact_manifest_sha256':deps['ARTIFACT_MANIFEST.json'],
        'dispatcher_sha256':deps['dispatcher.py'], 'verifier_sha256':deps['verifier.py'],
        'confirmation_contract_sha256':deps['CONFIRMATION_CONTRACT.json'], 'operation_bindings_sha256':sha(Path(profile['_package'])/'OPERATION_BINDINGS.json'),
        'final_readonly_preflight_status':'PENDING', 'final_readonly_preflight_sha256':'0'*64,
        'preflight_readonly':True, 'execution_approval':'NOT_GRANTED', 'fresh_explicit_owner_execution_approval':False}
    if approval:
        envelope.update({'execution_approval':'APPROVED','fresh_explicit_owner_execution_approval':True,
            'window':approval['window'], 'scope':'AGENT_HUB_ONLY_NO_PROVIDER_NO_VIDEO_FACTORY_EXECUTION',
            'approval_file_sha256':profile['_approval_file_sha256'], 'approval_verbatim_sha256':approval['owner_authorization_receipt_sha256']})
    return envelope

def observe(package, verified, profile, anchor, envelope, evidence, invoker=invoke):
    argv=strict_argv(profile,['python3','-B','-','preflight',encode(envelope)])
    return dispatch_preflight(invoker,argv,package=package,expected_manifest=anchor,
        expected_head=profile['candidate_head'],expected_baseline=profile['protected_services_sha256'],
        input_bytes=(package/'remote_runtime.py').read_bytes(),evidence_directory=evidence,timeout=240)

def invoke_mode(package,profile,envelope,mode,evidence,invoker=invoke):
    argv=strict_argv(profile,['python3','-B','-',mode,encode(envelope)])
    identifier=str(uuid4()); started=datetime.now(timezone.utc).isoformat()
    result=invoker(argv,input_bytes=(package/'remote_runtime.py').read_bytes(),timeout=2700)
    capture._publish(evidence,identifier,{'binding_id':profile['operation_id'],'invocation_id':identifier,
        'started_at_utc':started,'completed_at_utc':datetime.now(timezone.utc).isoformat(), 'child_returncode':result.returncode,
        'stdout':capture._stream(result.stdout),'stderr':capture._stream(result.stderr),'argv_or_authorization_persisted':False})
    require(type(result.returncode) is int and result.returncode==0 and not result.stderr,'REMOTE_ACTION_FAILED')
    value=json.loads(result.stdout)
    require(value.get('operation_id')==profile['operation_id'] and value.get('mode')==mode,'REMOTE_ACTION_BINDING_MISMATCH')
    return value

def execute(package,verified,profile,anchor,approval_path,confirmation_path,authority, *, action='execute', invoker=invoke, browser=None):
    # Approval and token checks occur before transport, any claim, or any file write.
    phase={'execute':'mutation','uat':'decision','rollback':'recovery'}[action]
    approval=authorize(package,verified,anchor,approval_path,confirmation_path,phase=phase)
    require(isinstance(approval.get('owner_authorization_receipt_sha256'),str)
        and bool(HASH.fullmatch(approval['owner_authorization_receipt_sha256'])),'OWNER_AUTHORIZATION_RECEIPT_MISSING')
    profile['_approval_file_sha256']=sha(approval_path)
    invocation=str(uuid4()) if action=='execute' else load(authority/'DISPATCH_CLAIM.json')['invocation_id']
    envelope=envelope_for(verified,profile,anchor,invocation,approval)
    if action=='execute':
        require(not (authority/'DISPATCH_CLAIM.json').exists(),'LOCAL_OPERATION_ALREADY_DISPATCHED')
        preflight,path=observe(package,verified,profile,anchor,envelope,authority/'captures',invoker)
        preflight_path=publish(authority,'FINAL_READONLY_PREFLIGHT.json',preflight)
        envelope['final_readonly_preflight_status']='PASS';envelope['final_readonly_preflight_sha256']=sha(preflight_path)
        # Revalidate the approval window and all files after the child and before claim.
        verify_execution_approval(approval,verify_package(package,anchor,profile['candidate_head'],profile['protected_services_sha256']),anchor)
        publish(authority,'DISPATCH_CLAIM.json',envelope)
        claimed=invoke_mode(package,profile,envelope,'claim',authority/'captures',invoker)
        require(claimed.get('status')=='CLAIMED' and claimed.get('claim_id')==invocation,'REMOTE_CLAIM_NOT_ACCEPTED')
        publish(authority,'REMOTE_CLAIM.json',claimed)
        require(claimed.get('stage_path')=='/var/lib/npd-ai/agent-hub-deployments/phase9-limited-pilot/attempts/'+profile['operation_id']+'/candidate.oci.tar','REMOTE_STAGE_PATH_MISMATCH')
        staged=invoker(stage_argv(profile,package/'candidate.oci.tar',profile['operation_id']),timeout=900)
        require(staged.returncode==0,'CANDIDATE_STAGE_FAILED')
        value=invoke_mode(package,profile,envelope,'deploy',authority/'captures',invoker)
        require(value.get('status') in {'DEPLOYED_VERIFIED_UAT_PENDING','ROLLED_BACK_VERIFIED','RECOVERY_UNVERIFIED'},'REMOTE_DEPLOY_RESULT_INVALID')
        publish(authority,'REMOTE_DEPLOYMENT.json',value)
        return value
    previous=load(authority/'DISPATCH_CLAIM.json')
    require(previous.get('operation_id')==profile['operation_id'],'LOCAL_OPERATION_MISMATCH')
    if action=='uat':
        require(isinstance(browser,dict),'REAL_BROWSER_UAT_EVIDENCE_REQUIRED')
        envelope['task_id']=browser.get('task_id');envelope['review_id']=browser.get('review_id')
    envelope['final_readonly_preflight_status']='PASS';envelope['final_readonly_preflight_sha256']=previous['final_readonly_preflight_sha256']
    value=invoke_mode(package,profile,envelope,action,authority/'captures',invoker)
    publish(authority,action.upper()+'_RESULT.json',value)
    return value

def main(action='execute'):
    parser=argparse.ArgumentParser(); parser.add_argument('--verify-prepared',action='store_true'); parser.add_argument('--execute',action='store_true')
    parser.add_argument('--manifest',required=True);parser.add_argument('--head',required=True);parser.add_argument('--baseline',required=True)
    parser.add_argument('--approval');parser.add_argument('--confirmation');parser.add_argument('--authority')
    args=parser.parse_args(); require(args.verify_prepared != args.execute,'EXACT_ACTION_REQUIRED')
    package=Path(__file__).resolve().parent
    verified=verify_package(package,args.manifest,args.head,args.baseline)
    if args.verify_prepared:
        print(json.dumps({'status':'PREPARED_FOR_OWNER_REVIEW','operation_id':verified['manifest']['operation_id'], 'execution_approval':'NOT_GRANTED','operation_execution':'NONE'}));return
    require(args.authority is not None,'AUTHORITY_DIRECTORY_REQUIRED')
    profile=load(package/'RUNTIME_PROFILE.json');profile['_package']=str(package)
    value=execute(package,verified,profile,args.manifest,args.approval,args.confirmation,Path(args.authority),action=action)
    print(json.dumps({'status':value['status'],'operation_id':profile['operation_id'],'raw_sensitive_output':False}))

if __name__=='__main__':
    try:main()
    except Exception as error:
        print(json.dumps({'status':'ABORTED_FAIL_CLOSED','reason':str(error) if isinstance(error,GateStop) else 'REDACTED_'+type(error).__name__,'raw_sensitive_output':False}));raise SystemExit(2)
