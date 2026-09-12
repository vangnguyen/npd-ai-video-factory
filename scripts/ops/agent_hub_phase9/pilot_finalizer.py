"""Reconcile one real UAT after future fresh owner execution approval."""
import argparse
import json
from pathlib import Path
from gate_bindings import GateStop, load, require, sha, verify_package
import pilot_runner as runner
import pilot_uat as uat

def main():
    p=argparse.ArgumentParser();p.add_argument('--finalize',action='store_true',required=True)
    for name in ('manifest','head','baseline','approval','confirmation','authority','browser-evidence'):p.add_argument('--'+name,required=True)
    args=p.parse_args();package=Path(__file__).resolve().parent;authority=Path(args.authority)
    verified=verify_package(package,args.manifest,args.head,args.baseline)
    profile=load(package/'RUNTIME_PROFILE.json');profile['_package']=str(package)
    approval=runner.authorize(package,verified,args.manifest,args.approval,args.confirmation,phase='decision')
    browser=load(args.browser_evidence)
    dispatch=load(authority/'DISPATCH_CLAIM.json');claimed=load(authority/'REMOTE_CLAIM.json');deployed=load(authority/'REMOTE_DEPLOYMENT.json')
    require(browser.get('operation_id')==profile['operation_id'] and browser.get('invocation_id')==dispatch['invocation_id'],'BROWSER_OPERATION_BINDING_INVALID')
    remote=runner.execute(package,verified,profile,args.manifest,args.approval,args.confirmation,authority,action='uat',browser=browser)
    uat.configure(profile,approval);evaluation=uat.evaluate(dispatch,claimed,deployed,browser,remote)
    runner.publish(authority,'UAT_EVALUATION.json',evaluation)
    require(evaluation['status']=='PASS','UAT_FAILED_ROLLBACK_REVIEW_REQUIRED')
    runner.publish(authority,'LIMITED_PHASE9_PILOT_FINAL_RECEIPT.json',{'operation_id':profile['operation_id'],
        'invocation_id':dispatch['invocation_id'],'verdict':'LIMITED_PHASE9_PILOT_PASS','full_phase9_acceptance':False,
        'snapshot_sha256':profile['snapshot_sha256'],'counter_evidence_sha256':profile['counter_evidence_sha256'],
        'evaluation_sha256':sha(authority/'UAT_EVALUATION.json'),'actual_browser_evidence_sha256':sha(args.browser_evidence),
        'owner_approval_sha256':sha(args.approval),'provider_calls':0,'video_factory_execution':False})
    print(json.dumps({'verdict':'LIMITED_PHASE9_PILOT_PASS','operation_id':profile['operation_id'],'full_phase9_acceptance':False}))

if __name__=='__main__':
    try:main()
    except Exception as e:
        print(json.dumps({'status':'ABORTED_FAIL_CLOSED','reason':str(e) if isinstance(e,GateStop) else 'REDACTED_'+type(e).__name__}));raise SystemExit(2)
