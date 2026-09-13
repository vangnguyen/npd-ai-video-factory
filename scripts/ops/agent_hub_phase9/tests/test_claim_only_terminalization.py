"""Local temporary fixtures only; no remote writes, claims, pilot or real approval."""
from datetime import datetime, timedelta, timezone
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import claim_only_terminalization as terminal
import operation_identity as identity
import pilot_dispatcher as dispatcher
import runtime_template as runtime

NOW=datetime(2026,9,13,7,10,tzinfo=timezone.utc)
ATTEMPT='542945ca-a1fb-49af-a340-4acd5485ee8f'

def fixture(root):
    operation=identity.CONSUMED_ABORTED_OPERATION;attempt=root/'attempts'/operation
    attempt.mkdir(parents=True);(root/'operations').mkdir()
    target={'container_id':'synthetic-unchanged-container','image_id':'synthetic-rollback-image','running':True,'restart_count':0}
    counters={'synthetic-counter':0};claimed=(NOW-timedelta(hours=2)).isoformat();mutation=(NOW-timedelta(hours=1)).isoformat()
    claim={'fixture_only':True,'schema':identity.CLAIM_SCHEMA,'operation_id':operation,'invocation_id':ATTEMPT,'claim_id':ATTEMPT,
        'status':'CLAIMED','claimed_at':claimed,'reset_for_retry_allowed':False,'window':{'latest_mutation_utc':mutation}}
    state={'fixture_only':True,'operation_id':operation,'invocation_id':ATTEMPT,'status':'CLAIMED','claimed_at':claimed,
        'before':target,'target_mutation_attempted':False,'candidate_deployment_retry_allowed':False,
        'protected_services_sha256':'a'*64,'baseline_safety_counters':counters,'baseline_namespace_key_count':10692}
    claim_path=root/'operations'/(operation+'.json');state_path=attempt/'state.json'
    claim_path.write_bytes(terminal.canonical(claim)+b'\n');state_path.write_bytes(terminal.canonical(state)+b'\n')
    (root/'operations'/'synthetic-other-operation.json').write_bytes(b'{"status":"CLAIMED","fixture_only":true}\n')
    plan={'schema':terminal.PLAN_SCHEMA,'root_path':terminal.ROOT_PATH,'operation_id':operation,'attempt_id':ATTEMPT,
        'expected_current_state':'CLAIMED','terminal_state':terminal.TERMINAL_STATE,'local_disposition':'ABORTED_BEFORE_STAGE_NOT_REUSABLE',
        'pilot_execution_authorized':False,'new_claim_authorized':False,'source_head':'1'*40,'claim_sha256':terminal.sha(claim_path.read_bytes()),
        'state_sha256':terminal.sha(state_path.read_bytes()),'observed_at_utc':NOW.isoformat(),'deadline_utc':(NOW+timedelta(hours=2)).isoformat(),
        'old_mutation_deadline_utc':mutation,'expected_claimed_at_utc':claimed,'allowed_metadata_paths':terminal.allowed_paths(operation),
        'expected_target':target,'expected_safety_counters':counters,'expected_namespace_key_count':10692,'protected_services_sha256':'a'*64}
    for name in ('claim_evidence_sha256','no_stage_no_deploy_evidence_sha256','local_disposition_sha256','terminalization_tool_sha256',
        'identity_contract_sha256','approved_remote_runtime_sha256','approved_runtime_profile_sha256','candidate_ci_evidence_sha256',
        'terminalization_entry_sha256','terminalization_contract_sha256','strict_transport_sha256'):plan[name]='b'*64
    live={'status':'PASS_READONLY_BASELINE','target':target,'protected_services_sha256':'a'*64,'safety_counters':counters,
        'namespace_key_count':10692,'cohort_review_count':0,'writes':0}
    return plan,live

def approval(plan):
    return {'kind':'OWNER_CLAIM_ONLY_TERMINALIZATION_APPROVAL','decision':'APPROVED','fresh_explicit_owner_approval':True,
        'plan_sha256':terminal.plan_digest(plan),'operation_id':plan['operation_id'],'attempt_id':plan['attempt_id'],
        'source_head':plan['source_head'],'terminalization_tool_sha256':plan['terminalization_tool_sha256'],
        'owner_verbatim_sha256':terminal.sha(terminal.approval_text(plan).encode()),'pilot_execution_authorized':False,'new_claim_authorized':False}

class ClaimOnlyTerminalizationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)/'local-fixture'
        self.plan,self.live=fixture(self.root);self.attempt=self.root/'attempts'/self.plan['operation_id']
        self.claim=self.root/'operations'/(self.plan['operation_id']+'.json');self.state=self.attempt/'state.json'
    def execute(self,**options):
        plan=options.pop('plan',self.plan)
        return terminal.terminalize(self.root,plan,options.pop('approval',approval(plan)),tool_sha256=options.pop('tool_sha256',plan['terminalization_tool_sha256']),
            verify_runtime=options.pop('verify_runtime',Mock(return_value=self.live)),current=options.pop('current',NOW),root_metadata=False,**options)
    def bytes(self):return {p.relative_to(self.root).as_posix():p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
    def assert_denied_unchanged(self,pattern,**options):
        before=self.bytes()
        with self.assertRaisesRegex(terminal.TerminalizationStop,pattern):self.execute(**options)
        self.assertEqual(self.bytes(),before)
    def test_correct_claim_only_terminalizes_once_preserves_originals_and_other_operation(self):
        before=self.bytes();verify=Mock(return_value=self.live);value=self.execute(verify_runtime=verify)
        self.assertEqual(value['status'],'TERMINALIZATION_COMPLETE_VERIFIED');self.assertEqual(verify.call_count,2)
        self.assertEqual(terminal.decode(self.claim.read_bytes())['status'],'ABORTED_BEFORE_STAGE')
        self.assertEqual(terminal.decode(self.state.read_bytes())['status'],'ABORTED_BEFORE_STAGE')
        self.assertEqual((self.attempt/'claim-before-terminalization.json').read_bytes(),before[f'operations/{self.plan["operation_id"]}.json'])
        self.assertEqual((self.attempt/'state-before-terminalization.json').read_bytes(),before[f'attempts/{self.plan["operation_id"]}/state.json'])
        self.assertEqual((self.root/'operations'/'synthetic-other-operation.json').read_bytes(),before['operations/synthetic-other-operation.json'])
        self.assertFalse(terminal.decode(self.claim.read_bytes())['reset_for_retry_allowed'])
        self.assertFalse(terminal.decode(self.state.read_bytes())['candidate_deployment_retry_allowed'])
    def test_second_terminalization_rejected_without_any_bytes_changed(self):
        self.execute();self.assert_denied_unchanged('FILE_PRESENT')
    def test_wrong_operation_rejected(self):
        plan={**self.plan,'operation_id':'PHASE9-LIMITED-PILOT-RCA06-'+str(uuid4())}
        with self.assertRaisesRegex(terminal.TerminalizationStop,'NOT_EXACT_ORPHAN'):terminal.verify_plan(plan)
    def test_wrong_attempt_rejected(self):self.assert_denied_unchanged('OWNERSHIP',plan={**self.plan,'attempt_id':str(uuid4())})
    def test_staged_operation_rejected(self):
        (self.attempt/'candidate.oci.tar').write_bytes(b'synthetic-stage');self.assert_denied_unchanged('FILE_PRESENT')
    def test_override_or_extra_file_rejected(self):
        for name in ('candidate-override.json','rollback-override.json','extra.txt'):
            with self.subTest(name=name):
                path=self.attempt/name;path.write_bytes(b'{}');self.assert_denied_unchanged('FILE_PRESENT');path.unlink()
    def test_deployed_operation_rejected(self):
        state=terminal.decode(self.state.read_bytes());state.update(status='DEPLOYED_VERIFIED_UAT_PENDING',target_mutation_attempted=True)
        self.state.write_bytes(terminal.canonical(state)+b'\n');self.plan['state_sha256']=terminal.sha(self.state.read_bytes())
        self.assert_denied_unchanged('NOT_ELIGIBLE')
    def test_mutation_flag_rejected_even_if_claimed(self):
        state=terminal.decode(self.state.read_bytes());state['target_mutation_attempted']=True;self.state.write_bytes(terminal.canonical(state)+b'\n')
        self.plan['state_sha256']=terminal.sha(self.state.read_bytes());self.assert_denied_unchanged('MUTATION_OR_RETRY')
    def test_claim_or_state_modified_after_readonly_evidence_rejected(self):
        self.claim.write_bytes(self.claim.read_bytes()+b' ');self.assert_denied_unchanged('HASH_MISMATCH')
    def test_modified_plan_after_owner_approval_rejected(self):
        grant=approval(self.plan);plan={**self.plan,'claim_evidence_sha256':'c'*64}
        self.assert_denied_unchanged('BINDING_MISMATCH',plan=plan,approval=grant)
    def test_wrong_tool_digest_rejected(self):self.assert_denied_unchanged('TOOL_HASH',tool_sha256='c'*64)
    def test_missing_approval_or_old_pilot_approval_cannot_authorize_close(self):
        for grant in (None,{}, {'kind':'OWNER_EXECUTION_APPROVAL','decision':'APPROVED','fresh_explicit_owner_execution_approval':True}):
            with self.subTest(grant=grant):self.assert_denied_unchanged('NOT_GRANTED',approval=grant)
    def test_expired_terminalization_approval_rejected_exclusive(self):
        self.assert_denied_unchanged('OUTSIDE_WINDOW',current=terminal.utc(self.plan['deadline_utc']))
    def test_expired_pilot_or_terminalization_approval_cannot_authorize_execution(self):
        with self.assertRaisesRegex(ValueError,'NOT_GRANTED'):dispatcher.verify_execution_approval(approval(self.plan),{},'b'*64,current=NOW)
    def test_terminalized_operation_cannot_retry_and_sealed_claim_reader_rejects(self):
        self.execute()
        with self.assertRaisesRegex(identity.OperationIdentityError,'RETIRED'):identity.validate_fresh_operation_id(self.plan['operation_id'])
        with patch.object(runtime,'CLAIM_PATH',self.claim),patch.object(runtime,'OPERATION',self.plan['operation_id']):
            with self.assertRaisesRegex(runtime.GateStop,'CLAIM_STATUS_INVALID'):runtime.read_claim(ATTEMPT)
    def test_live_image_protected_or_counter_drift_rejected_before_write(self):
        for key,value in (('target',{}),('protected_services_sha256','c'*64),('safety_counters',{}),('namespace_key_count',10693),('cohort_review_count',1),('writes',1)):
            with self.subTest(key=key):self.assert_denied_unchanged('LIVE_',verify_runtime=Mock(return_value={**self.live,key:value}))
    def test_wrong_expected_state_terminal_state_or_metadata_scope_rejected(self):
        for key,value in (('expected_current_state','DEPLOYED'),('terminal_state','CLAIMED'),('allowed_metadata_paths',self.plan['allowed_metadata_paths']+['operations/another.json'])):
            with self.subTest(key=key):
                with self.assertRaises(terminal.TerminalizationStop):terminal.verify_plan({**self.plan,key:value})
    def test_old_mutation_deadline_must_match_actual_claim(self):
        plan={**self.plan,'old_mutation_deadline_utc':(NOW-timedelta(hours=3)).isoformat()}
        self.assert_denied_unchanged('OLD_WINDOW_BINDING',plan=plan)
    def test_close_not_allowed_while_old_mutation_window_open(self):
        with self.assertRaisesRegex(terminal.TerminalizationStop,'STILL_OPEN'):terminal.verify_plan({**self.plan,'old_mutation_deadline_utc':(NOW+timedelta(minutes=1)).isoformat()})
    def test_interruption_after_state_write_is_fail_closed_not_retryable(self):
        original=terminal.replace_owned
        def interrupted(path,raw,expected):
            if path==self.claim:raise terminal.TerminalizationStop('LOCAL_FIXTURE_INTERRUPTION')
            return original(path,raw,expected)
        with patch.object(terminal,'replace_owned',side_effect=interrupted):
            with self.assertRaisesRegex(terminal.TerminalizationStop,'INTERRUPTION'):self.execute()
        self.assertEqual(terminal.decode(self.state.read_bytes())['status'],terminal.TERMINAL_STATE)
        self.assertEqual(terminal.decode(self.claim.read_bytes())['status'],'CLAIMED')
        self.assert_denied_unchanged('FILE_PRESENT')
        with self.assertRaises(identity.OperationIdentityError):identity.validate_fresh_operation_id(self.plan['operation_id'])
    def test_duplicate_json_keys_are_rejected(self):
        with self.assertRaisesRegex(terminal.TerminalizationStop,'DUPLICATE'):terminal.decode(b'{"status":"CLAIMED","status":"DEPLOYED"}')
    def test_readonly_preview_writes_nothing(self):
        before=self.bytes();terminal.observe_claim(self.root,self.plan,root_metadata=False);self.assertEqual(self.bytes(),before)

if __name__=='__main__':unittest.main()
