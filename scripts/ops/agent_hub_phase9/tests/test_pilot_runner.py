"""Compile all probes and prove preparation cannot enter action dispatch."""
import ast
import base64
from datetime import timedelta
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_bindings as gate
import pilot_dispatcher as dispatcher
import pilot_runner as runner
import render_runtime
import pilot_uat
from test_gate_bindings import HEAD, NOW, fixture

TEMPLATE=Path(__file__).resolve().parents[1]/'runtime_template.py'

class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'package';self.root.mkdir()
        self.baseline,self.anchor=fixture(self.root)
        self.verified=gate.verify_package(self.root,self.anchor,HEAD,self.baseline,current=NOW)
    def test_missing_approval_never_calls_transport_or_creates_claim(self):
        authority=Path(self.temp.name)/'authority'
        with patch.object(runner,'strict_argv',side_effect=AssertionError('transport reached')):
            with self.assertRaisesRegex(gate.GateStop,'NOT_GRANTED'):
                runner.execute(self.root,self.verified,{},self.anchor,None,None,authority,invoker=lambda *a,**kw:self.fail('remote called'))
        self.assertFalse(authority.exists())
    def test_preparation_exception_cannot_execute(self):
        approval=Path(self.temp.name)/'prep.json';approval.write_text(json.dumps({'kind':'OWNER_EVIDENCE_ONLY_EXCEPTION','decision':'APPROVED'}))
        with self.assertRaisesRegex(gate.GateStop,'NOT_GRANTED'):runner.authorize(self.root,self.verified,self.anchor,approval,None,current=NOW)
    def approval(self):
        return {'kind':'OWNER_EXECUTION_APPROVAL','decision':'APPROVED','fresh_explicit_owner_execution_approval':True,
            'operation_id':self.verified['bindings']['operation_id'],'candidate_head':HEAD,'package_manifest_sha256':self.anchor,
            'snapshot_sha256':self.verified['bindings']['snapshot_sha256'],'counter_evidence_sha256':self.verified['snapshot']['dependencies']['counter_receipt']['sha256'],
            'dependency_hashes':self.verified['bindings']['dependency_hashes'],'preparation_disposition_used_as_execution_approval':False,
            'window':dict(zip(('start_utc','latest_mutation_utc','decision_deadline_utc','recovery_deadline_utc'),
                ((NOW+timedelta(seconds=x)).isoformat() for x in (-1,60,120,180))))}
    def test_only_fully_bound_synthetic_approval_passes_verifier(self):
        dispatcher.verify_execution_approval(self.approval(),self.verified,self.anchor,current=NOW)
    def test_historical_identity_approval_denies(self):
        approval=self.approval();approval['operation_id']='ABORTED-HISTORICAL-OPERATION'
        with self.assertRaisesRegex(gate.GateStop,'BINDING_MISMATCH'):dispatcher.verify_execution_approval(approval,self.verified,self.anchor,current=NOW)
    def test_unbound_or_old_window_denies(self):
        for window in (None, {}, dict(zip(('start_utc','latest_mutation_utc','decision_deadline_utc','recovery_deadline_utc'),('2025-01-01T00:00:00Z','2025-01-01T01:00:00Z','2025-01-01T02:00:00Z','2025-01-01T03:00:00Z')))):
            with self.subTest(window=window),self.assertRaises(gate.GateStop):
                approval=self.approval();approval['window']=window
                dispatcher.verify_execution_approval(approval,self.verified,self.anchor,current=NOW)
    def test_missing_confirmation_denies_after_synthetic_approval(self):
        approval=Path(self.temp.name)/'synthetic-approval.json';approval.write_text(json.dumps(self.approval()))
        with patch.object(runner,'unprotect',side_effect=AssertionError('DPAPI reached')):
            with self.assertRaisesRegex(gate.GateStop,'CUSTODY_MISSING'):runner.authorize(self.root,self.verified,self.anchor,approval,None,current=NOW)
    def test_render_all_embedded_probes_compile(self):
        values={key:'a'*64 for key in render_runtime.BINDINGS.values()};values['candidate_archive_size']=1
        values['operation_id']='PHASE9-LIMITED-PILOT-RCA05-00000000-0000-4000-8000-000000000001'
        render_runtime.render(TEMPLATE,values)
    def test_template_unbound_no_historical_identity_or_window(self):
        text=TEMPLATE.read_text();tree=ast.parse(text)
        literals={t.id:n.value.value for n in tree.body if isinstance(n,ast.Assign) and isinstance(n.value,ast.Constant) for t in n.targets if isinstance(t,ast.Name)}
        for key in ('TOKEN_SHA','FRESH_BACKUP_MANIFEST_SHA','ROLLBACK_BUNDLE_MANIFEST_SHA','BASELINE_PROTECTED_SHA','NOT_BEFORE','LATEST_MUTATION','DECISION_DEADLINE','RECOVERY_DEADLINE'):
            self.assertIsNone(literals[key])
        self.assertEqual(literals['OPERATION'],'UNBOUND');self.assertNotIn('PHASE9-LIMITED-PILOT-FRESH-V2-20260911',text)
    def test_remote_template_aborts_before_authority_or_actions(self):
        spec=importlib.util.spec_from_file_location('synthetic_unbound_runtime',TEMPLATE);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with patch.object(module,'run',side_effect=AssertionError('remote command reached')):
            with self.assertRaises(module.GateStop):module.parse_envelope(base64.urlsafe_b64encode(b'{}').decode())
            with self.assertRaises(module.GateStop):module.claim({'invocation_id':'synthetic'})
    def test_confirmation_entropy_binds_operation_head_snapshot(self):
        a={'operation_id':'synthetic-A','candidate_head':HEAD,'snapshot_sha256':'a'*64}
        for field in a:
            b={**a,field:'other'};self.assertNotEqual(runner.confirmation_entropy(a),runner.confirmation_entropy(b))
    @unittest.skipUnless(os.name=='nt','CurrentUser DPAPI is Windows-only')
    def test_native_currentuser_dpapi_roundtrip_and_wrong_entropy_denies(self):
        raw=os.urandom(32);entropy=b'clearly-synthetic-native-custody-test'
        blob=runner.protect(raw,entropy);self.assertNotEqual(blob,raw)
        self.assertEqual(runner.unprotect(blob,entropy),raw)
        with self.assertRaises(gate.GateStop):runner.unprotect(blob,b'other-entropy')
    def test_empty_browser_and_api_uat_never_pass(self):
        pilot_uat.configure({'operation_id':'SYNTHETIC','subject_ref_sha256':'a'*64,'role_email_sha256':{},'candidate_runtime_ids':[]},self.approval())
        value=pilot_uat.evaluate({},{},{},{},{})
        self.assertEqual(value['status'],'FAIL');self.assertIn('browser_all',value['failures'])

if __name__=='__main__':unittest.main()
