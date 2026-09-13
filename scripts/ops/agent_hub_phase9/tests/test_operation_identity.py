"""Synthetic identities/approvals; no real transport, claims, packages or CI."""
from datetime import timedelta
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_bindings as gate
import pilot_dispatcher as dispatcher
import pilot_runner as runner
import pilot_transport as transport
import render_runtime
import operation_identity as identity
from test_gate_bindings import HEAD, NOW, fixture, write, reseal_outer

def approval(verified, anchor):
    return {'kind':'OWNER_EXECUTION_APPROVAL','decision':'APPROVED','fresh_explicit_owner_execution_approval':True,
        'operation_id':verified['bindings']['operation_id'],'candidate_head':HEAD,'package_manifest_sha256':anchor,
        'snapshot_sha256':verified['bindings']['snapshot_sha256'],'counter_evidence_sha256':verified['snapshot']['dependencies']['counter_receipt']['sha256'],
        'dependency_hashes':verified['bindings']['dependency_hashes'],'execution_window_sha256':verified['bindings']['dependency_hashes']['EXECUTION_WINDOW.json'],
        'window':{name:verified['window'][name] for name in gate.WINDOW_FIELDS},'preparation_disposition_used_as_execution_approval':False,
        'owner_authorization_receipt_sha256':'a'*64}

class IdentityAndStageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'synthetic-package';self.root.mkdir()
        self.baseline,self.anchor=fixture(self.root,family='RCA06')
        self.verified=gate.verify_package(self.root,self.anchor,HEAD,self.baseline,current=NOW)
        self.operation=self.verified['bindings']['operation_id'];self.profile=gate.load(self.root/'RUNTIME_PROFILE.json')
        self.profile['transport']={'scp_executable':'synthetic-scp','identity_file':'synthetic-identity','known_hosts_client_path':'synthetic-pinned-file'}
    def test_current_family_gate_dispatcher_and_stage_binding_passes(self):
        expected={'status':'PASS','mode':'preflight','operation_id':self.operation,'candidate_head':HEAD,
            'snapshot_sha256':self.verified['manifest']['snapshot_sha256'],'counter_evidence_sha256':self.verified['snapshot']['dependencies']['counter_receipt']['sha256'],
            'protected_services_sha256':self.baseline,'package_manifest_sha256':self.anchor,'safety_counters':self.verified['snapshot']['safety_counters'],
            'checked_at':NOW.isoformat(),'claim_absent':True,'candidate_staged':False,'production_mutation':False,'business_system_write':False,
            'raw_secrets_accounts_keys_values_or_pii_emitted':False}
        invoker=Mock(return_value=subprocess.CompletedProcess([],0,json.dumps(expected).encode(),b''))
        value,_=dispatcher.dispatch_preflight(invoker,['synthetic-no-network'],package=self.root,expected_manifest=self.anchor,
            expected_head=HEAD,expected_baseline=self.baseline,input_bytes=b'synthetic',evidence_directory=Path(self.temp.name)/'captures',current=NOW)
        self.assertEqual(value['operation_id'],self.operation)
        dispatcher.verify_execution_approval(approval(self.verified,self.anchor),self.verified,self.anchor,current=NOW,phase='dispatch')
        with patch.object(transport,'strict_argv',return_value=['local-only']) as trust:
            argv=transport.stage_argv(self.profile,Path('space name/candidate.oci.tar'),self.operation)
        trust.assert_called_once_with(self.profile,['true']);self.assertIn(self.operation,argv[-1])
        self.assertEqual(argv[-2],str(Path('space name/candidate.oci.tar')))
    def test_supported_families_have_canonical_uuid_v4(self):
        for family in identity.SUPPORTED_FAMILIES:
            operation=f'PHASE9-LIMITED-PILOT-{family}-'+str(uuid4())
            self.assertEqual(identity.validate_fresh_operation_id(operation),operation)
    def test_malformed_uuid_prefix_family_and_injection_rejected(self):
        suffix=str(uuid4())
        for value in (None,42,'','PHASE9-LIMITED-PILOT-RCA07-'+suffix,'PHASE9-LIMITED-PILOT-RCA06-'+'-'*36,
            'PHASE9-LIMITED-PILOT-RCA06-'+suffix.upper(),self.operation+'/../escape',self.operation+';touch /tmp/x',self.operation+'\n',
            'PHASE9-LIMITED-PILOT-RCA06-00000000-0000-1000-8000-000000000000'):
            with self.subTest(value=value),self.assertRaises(identity.OperationIdentityError):identity.validate_fresh_operation_id(value)
    def test_consumed_aborted_operation_is_denied_even_with_fresh_synthetic_bindings(self):
        root=Path(self.temp.name)/'aborted-fixture';root.mkdir();baseline,anchor=fixture(root,operation=identity.CONSUMED_ABORTED_OPERATION)
        with self.assertRaisesRegex(gate.GateStop,'RETIRED_NOT_REUSABLE'):gate.verify_package(root,anchor,HEAD,baseline,current=NOW)
        with self.assertRaisesRegex(gate.GateStop,'RETIRED_NOT_REUSABLE'):
            transport.stage_argv({'operation_id':identity.CONSUMED_ABORTED_OPERATION},root/'candidate.oci.tar',identity.CONSUMED_ABORTED_OPERATION)
    def test_stale_rca05_package_rejected(self):
        root=Path(self.temp.name)/'stale-rca05';root.mkdir();baseline,anchor=fixture(root,family='RCA05')
        with self.assertRaisesRegex(gate.GateStop,'STALE_OR_FUTURE'):gate.verify_package(root,anchor,HEAD,baseline,current=NOW+timedelta(seconds=601))
    def test_expired_rca06_dispatch_deadline_rejected_while_counter_not_stale(self):
        with self.assertRaises(gate.GateStop):dispatcher.verify_execution_approval(approval(self.verified,self.anchor),self.verified,self.anchor,current=NOW+timedelta(seconds=301),phase='dispatch')
    def test_operation_not_present_in_bindings_rejected(self):
        value=gate.load(self.root/'OPERATION_BINDINGS.json');value['operation_id']='PHASE9-LIMITED-PILOT-RCA06-'+str(uuid4());write(self.root/'OPERATION_BINDINGS.json',value);reseal_outer(self.root)
        with self.assertRaisesRegex(gate.GateStop,'OPERATION_BINDING'):gate.verify_package(self.root,gate.sha(self.root/'PACKAGE_MANIFEST.json'),HEAD,self.baseline,current=NOW)
    def test_another_package_approval_rejected(self):
        root=Path(self.temp.name)/'other-package';root.mkdir();baseline,anchor=fixture(root,family='RCA06');verified=gate.verify_package(root,anchor,HEAD,baseline,current=NOW)
        with self.assertRaisesRegex(gate.GateStop,'BINDING_MISMATCH'):dispatcher.verify_execution_approval(approval(self.verified,self.anchor),verified,anchor,current=NOW)
    def test_modified_operation_after_approval_rejected(self):
        grant=approval(self.verified,self.anchor);grant['operation_id']='PHASE9-LIMITED-PILOT-RCA06-'+str(uuid4())
        with self.assertRaisesRegex(gate.GateStop,'BINDING_MISMATCH'):dispatcher.verify_execution_approval(grant,self.verified,self.anchor,current=NOW)
    def test_stage_wrong_profile_operation_rejected_before_trust(self):
        with patch.object(transport,'strict_argv',side_effect=AssertionError('trust reached')):
            with self.assertRaisesRegex(gate.GateStop,'STAGE_OPERATION_BINDING'):
                transport.stage_argv(self.profile,self.root/'candidate.oci.tar','PHASE9-LIMITED-PILOT-RCA06-'+str(uuid4()))
    def test_transport_mismatch_rejected_before_preflight_claim_publish(self):
        authority=Path(self.temp.name)/'not-created';grant=Path(self.temp.name)/'unit-approval';grant.write_text('{}')
        invoker=Mock(side_effect=AssertionError('remote reached'))
        with patch.object(runner,'authorize',return_value=approval(self.verified,self.anchor)),patch.object(runner,'envelope_for',return_value={}),patch.object(runner,'verify_execution_approval'),patch.object(runner,'stage_argv',side_effect=gate.GateStop('STAGE_CONTRACT_INVALID')),patch.object(runner,'observe',side_effect=AssertionError('preflight reached')),patch.object(runner,'publish',side_effect=AssertionError('publish reached')):
            with self.assertRaisesRegex(gate.GateStop,'STAGE_CONTRACT_INVALID'):runner.execute(self.root,self.verified,self.profile,self.anchor,grant,None,authority,invoker=invoker)
        invoker.assert_not_called();self.assertFalse(authority.exists())
    def test_consumed_approval_same_operation_cannot_dispatch_twice(self):
        authority=Path(self.temp.name)/'authority';authority.mkdir();write(authority/'DISPATCH_CLAIM.json',{'operation_id':self.operation})
        grant=Path(self.temp.name)/'unit-approval';grant.write_text('{}');invoker=Mock(side_effect=AssertionError('remote reached'))
        with patch.object(runner,'authorize',return_value=approval(self.verified,self.anchor)),patch.object(runner,'envelope_for',return_value={}):
            with self.assertRaisesRegex(gate.GateStop,'LOCAL_OPERATION_ALREADY_DISPATCHED'):runner.execute(self.root,self.verified,self.profile,self.anchor,grant,None,authority,invoker=invoker)
        invoker.assert_not_called()
    def test_rendered_remote_uses_same_contract_without_import_dependency(self):
        profile={key:'a'*64 for key in render_runtime.BINDINGS.values()};profile['candidate_archive_size']=1;profile['operation_id']=self.operation
        output=render_runtime.render(Path(render_runtime.__file__).with_name('runtime_template.py'),profile)
        self.assertNotIn(b'from operation_identity import',output)
        scope={'__name__':'synthetic_runtime_contract'};exec(compile(output,'unit_runtime','exec'),scope)
        self.assertEqual(scope['SUPPORTED_FAMILIES'],identity.SUPPORTED_FAMILIES)
        self.assertEqual(scope['validate_fresh_operation_id'](self.operation),self.operation)
        with self.assertRaises(scope['OperationIdentityError']):scope['validate_fresh_operation_id'](identity.CONSUMED_ABORTED_OPERATION)
    def test_retired_operation_cannot_be_rendered(self):
        with self.assertRaisesRegex(identity.OperationIdentityError,'RETIRED'):render_runtime.render('not-read',{'operation_id':identity.CONSUMED_ABORTED_OPERATION})

if __name__=='__main__':unittest.main()
