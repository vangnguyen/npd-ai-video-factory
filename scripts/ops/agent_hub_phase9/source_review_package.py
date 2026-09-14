"""Verify static source review bytes. Never activates a writer or pilot."""
import hashlib,json
from pathlib import Path,PurePosixPath
from zipfile import ZipFile,BadZipFile


class SourcePackageStop(ValueError):pass


def sha(raw):return hashlib.sha256(raw).hexdigest()


def load(raw):
    def unique(pairs):
        result={}
        for k,v in pairs:
            if k in result:raise SourcePackageStop('DUPLICATE_JSON_KEY')
            result[k]=v
        return result
    return json.loads(raw.decode('utf8',errors='strict'),object_pairs_hook=unique)


def safe_name(name):
    if (not isinstance(name,str) or not name or '\\' in name or ':' in name
            or PurePosixPath(name).is_absolute() or any(p in ('','..','.') for p in name.split('/'))):
        raise SourcePackageStop('UNSAFE_PACKAGE_PATH')
    return name


def contract(manifest):
    if (manifest.get('kind')!='AGENT_HUB_RETENTION_SOURCE_REVIEW_ONLY'
            or manifest.get('production_activation')!='NOT_AUTHORIZED'
            or manifest.get('backend_provisioning')!='NOT_AUTHORIZED'
            or manifest.get('owner_execution_approval')!='NOT_GRANTED'
            or manifest.get('execution_authorized') is not False
            or manifest.get('operation_id') is not None or manifest.get('execution_window') is not None):
        raise SourcePackageStop('SOURCE_REVIEW_CANNOT_GRANT_AUTHORITY')
    files=manifest.get('files')
    if not isinstance(files,dict) or not files:raise SourcePackageStop('EMPTY_MANIFEST')
    for name,proof in files.items():
        safe_name(name)
        if not isinstance(proof,dict) or set(proof)!={'sha256','size_bytes'}:
            raise SourcePackageStop('MANIFEST_PROOF_INVALID')
    return files


def verify_directory(root,expected_manifest):
    root=Path(root).resolve();path=root/'PACKAGE_MANIFEST.json'
    raw=path.read_bytes()
    if sha(raw)!=expected_manifest:raise SourcePackageStop('MANIFEST_HASH_MISMATCH')
    manifest=load(raw);files=contract(manifest)
    paths=list(root.rglob('*'))
    if any(p.is_symlink() for p in paths):raise SourcePackageStop('SYMLINK_REJECTED')
    actual={p.relative_to(root).as_posix() for p in paths if p.is_file()}
    if actual!=set(files)|{'PACKAGE_MANIFEST.json'}:raise SourcePackageStop('PACKAGE_INVENTORY_MISMATCH')
    for name,proof in files.items():
        raw=(root/name).read_bytes()
        if sha(raw)!=proof['sha256'] or len(raw)!=proof['size_bytes']:
            raise SourcePackageStop('PACKAGE_BYTES_MISMATCH')
    return {'status':'PASS','files_verified':len(files),'execution_authorized':False}


def verify_archive(path,expected_manifest):
    try:
        with ZipFile(path) as z:
            names=z.namelist()
            if len(names)!=len(set(names)):raise SourcePackageStop('DUPLICATE_ARCHIVE_ENTRY')
            for name in names:safe_name(name)
            if z.testzip() is not None:raise SourcePackageStop('ARCHIVE_CRC_INVALID')
            raw=z.read('PACKAGE_MANIFEST.json')
            if sha(raw)!=expected_manifest:raise SourcePackageStop('MANIFEST_HASH_MISMATCH')
            files=contract(load(raw))
            if set(names)!=set(files)|{'PACKAGE_MANIFEST.json'}:raise SourcePackageStop('ARCHIVE_INVENTORY_MISMATCH')
            for name,proof in files.items():
                raw=z.read(name)
                if sha(raw)!=proof['sha256'] or len(raw)!=proof['size_bytes']:
                    raise SourcePackageStop('ARCHIVE_BYTES_MISMATCH')
            return {'status':'PASS','crc':'PASS','all_bytes':'PASS','files_verified':len(files),'execution_authorized':False}
    except (BadZipFile,KeyError) as error:raise SourcePackageStop('ARCHIVE_INVALID') from error
