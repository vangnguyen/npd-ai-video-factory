"""Tamper rejection for source-only reviews; no operation, window or approval."""
import json
from pathlib import Path
import sys,tempfile,unittest,zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import source_review_package as package


class SourceReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'source';self.root.mkdir();(self.root/'code.py').write_bytes(b'# static source\n')
        self.manifest={'kind':'AGENT_HUB_RETENTION_SOURCE_REVIEW_ONLY','production_activation':'NOT_AUTHORIZED',
            'backend_provisioning':'NOT_AUTHORIZED','owner_execution_approval':'NOT_GRANTED','execution_authorized':False,
            'operation_id':None,'execution_window':None,'files':{'code.py':{'sha256':package.sha(b'# static source\n'),'size_bytes':16}}}
        self.reseal()
    def reseal(self):
        raw=json.dumps(self.manifest,sort_keys=True).encode();(self.root/'PACKAGE_MANIFEST.json').write_bytes(raw)
        self.anchor=package.sha(raw)
    def archive(self):
        path=Path(self.temp.name)/'static.zip'
        with zipfile.ZipFile(path,'w') as z:
            for p in self.root.rglob('*'):
                if p.is_file():z.write(p,p.relative_to(self.root).as_posix())
        return path
    def test_exact_static_bytes_directory_and_crc_archive_pass(self):
        self.assertFalse(package.verify_directory(self.root,self.anchor)['execution_authorized'])
        self.assertEqual(package.verify_archive(self.archive(),self.anchor)['crc'],'PASS')
    def test_modified_bytes_denied(self):
        (self.root/'code.py').write_bytes(b'# tampered\n')
        with self.assertRaises(package.SourcePackageStop):package.verify_directory(self.root,self.anchor)
        with self.assertRaises(package.SourcePackageStop):package.verify_archive(self.archive(),self.anchor)
    def test_extra_file_denied(self):
        (self.root/'extra').write_bytes(b'extra')
        with self.assertRaises(package.SourcePackageStop):package.verify_directory(self.root,self.anchor)
        with self.assertRaises(package.SourcePackageStop):package.verify_archive(self.archive(),self.anchor)
    def test_missing_file_denied(self):
        (self.root/'code.py').unlink()
        with self.assertRaises(package.SourcePackageStop):package.verify_directory(self.root,self.anchor)
    def test_source_draft_cannot_grant_authority_even_resealed(self):
        for field,value in [('execution_authorized',True),('production_activation','APPROVED'),('operation_id','unapproved-id'),('owner_execution_approval','GRANTED')]:
            old=self.manifest[field];self.manifest[field]=value;self.reseal()
            with self.assertRaises(package.SourcePackageStop):package.verify_directory(self.root,self.anchor)
            self.manifest[field]=old
    def test_manifest_and_unsafe_path_denied(self):
        with self.assertRaises(package.SourcePackageStop):package.verify_directory(self.root,'a'*64)
        for name in ('../outside','/absolute','C:/outside','x\\y'):
            with self.assertRaises(package.SourcePackageStop):package.safe_name(name)
    def test_duplicate_json_and_archive_entry_denied(self):
        with self.assertRaises(package.SourcePackageStop):package.load(b'{"a":1,"a":2}')
        path=self.archive()
        with zipfile.ZipFile(path,'a') as z:z.writestr('code.py',b'overwritten')
        with self.assertRaises(package.SourcePackageStop):package.verify_archive(path,self.anchor)
    def test_corrupt_crc_or_invalid_archive_denied(self):
        path=self.archive();raw=bytearray(path.read_bytes());raw[40]^=1;path.write_bytes(raw)
        with self.assertRaises((package.SourcePackageStop,zipfile.BadZipFile)):package.verify_archive(path,self.anchor)

if __name__=='__main__':unittest.main()
