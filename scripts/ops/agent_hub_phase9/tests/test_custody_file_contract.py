"""Selected TemporaryDirectory fixtures only; no SSH, authority or production."""
import hashlib
from pathlib import Path
import sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from custody_file_contract import (CustodyFileStop,LocalFileCustodyFixture,custody_file_scope,custody_file_writer)
import remote_preflight_capture as capture


@custody_file_writer
def write(path,raw):path.write_bytes(raw)


@custody_file_writer
def partial(path):
    path.write_bytes(b'partial-owned-local')
    raise OSError('synthetic fixture failure')


class FileCustodyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.path=self.root/'owned.json'
        self.registry=LocalFileCustodyFixture(self.root)
    def test_default_hold_precedes_any_publication(self):
        with self.assertRaisesRegex(CustodyFileStop,'NOT_CONFIGURED'):capture._publish(self.root,'synthetic-correlation',{})
        self.assertFalse(list(self.root.iterdir()))
    def test_raw_versions_retained_no_semantic_substitution(self):
        raw=b' {"raw": 1}\r\n'
        self.path.write_bytes(raw)
        with custody_file_scope(self.registry):write(self.path,b'{"raw":1}\n')
        self.assertEqual(self.registry.raw_versions[(str(self.path),hashlib.sha256(raw).hexdigest())],raw)
        self.assertEqual(len(self.registry.raw_versions),2)
        self.assertFalse(self.registry.execution_authorized)
    def test_reference_registration_precedes_io(self):
        events=[];self.registry.register_reference=events.append
        self.registry.bind_reference(self.path,'exact-owned-raw-identity')
        with custody_file_scope(self.registry):
            write(self.path,b'first');write(self.path,b'second')
        self.assertEqual(events,['exact-owned-raw-identity'])
    def test_missing_registry_stops_before_io(self):
        self.registry.bind_reference(self.path,'missing-registry')
        with custody_file_scope(self.registry),self.assertRaisesRegex(CustodyFileStop,'REGISTRY_MISSING'):write(self.path,b'new')
        self.assertFalse(self.path.exists())
    def test_archive_failure_stops_before_replacement(self):
        self.path.write_bytes(b'original');self.registry.fail_archive=True
        with custody_file_scope(self.registry),self.assertRaisesRegex(CustodyFileStop,'ARCHIVE_UNAVAILABLE'):write(self.path,b'new')
        self.assertEqual(self.path.read_bytes(),b'original')
    def test_modified_local_archive_rejected(self):
        raw=b'original';self.path.write_bytes(raw)
        self.registry.raw_versions[(str(self.path),hashlib.sha256(raw).hexdigest())]=b'wrong'
        with custody_file_scope(self.registry),self.assertRaisesRegex(CustodyFileStop,'DIGEST_MISMATCH'):write(self.path,b'new')
        self.assertEqual(self.path.read_bytes(),raw)
    def test_scope_cannot_expand_to_another_directory(self):
        with tempfile.TemporaryDirectory() as other:
            path=Path(other)/'unowned'
            with custody_file_scope(self.registry),self.assertRaisesRegex(CustodyFileStop,'OUTSIDE_EXACT'):write(path,b'new')
            self.assertFalse(path.exists())
    def test_partial_failure_preserves_original_and_blocks_retry(self):
        self.path.write_bytes(b'original')
        with custody_file_scope(self.registry):
            with self.assertRaises(OSError):partial(self.path)
            with self.assertRaisesRegex(CustodyFileStop,'REVIEW_REQUIRED'):write(self.path,b'retry')
        self.assertIn(b'original',self.registry.raw_versions.values())
        self.assertTrue(self.registry.uncertain)
    def test_pre_io_validation_failure_does_not_claim_partial_write(self):
        @custody_file_writer
        def deny(path):raise ValueError('local validation denied before IO')
        self.path.write_bytes(b'unchanged')
        with custody_file_scope(self.registry),self.assertRaises(ValueError):deny(self.path)
        self.assertFalse(self.registry.uncertain)
        self.assertEqual(self.path.read_bytes(),b'unchanged')
    def test_live_source_helpers_keep_guard_in_rendered_runtime(self):
        import ast,render_runtime
        template=Path(__file__).resolve().parents[1]/'runtime_template.py'
        tree=ast.parse(template.read_text(encoding='utf8'))
        names=('create_exclusive','replace_private','prepare_claim_parents','claim')
        for name in names:
            node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
            self.assertIn('custody_file_writer',[ast.unparse(d) for d in node.decorator_list])
        values={k:'a'*64 for k in render_runtime.BINDINGS.values()};values['candidate_archive_size']=1
        values['operation_id']='PHASE9-LIMITED-PILOT-RCA05-00000000-0000-4000-8000-000000000001'
        rendered=render_runtime.render(template,values).decode('utf8')
        self.assertIn('class LocalFileCustodyFixture',rendered)
        self.assertNotIn('from custody_file_contract import',rendered)
        self.assertIn("default=None",rendered)

if __name__=='__main__':unittest.main()
