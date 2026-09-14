"""Guard file custody producers before IO. No production activation binder.

Default is HOLD. Explicit local scopes are synthetic test evidence only, confined
to a selected temporary root. Registry-first references never release custody.
"""
import contextvars
import functools
import hashlib
import inspect
import json
from pathlib import Path
import tempfile
from threading import RLock


class CustodyFileStop(ValueError):
    pass


_FILE_CONTEXT=contextvars.ContextVar('agent_hub_file_custody_scope',default=None)


class LocalFileCustodyFixture:
    def __init__(self,root,*,register_reference=None):
        self.root=Path(root).resolve()
        if not self.root.is_relative_to(Path(tempfile.gettempdir()).resolve()):
            raise CustodyFileStop('SYNTHETIC_SCOPE_CANNOT_TARGET_PRODUCTION')
        self.register_reference=register_reference;self.bindings={};self.raw_versions={};self.protected_paths=set()
        self.lock=RLock();self.generation=0;self.depth=0;self.uncertain=False;self.fail_archive=False
        self.execution_authorized=False;self.synthetic_local_only=True
    def bind_reference(self,path,identity):
        path=self.checked(path);self.bindings.setdefault(str(path),set()).add(identity);self.generation+=1
    def checked(self,path):
        path=Path(path)
        if any(p.is_symlink() for p in (path,*path.parents)):raise CustodyFileStop('CUSTODY_SYMLINK_REJECTED')
        path=path.resolve()
        if not path.is_relative_to(self.root):raise CustodyFileStop('CUSTODY_PATH_OUTSIDE_EXACT_LOCAL_SCOPE')
        return path
    def preserve(self,paths):
        if self.uncertain:raise CustodyFileStop('PARTIAL_FILE_CUSTODY_REVIEW_REQUIRED')
        if self.fail_archive:raise CustodyFileStop('FILE_ARCHIVE_UNAVAILABLE')
        for path in paths:
            path=self.checked(path)
            if str(path) not in self.protected_paths:
                for identity in self.bindings.get(str(path),()):
                    if self.register_reference is None:raise CustodyFileStop('REFERENCE_REGISTRY_MISSING')
                    self.register_reference(identity)
                self.protected_paths.add(str(path));self.generation+=1
            files=[path] if path.is_file() else sorted(path.rglob('*')) if path.is_dir() else []
            for f in files:
                f=self.checked(f)
                if not f.is_file():continue
                raw=f.read_bytes();sha=hashlib.sha256(raw).hexdigest();key=(str(f),sha)
                if key in self.raw_versions and self.raw_versions[key]!=raw:raise CustodyFileStop('RAW_CUSTODY_DIGEST_MISMATCH')
                self.raw_versions.setdefault(key,raw)
                if hashlib.sha256(self.raw_versions[key]).hexdigest()!=sha:raise CustodyFileStop('INDEPENDENT_LOCAL_READBACK_FAILED')
    def fingerprint(self,paths):
        rows=[]
        for p in paths:
            p=self.checked(p)
            targets=[p] if p.is_file() else sorted(p.rglob('*')) if p.is_dir() else []
            rows.append((str(p),p.exists()))
            rows.extend((str(self.checked(f)),hashlib.sha256(f.read_bytes()).hexdigest()) for f in targets if f.is_file())
        return rows


class custody_file_scope:
    def __init__(self,registry):self.registry=registry
    def __enter__(self):
        if not isinstance(self.registry,LocalFileCustodyFixture):raise CustodyFileStop('PRODUCTION_FILE_CUSTODY_NOT_ACTIVATED')
        self.token=_FILE_CONTEXT.set(self.registry);return self.registry
    def __exit__(self,*args):_FILE_CONTEXT.reset(self.token)


def custody_file_writer(function):
    signature=inspect.signature(function)
    @functools.wraps(function)
    def wrapped(*args,**kwargs):
        registry=_FILE_CONTEXT.get()
        if registry is None:raise CustodyFileStop('FILE_CUSTODY_WRITER_NOT_CONFIGURED')
        bound=signature.bind(*args,**kwargs);paths=[]
        for key,value in bound.arguments.items():
            if key in ('path','directory','authority','root','output_directory') and isinstance(value,(str,Path)):
                paths.append(Path(value))
        for name in function.__code__.co_names:
            value=function.__globals__.get(name)
            if isinstance(value,Path):paths.append(value)
        with registry.lock:
            if not paths and registry.depth==0:raise CustodyFileStop('FILE_WRITER_TARGET_BINDING_MISSING')
            registry.preserve(paths);before=registry.fingerprint(paths);registry.depth+=1
            try:
                result=function(*args,**kwargs)
                registry.preserve(paths)
                return result
            except BaseException:
                # File/OS failures can leave partial publication. Original
                # versions remain preserved; the scope is not permission retry.
                if registry.fingerprint(paths)!=before:registry.uncertain=True
                raise
            finally:registry.depth-=1
    wrapped.__custody_file_writer__=True
    return wrapped
