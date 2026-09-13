"""Local-only CLI, exact old guard reproduction and recovered custody checks."""
import ast
import base64
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))
import baseline_compose_context as bc
import operation_identity as identity
import render_runtime
import remote_preflight_capture as capture
import pilot_runner as runner
import pilot_dispatcher as dispatcher
from test_gate_bindings import fixture as package_fixture, HEAD, NOW, write, reseal_outer
import gate_bindings as gate

FRESH = 'PHASE9-LIMITED-PILOT-RCA06-00000000-0000-4000-8000-000000000011'  # Synthetic only.
ATTEMPT = '313c7a37-63cd-4575-8205-e8fe90e3a156'

def recovered_fixture():
    op = identity.RECOVERED_TERMINAL_OPERATION; root = PurePosixPath(bc.COMPOSE_CLAIM_ROOT); directory = root / 'attempts' / op
    claim = {'status':'CLAIMED','operation_id':op,'claim_id':ATTEMPT,'invocation_id':ATTEMPT,'reset_for_retry_allowed':False}
    state = {'status':'ROLLED_BACK_VERIFIED','operation_id':op,'invocation_id':ATTEMPT,'candidate_deployment_retry_allowed':False,
        'target_mutation_attempted':True,'rollback_verification':{'target':{'image_id':bc.COMPOSE_ROLLBACK_CONFIG}}}
    raw = {str(root / 'operations' / (op + '.json')):json.dumps(claim).encode(),
        str(directory / 'state.json'):json.dumps(state).encode(),
        str(directory / 'rollback-override.json'):b'{"services":{"agent-hub":{"image":"npd-agent-hub:phase5"}}}'}
    value = {'schema':bc.COMPOSE_BINDING_SCHEMA,'provenance_only':True,'execution_authorized':False,'operation_id':op,'attempt_id':ATTEMPT,
        'terminal_state':'ROLLED_BACK_VERIFIED','claim_state':'CLAIMED','rollback_image_config':bc.COMPOSE_ROLLBACK_CONFIG,
        'container_id':'7'*64,'target_signature_sha256':hashlib.sha256(b'{}').hexdigest(),
        'config_files':[bc.COMPOSE_BASE_PATH,str(directory / 'rollback-override.json')],
        'metadata_sha256':{k:hashlib.sha256(v).hexdigest() for k,v in raw.items()},'recovery_receipt_sha256':'a'*64,'source_observation_sha256':'b'*64}
    item = {'Id':value['container_id'],'Image':bc.COMPOSE_ROLLBACK_CONFIG,'Config':{'Image':'npd-agent-hub:phase5',
        'Env':['VIDEO_API_URL=http://fixture.invalid','AGENT_REDIS_URL=redis://fixture.invalid/11','AGENT_STORE_NAMESPACE=fixture'],
        'Labels':{'com.docker.compose.project.config_files':','.join(value['config_files']),
            'com.docker.compose.project.working_dir':'/fixture'}},
        'Mounts':[{'Destination':name,'Source':'/fixture/'+str(i),'Type':'bind','RW':False} for i,name in enumerate(
            ['/run/secrets/ga4-service-account.json','/run/secrets/agent-attribution-verification-keys.json'])],
        'NetworkSettings':{'Networks':{'npd-ai-video-factory_default':{},'n8n-marketing_n8n_net':{}}},
        'HostConfig':{'PortBindings':{'8010/tcp':[{'HostIp':'127.0.0.1','HostPort':'8010'}]}}}
    return value, raw, item

def verify(value, raw, item, paths=None):
    return bc.verify_recovered_compose(value,item,paths or value['config_files'],bc.COMPOSE_BASE_PATH,bc.COMPOSE_CLAIM_ROOT,
        bc.COMPOSE_ROLLBACK_CONFIG,'npd-agent-hub:phase5',value['target_signature_sha256'],custody_reader=lambda *a:raw)

class RecoveredComposeTests(unittest.TestCase):
    def test_exact_terminal_custody_passes_only_as_provenance(self):
        value,raw,item=recovered_fixture();self.assertTrue(verify(value,raw,item));self.assertFalse(value['execution_authorized'])
        with self.assertRaises(identity.OperationIdentityError):identity.validate_fresh_operation_id(value['operation_id'])
    def test_original_failure_is_exact_exit_two_stdout_hash_not_argparse(self):
        fixture=json.loads((OPS/'tests/fixtures/preflight_child_exit2.json').read_bytes())
        program='''import json,sys
sys.stdout.reconfigure(encoding='utf-8',newline='\\n')
f=json.loads(sys.argv[1])
if f['actual_config_files'] not in f['old_allowed_paths']:
 print(json.dumps({'status':'ABORTED_FAIL_CLOSED','reason':'COMPOSE_FILE_LABEL_DRIFT','operation_id':f['operation_id'],'raw_sensitive_output':False},sort_keys=True))
 raise SystemExit(2)
raise SystemExit('old guard unexpectedly passed')
'''
        p=subprocess.run([sys.executable,'-B','-c',program,json.dumps(fixture)],capture_output=True,shell=False)
        self.assertEqual(p.returncode,2);self.assertEqual(p.stderr,b'');self.assertEqual(len(p.stdout),186)
        self.assertEqual(hashlib.sha256(p.stdout).hexdigest(),fixture['original_stdout_sha256'])
    def test_missing_binding_keeps_old_guard_fail_closed(self):
        spec=importlib.util.spec_from_file_location('local_compose_runtime',OPS/'runtime_template.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        value,raw,item=recovered_fixture()
        with self.assertRaisesRegex(m.GateStop,'COMPOSE_FILE_LABEL_DRIFT'):m.compose_context(item,'npd-agent-hub:phase5')
    def test_actual_runtime_context_preserves_network_mount_port_checks(self):
        spec=importlib.util.spec_from_file_location('local_valid_compose_runtime',OPS/'runtime_template.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        value,raw,item=recovered_fixture();m.BASELINE_COMPOSE_BINDING_JSON=json.dumps(value)
        m.BASE_COMPOSE=PurePosixPath(bc.COMPOSE_BASE_PATH);m.CLAIM_ROOT=PurePosixPath(bc.COMPOSE_CLAIM_ROOT)
        with patch.object(m,'Path',PurePosixPath),patch.object(m,'container_signature',return_value={}),\
            patch.object(m,'verify_recovered_compose',side_effect=lambda *a:bc.verify_recovered_compose(*a,custody_reader=lambda *a:raw)),\
            patch.object(m,'protected_file'),patch.object(m,'run',return_value=b'{"services":{"agent-hub":{"image":"npd-agent-hub:phase5"}}}'):
            command,env,base=m.compose_context(item,'npd-agent-hub:phase5');self.assertEqual(command[:2],['docker','compose'])
            for change,reason in [('NetworkSettings','NETWORK_SET_DRIFT'),('Mounts','SECRET_MOUNT_SET_DRIFT'),('HostConfig','PORT_BINDING_DRIFT')]:
                bad=copy.deepcopy(item);bad[change]={} if change!='Mounts' else []
                with self.subTest(change=change),self.assertRaisesRegex(m.GateStop,reason):m.compose_context(bad,'npd-agent-hub:phase5')
    def test_binding_shape_authority_paths_family_attempt_and_hashes_reject(self):
        value,raw,item=recovered_fixture()
        changes=[{'execution_authorized':True},{'extra':True},{'operation_id':FRESH},{'attempt_id':'bad'},
            {'terminal_state':'DEPLOYED_VERIFIED_UAT_PENDING'},{'container_id':'bad'},
            {'config_files':[bc.COMPOSE_BASE_PATH,'/other/rollback-override.json']},{'metadata_sha256':{}},
            {'rollback_image_config':'sha256:'+'f'*64}]
        for change in changes:
            with self.subTest(change=change),self.assertRaises(ValueError):verify({**value,**change},raw,item)
    def test_wrong_container_signature_image_and_extra_label_reject(self):
        value,raw,item=recovered_fixture()
        for bad in ({**item,'Id':'0'*64},{**item,'Image':'other'}, {**item,'Config':{'Image':'other'}}):
            with self.subTest(item=bad),self.assertRaises(bc.ComposeBindingError):verify(value,raw,bad)
        with self.assertRaises(bc.ComposeBindingError):verify(value,raw,item,value['config_files']+['/extra'])
        with self.assertRaises(bc.ComposeBindingError):bc.verify_recovered_compose(value,item,value['config_files'],bc.COMPOSE_BASE_PATH,
            bc.COMPOSE_CLAIM_ROOT,bc.COMPOSE_ROLLBACK_CONFIG,'npd-agent-hub:phase5','c'*64,lambda *a:raw)
    def test_modified_truncated_missing_extra_custody_rejects(self):
        value,raw,item=recovered_fixture();name=next(iter(raw))
        for bad in ({**raw,name:raw[name]+b' '},{**raw,name:raw[name][:-1]}, {}, {**raw,'/extra':b'{}'}):
            with self.subTest(raw=bad),self.assertRaises(bc.ComposeBindingError):verify(value,bad,item)
    def test_rebound_hash_cannot_hide_wrong_owner_stage_deploy_retry_or_override(self):
        value,raw,item=recovered_fixture();directory=PurePosixPath(bc.COMPOSE_CLAIM_ROOT)/'attempts'/value['operation_id']
        changes=[('state.json',{'status':'CLAIMED'}),('state.json',{'status':'STAGED'}),('state.json',{'status':'DEPLOYED_VERIFIED_UAT_PENDING'}),
            ('state.json',{'invocation_id':'00000000-0000-4000-8000-000000000012'}),('state.json',{'candidate_deployment_retry_allowed':True}),
            ('rollback-override.json',{'ports':['9999:9999']})]
        for filename,change in changes:
            name=str(directory/filename);obj=json.loads(raw[name]);obj.update(change);bad={**raw,name:json.dumps(obj).encode()}
            bound={**value,'metadata_sha256':{k:hashlib.sha256(v).hexdigest() for k,v in bad.items()}}
            with self.subTest(change=change),self.assertRaises(bc.ComposeBindingError):verify(bound,bad,item)
    def test_missing_file_never_becomes_empty_custody(self):
        value,raw,item=recovered_fixture()
        with self.assertRaises((OSError,bc.ComposeBindingError)):bc.read_compose_custody(value,bc.COMPOSE_CLAIM_ROOT)
    @unittest.skipUnless(os.name=='posix','Linux ownership/symlink custody')
    def test_real_local_read_rejects_nonroot_or_nonprivate_custody(self):
        # A local temporary tree only; no production path is read.
        value,raw,item=recovered_fixture()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);root.chmod(0o700);mapped={}
            for i,content in enumerate(raw.values()):
                path=root/str(i);path.write_bytes(content);path.chmod(0o600);mapped[str(path)]=hashlib.sha256(content).hexdigest()
            bound={**value,'metadata_sha256':mapped}
            if os.geteuid() != 0:
                with self.assertRaises(bc.ComposeBindingError):bc.read_compose_custody(bound,root)
                return
            self.assertEqual(len(bc.read_compose_custody(bound,root)),3)
            path=root/'0';path.chmod(0o644)
            with self.assertRaises(bc.ComposeBindingError):bc.read_compose_custody(bound,root)
    def test_renderer_inlines_same_contract_and_exact_context(self):
        value,raw,item=recovered_fixture();profile={k:'a'*64 for k in render_runtime.BINDINGS.values()}
        profile.update(operation_id=FRESH,candidate_archive_size=1,baseline_compose_binding=value)
        program=render_runtime.render(OPS/'runtime_template.py',profile);m={'__name__':'local_rendered'};exec(program,m)
        self.assertEqual(json.loads(m['BASELINE_COMPOSE_BINDING_JSON']),value);self.assertEqual(m['BASELINE_TARGET_ID'],value['container_id'])
        self.assertNotIn('from baseline_compose_context',program.decode())
        for operation in identity.RETIRED_EXECUTION_OPERATIONS:
            with self.assertRaises(identity.OperationIdentityError):render_runtime.render(OPS/'runtime_template.py',{**profile,'operation_id':operation})
    def test_gate_requires_package_bound_context_and_provenance(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);baseline,anchor=package_fixture(root);profile=json.loads((root/'RUNTIME_PROFILE.json').read_bytes())
            profile['baseline_compose_binding']=recovered_fixture()[0];(root/'RUNTIME_PROFILE.json').write_text(json.dumps(profile))
            with self.assertRaises(gate.GateStop):gate.verify_package(root,anchor,HEAD,baseline,current=NOW)
    def test_fully_resealed_synthetic_context_binds_gate_to_runtime(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);baseline,anchor=package_fixture(root);context,raw,item=recovered_fixture()
            for name in ['PROTECTED_BASELINE.json','COUNTER_EVIDENCE.json']:
                obj=gate.load(root/'evidence'/name)
                if name=='PROTECTED_BASELINE.json':obj['target']['id']=context['container_id']
                else:obj['source_agent_hub_container_id']=context['container_id']
                write(root/'evidence'/name,obj)
            transported=json.dumps(gate.load(root/'evidence/COUNTER_EVIDENCE.json'),sort_keys=True).encode()+b'\n'
            transport=gate.load(root/'evidence/COUNTER_TRANSPORT.json');transport['stdout']={'sha256':hashlib.sha256(transported).hexdigest(),'length_bytes':len(transported)}
            write(root/'evidence/COUNTER_TRANSPORT.json',transport)
            snapshot=gate.load(root/'evidence/FULL_EXECUTION_SNAPSHOT.json')
            for entry in snapshot['dependencies'].values():entry['sha256']=gate.sha(root/'evidence'/entry['path'])
            write(root/'evidence/FULL_EXECUTION_SNAPSHOT.json',snapshot);snapshot_sha=gate.sha(root/'evidence/FULL_EXECUTION_SNAPSHOT.json')
            write(root/'evidence/COMPLETED_RECOVERY_RECEIPT.json',{'fixture_only':True})
            write(root/'evidence/RECOVERED_COMPOSE_READONLY.json',{'fixture_only':True})
            context['recovery_receipt_sha256']=gate.sha(root/'evidence/COMPLETED_RECOVERY_RECEIPT.json')
            context['source_observation_sha256']=gate.sha(root/'evidence/RECOVERED_COMPOSE_READONLY.json')
            write(root/'evidence/BASELINE_COMPOSE_BINDING.json',context)
            for name in ['PILOT_PAYLOAD.json','CONFIRMATION_CONTRACT.json','RUNTIME_PROFILE.json']:
                obj=gate.load(root/name);obj['snapshot_sha256']=snapshot_sha;obj['counter_evidence_sha256']=gate.sha(root/'evidence/COUNTER_EVIDENCE.json')
                if name=='RUNTIME_PROFILE.json':obj['baseline_compose_binding']=context
                write(root/name,obj)
            runtime=("BASELINE_COMPOSE_BINDING_JSON = "+repr(json.dumps(context))+"\nBASELINE_TARGET_ID = "+repr(context['container_id'])+
                "\nBASELINE_TARGET_SIGNATURE_SHA = "+repr(context['target_signature_sha256'])+"\n")
            (root/'remote_runtime.py').write_text(runtime)
            def reseal():
                bindings=gate.load(root/'OPERATION_BINDINGS.json');bindings['snapshot_sha256']=snapshot_sha
                names=(set(bindings['dependency_hashes'])|{'evidence/BASELINE_COMPOSE_BINDING.json',
                    'evidence/COMPLETED_RECOVERY_RECEIPT.json','evidence/RECOVERED_COMPOSE_READONLY.json'})-{'ARTIFACT_MANIFEST.json'}
                hashes={name:gate.sha(root/name) for name in names};write(root/'ARTIFACT_MANIFEST.json',{'artifact_hashes':hashes})
                hashes['ARTIFACT_MANIFEST.json']=gate.sha(root/'ARTIFACT_MANIFEST.json');bindings['dependency_hashes']=hashes;write(root/'OPERATION_BINDINGS.json',bindings)
                manifest=gate.load(root/'PACKAGE_MANIFEST.json');manifest['snapshot_sha256']=snapshot_sha;reseal_outer(root,manifest)
                return gate.sha(root/'PACKAGE_MANIFEST.json')
            anchor=reseal();gate.verify_package(root,anchor,HEAD,baseline,current=NOW)
            (root/'remote_runtime.py').write_text(runtime.replace(context['container_id'],'0'*64));anchor=reseal()
            with self.assertRaisesRegex(gate.GateStop,'RUNTIME_BINDING_MISMATCH'):gate.verify_package(root,anchor,HEAD,baseline,current=NOW)

class PreflightChildDiagnosticsTests(unittest.TestCase):
    def test_known_guard_retains_raw_before_precise_abort_never_success(self):
        op=FRESH;raw=(json.dumps({'status':'ABORTED_FAIL_CLOSED','reason':'COMPOSE_FILE_LABEL_DRIFT','operation_id':op,
            'raw_sensitive_output':False},sort_keys=True)+'\n').encode()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(capture.CaptureStop) as caught:
                capture.invoke_preflight(lambda *a,**k:subprocess.CompletedProcess([],2,raw,b''),['ssh'],input_bytes=b'fixture',timeout=1,
                    evidence_directory=Path(directory),binding_id=op,retain_raw_stdout=True,
                    success_verifier=lambda _:self.fail('nonzero verifier called'))
            error=caught.exception;receipt=json.loads(error.capture_path.read_bytes())
            self.assertEqual((Path(directory)/receipt['raw_stdout_file']).read_bytes(),raw)
            self.assertEqual(error.diagnostic['classification'],'REMOTE_RUNTIME_GUARD:COMPOSE_FILE_LABEL_DRIFT')
            self.assertIn('exit=2',str(error));self.assertIn('stderr=EMPTY',str(error))
    def test_unknown_output_and_secret_stderr_remain_opaque(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(capture.CaptureStop) as caught:
                capture.invoke_preflight(lambda *a,**k:subprocess.CompletedProcess([],2,b'fixture-only-private',b'fixture-only-private'),
                    ['ssh'],input_bytes=b'fixture',timeout=1,evidence_directory=Path(directory),binding_id=FRESH,retain_raw_stdout=True)
            self.assertNotIn(b'fixture-only-private',caught.exception.capture_path.read_bytes())
            self.assertFalse(list(Path(directory).glob('*.stdout.bin')))
            self.assertIsNone(json.loads(caught.exception.capture_path.read_bytes())['raw_stdout_file'])
    def test_invalid_safe_context_rejects_before_child(self):
        with tempfile.TemporaryDirectory() as directory,self.assertRaises(capture.CaptureStop):
            capture.invoke_preflight(lambda *a,**k:self.fail('child reached'),[],input_bytes=b'',timeout=1,evidence_directory=Path(directory),
                binding_id=FRESH,invocation_context={'secret':'fixture'})
    def test_runner_dispatcher_share_child_correlation_and_safe_context(self):
        with tempfile.TemporaryDirectory() as directory:
            package=Path(directory);(package/'remote_runtime.py').write_bytes(b'fixture')
            with patch.object(runner,'strict_argv',return_value=['pinned-ssh']),patch.object(runner,'dispatch_preflight') as dispatch:
                runner.observe(package,{}, {'candidate_head':'a'*40,'protected_services_sha256':'b'*64},'c'*64,
                    {'invocation_id':ATTEMPT},package)
                options=dispatch.call_args.kwargs;self.assertEqual(options['invocation_id'],ATTEMPT)
                self.assertEqual(options['invocation_context']['remote_argv_shape'][-1],'<redacted binding envelope>')

class RuntimeCLIRejectionTests(unittest.TestCase):
    def test_valid_current_preflight_invocation_reaches_real_context_guard(self):
        context,raw,item=recovered_fixture();profile={k:'a'*64 for k in render_runtime.BINDINGS.values()}
        profile.update(operation_id=FRESH,candidate_archive_size=1,baseline_compose_binding=context)
        m={'__name__':'local_valid_preflight'};exec(render_runtime.render(OPS/'runtime_template.py',profile),m)
        env={k:'0'*64 for k in m['GOVERNANCE_HASH_FIELDS']}
        for key,name in {'confirmation_token_sha256':'TOKEN_SHA','fresh_backup_manifest_sha256':'FRESH_BACKUP_MANIFEST_SHA',
            'rollback_bundle_manifest_sha256':'ROLLBACK_BUNDLE_MANIFEST_SHA','main_sha':'MAIN_SHA','candidate_head':'CANDIDATE_HEAD',
            'snapshot_sha256':'SNAPSHOT_SHA','counter_evidence_sha256':'COUNTER_EVIDENCE_SHA','protected_services_sha256':'BASELINE_PROTECTED_SHA',
            'owner_exception_receipt_sha256':'OWNER_EXCEPTION_SHA','execution_window_sha256':'EXECUTION_WINDOW_SHA'}.items():env[key]=m[name]
        env.update(schema=identity.DISPATCH_SCHEMA,operation_id=FRESH,invocation_id=ATTEMPT,preflight_readonly=True)
        m['BASE_COMPOSE']=PurePosixPath(bc.COMPOSE_BASE_PATH);m['CLAIM_ROOT']=PurePosixPath(bc.COMPOSE_CLAIM_ROOT);m['Path']=PurePosixPath
        m['container_signature']=lambda _:{};m['protected_file']=lambda *a:None
        m['run']=lambda *a,**k:b'{"services":{"agent-hub":{"image":"npd-agent-hub:phase5"}}}'
        m['verify_recovered_compose']=lambda *a:bc.verify_recovered_compose(*a,custody_reader=lambda *a:raw)
        def baseline(*,exact_container):
            self.assertTrue(exact_container);m['compose_context'](item,'npd-agent-hub:phase5')
            return {'target':item,'routes':{},'safety':{name:0 for name in m['SAFETY_COUNTERS']}}
        m['verify_baseline']=baseline;m['public_identity']=lambda _: {'container_id':context['container_id']}
        import contextlib,io
        output=io.StringIO()
        with patch.object(sys,'argv',['-','preflight',runner.encode(env)]),contextlib.redirect_stdout(output):m['main']()
        result=json.loads(output.getvalue());self.assertEqual(result['status'],'PASS');self.assertTrue(result['claim_absent'])
        self.assertFalse(result['production_mutation']);self.assertEqual(result['operation_id'],FRESH)
    def test_missing_unknown_arguments_malformed_envelope_and_wrong_operation_fail_closed(self):
        profile={k:'a'*64 for k in render_runtime.BINDINGS.values()};profile.update(operation_id=FRESH,candidate_archive_size=1)
        program=render_runtime.render(OPS/'runtime_template.py',profile)
        cases=[([], 'USAGE_INVALID'),(['--unknown'],'USAGE_INVALID'),(['preflight'],'USAGE_INVALID'),
            (['preflight','bad','extra'],'USAGE_INVALID'),(['preflight','bad'],'AUTHORIZATION_ENVELOPE_INVALID'),
            (['preflight',base64.urlsafe_b64encode(json.dumps({'schema':identity.DISPATCH_SCHEMA,'operation_id':'other'}).encode()).decode()],
                'AUTHORIZATION_OPERATION_MISMATCH')]
        for args,reason in cases:
            with self.subTest(args=args):
                p=subprocess.run([sys.executable,'-B','-',*args],input=program,capture_output=True,shell=False)
                self.assertEqual(p.returncode,2);self.assertEqual(p.stderr,b'');self.assertEqual(json.loads(p.stdout)['reason'],reason)

if __name__=='__main__':unittest.main()
