"""Source-integrated retention contract. No backend provisioning/activation entry.

Default persistent coordinator is HOLD. Local fixtures cannot activate a remote
client. Exact raw and linked custody must pass independent verification before
destructive commands are queued. Watch/EXEC uncertainty is never retried.
"""
from __future__ import annotations
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from functools import wraps
import hashlib
import inspect
import asyncio
import json
import math
from threading import RLock
from typing import Callable

from redis.exceptions import WatchError


class CustodyBlocked(ValueError):
    pass

class CustodyRejectionWithEvidence(RuntimeError):
    """Only exact, evidence-only failure batches may commit before rejection."""
    pass


RAW_DOMAIN = b'npd.agent-hub.retention.raw-record.v1\0'
PROPOSED_PERIODS = {
    'routine_provider_health_nonincident_nonpilot': 90,
    'ordinary_nonpilot_signed_delivery_and_deadletter': 180,
    'ordinary_nonpilot_audit_and_linked_snapshot': 365,
}
PROTECTED = frozenset({'active_operation', 'terminal_phase9_recovery',
    'owner_authorization', 'held_security_incident', 'unknown'})


def raw_bytes(value):
    if isinstance(value, bytes): return value
    if isinstance(value, str): return value.encode('utf8', errors='strict')
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value): raise CustodyBlocked('NONFINITE_VALUE')
        return str(value).encode('ascii')
    raise CustodyBlocked('RAW_BYTES_REQUIRED')


def digest(raw): return hashlib.sha256(raw_bytes(raw)).hexdigest()


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(',', ':')).encode('utf8')


def aware(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None or parsed.utcoffset() is None: raise CustodyBlocked('AWARE_UTC_REQUIRED')
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class RawRecord:
    source: str
    identifier: str
    raw: bytes
    links: tuple[tuple[str, bytes], ...] = ()
    @property
    def identity(self): return digest(RAW_DOMAIN + encode([self.source, self.identifier, digest(self.raw)]))


@dataclass(frozen=True)
class CustodyPolicy:
    policy_id: str
    category_periods: tuple[tuple[str, int], ...] = tuple(PROPOSED_PERIODS.items())
    category_mapping_owner_adopted: bool = False
    named_owner: str | None = None
    named_verifier: str | None = None
    named_custodian: str | None = None
    automatic_deletion: bool = False
    def validate_authorities(self):
        names = (self.named_owner, self.named_verifier, self.named_custodian)
        if not all(isinstance(n, str) and n.strip() and n != 'UNBOUND' for n in names):
            raise CustodyBlocked('NAMED_AUTHORITIES_UNBOUND')
        if len({n.strip().casefold() for n in names}) != 3: raise CustodyBlocked('AUTHORITY_SEPARATION_REQUIRED')
        if self.automatic_deletion: raise CustodyBlocked('AUTOMATIC_DELETION_FORBIDDEN')
        if not self.category_mapping_owner_adopted: raise CustodyBlocked('CATEGORY_MAPPING_NOT_ADOPTED')
        if len(dict(self.category_periods)) != len(self.category_periods): raise CustodyBlocked('DUPLICATE_CATEGORY')
        if any(c not in PROPOSED_PERIODS or isinstance(d, bool) or not isinstance(d, int) or d not in (90, 180, 365)
               for c, d in self.category_periods): raise CustodyBlocked('UNAPPROVED_PERIOD_FRAMEWORK')


@dataclass(frozen=True)
class ArchiveReceipt:
    identity: str
    raw_record_sha256: str
    link_digests: tuple[tuple[str, str], ...]
    immutable_version: str
    verified_at_utc: str
    retain_until_utc: str
    verifier: str
    policy_id: str
    category: str
    independently_verified: bool
    synthetic_local_only: bool


class LocalFixtureArchive:
    """Exact-byte local test custody, explicitly not independently durable/WORM."""
    def __init__(self): self.rows = {}; self.receipts = {}; self.fail = False
    def preserve(self, record, policy, category):
        if self.fail: raise CustodyBlocked('ARCHIVE_UNAVAILABLE')
        policy.validate_authorities()
        if category not in dict(policy.category_periods): raise CustodyBlocked('UNKNOWN_CATEGORY_HOLD')
        prior = self.rows.get(record.identity)
        if prior is not None and prior != record: raise CustodyBlocked('ARCHIVE_OVERWRITE_FORBIDDEN')
        self.rows.setdefault(record.identity, record)
        now = datetime.now(timezone.utc)
        receipt = ArchiveReceipt(record.identity, digest(record.raw), tuple((k, digest(v)) for k,v in record.links),
            'SYNTHETIC_LOCAL_VERSION:' + record.identity, now.isoformat(),
            (now + timedelta(days=dict(policy.category_periods)[category])).isoformat(),
            policy.named_verifier, policy.policy_id, category, True, True)
        self.receipts.setdefault(record.identity, receipt)
        return self.receipts[record.identity]
    def verify(self, record, policy, receipt):
        if self.fail or self.rows.get(record.identity) != record: raise CustodyBlocked('ARCHIVE_READBACK_MISMATCH')
        if (receipt.identity != record.identity or receipt.raw_record_sha256 != digest(record.raw)
            or receipt.link_digests != tuple((k,digest(v)) for k,v in record.links)
            or receipt.policy_id != policy.policy_id or receipt.verifier != policy.named_verifier
            or not receipt.independently_verified or not receipt.synthetic_local_only
            or receipt.immutable_version != 'SYNTHETIC_LOCAL_VERSION:' + record.identity):
            raise CustodyBlocked('ARCHIVE_RECEIPT_BINDING_INVALID')
        if aware(receipt.retain_until_utc) < aware(receipt.verified_at_utc) + timedelta(days=dict(policy.category_periods)[receipt.category]):
            raise CustodyBlocked('ARCHIVE_RETENTION_INVALID')


_ACTIVE: ContextVar[dict] = ContextVar('agent_hub_custody_batches', default={})


class CustodyCoordinator:
    def __init__(self, *, policy=None, archive=None, classify: Callable | None=None,
                 resolve_links: Callable | None=None, local_only=True, inactive=False):
        self.policy = policy; self.archive = archive; self.classify = classify
        self.local_only = local_only; self.inactive = inactive; self.lock = RLock()
        self.resolve_links=resolve_links;self._guards=[]
        self.holds = set(); self.references = set(); self.generation = 0
        self.receipts = []; self.uncertain = False; self.local_prior_versions = {};self.busy_task=None;self._async_lock=None;self._async_loop=None
    def async_lock(self):
        loop=asyncio.get_running_loop()
        if self._async_loop is not loop:
            if self._async_lock is not None and self._async_lock.locked():raise CustodyBlocked('ASYNC_LOOP_CHANGED_WHILE_BUSY')
            self._async_loop=loop;self._async_lock=asyncio.Lock()
        return self._async_lock
    def check_task(self):
        try:task=asyncio.current_task()
        except RuntimeError:task=None
        if self.busy_task is not None and task is not self.busy_task:raise CustodyBlocked('CONCURRENT_TASK_CUSTODY_HOLD')
    def protect(self, identity):
        with self.lock:
            self._register_shared(identity);self.holds.add(identity);self.generation += 1
    def register_reference(self, identity):
        with self.lock:
            self._register_shared(identity);self.references.add(identity);self.generation += 1
    def _register_shared(self,identity):
        for guard in self._guards:
            pipe=guard._client.pipeline(transaction=True)
            try:
                key=control_key(guard.owner,'references');pipe.watch(key)
                prior=json.loads(pipe.get(key) or b'[]')
                pipe.multi();pipe.set(key,encode(sorted(set(prior)|{identity})));pipe.execute()
            except WatchError as error:raise CustodyBlocked('REFERENCE_REGISTRY_CHANGED_NO_RETRY') from error
            finally:pipe.reset()
    def preserve(self, rows):
        if self.uncertain: raise CustodyBlocked('PARTIAL_CUSTODY_REVIEW_REQUIRED')
        if rows and (self.policy is None or self.archive is None or self.classify is None or self.resolve_links is None):
            raise CustodyBlocked('RETENTION_POLICY_OR_ARCHIVE_MISSING')
        receipts=[]
        for row in rows:
            if row.identity in self.holds or row.identity in self.references: raise CustodyBlocked('PROTECTED_REFERENCE_HOLD')
            category = self.classify(row)
            if category in PROTECTED or category not in dict(self.policy.category_periods):
                raise CustodyBlocked('PROTECTED_OR_UNKNOWN_MUST_NOT_EVICT')
            receipt=self.archive.preserve(row,self.policy,category)
            self.archive.verify(row,self.policy,receipt)
            receipts.append(receipt)
        return receipts
    def finalize(self,session,generation):
        victims=[]
        for row in session.victims():
            if self.resolve_links is None:raise CustodyBlocked('LINKED_CUSTODY_RESOLVER_MISSING')
            links=self.resolve_links(row,session)
            if not isinstance(links,tuple):raise CustodyBlocked('LINKED_CUSTODY_NOT_PROVEN')
            if any(not isinstance(k,str) or not isinstance(v,bytes) for k,v in links):raise CustodyBlocked('LINKED_RAW_BYTES_REQUIRED')
            victims.append(RawRecord(row.source,row.identifier,row.raw,links))
        if isinstance(session,RedisBatch):session.assert_unreferenced(victims)
        receipts=self.preserve(victims)
        if session.configuration!=(self.policy,self.archive,self.classify,self.resolve_links):
            raise CustodyBlocked('POLICY_OR_BACKEND_CHANGED_NO_RETRY')
        if self.generation!=generation:raise CustodyBlocked('HOLD_OR_REFERENCE_CHANGED')
        for row,receipt in zip(victims,receipts):self.archive.verify(row,self.policy,receipt)
        session.commit();self.receipts.extend(receipts)
    @contextmanager
    def batch(self, owner):
        if self.inactive or not self.local_only: raise CustodyBlocked('PRODUCTION_RETENTION_NOT_ACTIVATED')
        if self.uncertain: raise CustodyBlocked('PARTIAL_CUSTODY_REVIEW_REQUIRED')
        self.check_task();active=_ACTIVE.get()
        if id(owner) in active:
            session=active[id(owner)]
            if session.done or getattr(session,'closed',False):raise CustodyBlocked('EXPIRED_BATCH_REFERENCE_HOLD')
            yield session; return
        for existing in active.values():
            if isinstance(existing,MemoryBatch) and existing.coordinator is self:
                if existing.done or getattr(existing,'closed',False):raise CustodyBlocked('EXPIRED_BATCH_REFERENCE_HOLD')
                existing.join(owner)
                token=_ACTIVE.set({**active,id(owner):existing})
                try:yield existing
                finally:_ACTIVE.reset(token)
                return
        with self.lock:
            generation=self.generation
            is_redis=isinstance(getattr(owner,'redis',None),GuardedRedis)
            session=RedisBatch(owner.redis) if is_redis else MemoryBatch(owner,self)
            session.configuration=(self.policy,self.archive,self.classify,self.resolve_links)
            try:self.busy_task=asyncio.current_task()
            except RuntimeError:self.busy_task=None
            token=_ACTIVE.set({**active,id(owner):session})
            try:
                yield session
                self.finalize(session,generation)
            except CustodyRejectionWithEvidence:
                try:session.assert_evidence_only();self.finalize(session,generation)
                except BaseException:session.abort();raise
                raise
            except BaseException:
                session.abort(); raise
            finally:
                session.close(); _ACTIVE.reset(token);self.busy_task=None


def _coordinator(owner):
    root=getattr(owner,'store',owner)
    coordinator=getattr(root,'retention',None)
    if coordinator is None: raise CustodyBlocked('WRITER_NOT_INTEGRATED')
    return root,coordinator


def custody_detached_context():
    """Background work must acquire a new batch, never inherit a committed one."""
    context=copy_context();context.run(_ACTIVE.set,{})
    return context


def custody_writer(function):
    @wraps(function)
    def wrapped(self,*args,**kwargs):
        root,coordinator=_coordinator(self)
        with coordinator.batch(root) as session:
            if isinstance(session,MemoryBatch) and self is not root:session.join(self)
            return function(self,*args,**kwargs)
    wrapped.__custody_writer__=True
    return wrapped


def custody_reader(function):
    @wraps(function)
    def wrapped(self,*args,**kwargs):
        root,coordinator=_coordinator(self)
        with coordinator.lock:
            coordinator.check_task();return function(self,*args,**kwargs)
    return wrapped


def custody_operation(*paths):
    def decorate(function):
        signature=inspect.signature(function)
        def owner_for(args,kwargs):
            bound=signature.bind(*args,**kwargs); owners=[]
            for path in paths:
                parts=path.split('.'); value=bound.arguments.get(parts[0])
                for part in parts[1:]:value=getattr(value,part,None)
                if value is not None and hasattr(value,'retention') and value not in owners:owners.append(value)
            if not owners:raise CustodyBlocked('OPERATION_STORE_BINDING_MISSING')
            # Stable lock order prevents cross-store deadlocks. Cross-server
            # commits are not atomic and therefore deliberately forbidden.
            if len(owners)!=1:raise CustodyBlocked('MULTI_STORE_BATCH_NOT_SUPPORTED')
            return owners[0]
        if inspect.iscoroutinefunction(function):
            @wraps(function)
            async def wrapped(*args,**kwargs):
                owner=owner_for(args,kwargs)
                if id(owner) in _ACTIVE.get():
                    with owner.retention.batch(owner):return await function(*args,**kwargs)
                async with owner.retention.async_lock():
                    with owner.retention.batch(owner):return await function(*args,**kwargs)
        else:
            @wraps(function)
            def wrapped(*args,**kwargs):
                owner=owner_for(args,kwargs)
                with owner.retention.batch(owner):return function(*args,**kwargs)
        wrapped.__custody_operation__=paths
        return wrapped
    return decorate


def _model_raw(value):
    if hasattr(value,'model_dump_json'):return value.model_dump_json().encode('utf8')
    if isinstance(value,datetime):return value.isoformat().encode('utf8')
    if isinstance(value,tuple):return encode([v.isoformat() if isinstance(v,datetime) else v for v in value])
    return encode(value)


class MemoryBatch:
    """Locked local model; public reader methods cannot observe a partial batch."""
    def __init__(self,owner,coordinator):
        self.owner=owner;self.coordinator=coordinator
        self.participants=[];self.join(owner)
        self.done=False
    def join(self,owner):
        if any(p is owner for p,_ in self.participants):return
        before={k:deepcopy(v) for k,v in vars(owner).items() if k!='retention' and not hasattr(v,'retention')}
        self.participants.append((owner,before))
    def victims(self):
        rows=[]
        def compare(path,old,new):
            if isinstance(old,list):
                remaining=Counter(_model_raw(v) for v in new)
                for v in old:
                    raw=_model_raw(v)
                    if remaining[raw]:remaining[raw]-=1
                    else:rows.append(RawRecord(path,digest(raw),raw))
            elif isinstance(old,dict):
                for key,v in old.items():
                    if key not in new:rows.append(RawRecord(path,str(key),_model_raw(v)))
                    elif isinstance(v,list):compare(path+':'+str(key),v,new[key])
                    elif _model_raw(v)!=_model_raw(new[key]):
                        # Mutable local model versions are retained, not
                        # treated as disposable primary ledger entries.
                        raw=_model_raw(v);row=RawRecord(path,str(key),raw)
                        if row.identity in self.coordinator.holds|self.coordinator.references:raise CustodyBlocked('PROTECTED_MUTABLE_RECORD')
                        self.coordinator.local_prior_versions.setdefault(path+':'+str(key)+':'+digest(raw),raw)
        for owner,before in self.participants:
            for key,old in before.items():
                if isinstance(old,(list,dict)):compare(key,old,getattr(owner,key))
        return rows
    def commit(self):self.done=True
    def assert_evidence_only(self):
        for owner,before in self.participants:
            for key,value in before.items():
                if value!=getattr(owner,key) and key not in ('attribution_audit','attribution_dead_letters'):
                    raise CustodyBlocked('REJECTION_BATCH_CONTAINS_BUSINESS_WRITE')
    def abort(self):
        if not self.done:
            for owner,before in self.participants:
                for k,v in before.items():setattr(owner,k,v)
    def close(self):self.closed=True


def control_key(owner,suffix):
    # Control records are outside the business namespace. Activation must bind
    # these additional keys; the original 5,000-entry cap is unchanged.
    return 'npd:agent-hub:custody-control:'+digest(owner._key(''))+':'+suffix


class GuardedRedis:
    """No mutation escapes an outer writer/operation transaction."""
    MUTATIONS=frozenset({'set','setnx','rpush','ltrim','delete','zadd','zrem','expire','pexpireat'})
    READS=frozenset({'get','exists','type','lrange','llen','zcard','zrange','zrevrange','zscore','pttl'})
    def __init__(self,client,owner):
        self._client=client;self.owner=owner
        coordinator=owner.retention
        if not coordinator.inactive and coordinator.local_only and client.__class__.__module__.split('.')[0]=='fakeredis':
            coordinator._guards.append(self)
            for identity in coordinator.holds|coordinator.references:coordinator._register_shared(identity)
    def scan_iter(self,match='*',**kwargs):
        session=_ACTIVE.get().get(id(self.owner))
        if session is None:return self._client.scan_iter(match=match,**kwargs)
        import fnmatch
        current={str(k.decode('utf8') if isinstance(k,bytes) else k) for k in self._client.scan_iter(match=match,**kwargs)}
        for key in current:session.load(key)
        current|={k for k,(kind,_) in session.values.items() if kind!='none' and fnmatch.fnmatchcase(k,match)}
        current-={k for k,(kind,_) in session.values.items() if kind=='none'}
        return iter(sorted(current))
    def session(self):
        session=_ACTIVE.get().get(id(self.owner))
        if session is None:raise CustodyBlocked('UNGUARDED_REDIS_MUTATION')
        self.owner.retention.check_task()
        if session.done or getattr(session,'closed',False):raise CustodyBlocked('EXPIRED_BATCH_REFERENCE_HOLD')
        return session
    def pipeline(self,*args,**kwargs):return StagedPipeline(self.session())
    def transaction(self,function,*keys,**kwargs):
        session=self.session()
        for key in keys:session.load(key)
        pipe=StagedPipeline(session,immediate=True);function(pipe)
        if pipe.queue:pipe.execute()
    def __getattr__(self,name):
        if name in self.MUTATIONS:return lambda *a,**k:self.session().command(name,*a,**k)
        if name in self.READS:
            def read(*a,**k):
                session=_ACTIVE.get().get(id(self.owner))
                return self.session().command(name,*a,**k) if session else getattr(self._client,name)(*a,**k)
            return read
        if name in ('ping','info','connection_pool'):return getattr(self._client,name)
        raise CustodyBlocked('REDIS_COMMAND_NOT_CLASSIFIED')


class StagedPipeline:
    def __init__(self,session,immediate=False):self.session=session;self.immediate=immediate;self.queue=[]
    def multi(self):self.immediate=False
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def __getattr__(self,name):
        if name not in GuardedRedis.MUTATIONS|GuardedRedis.READS:raise CustodyBlocked('PIPELINE_COMMAND_NOT_CLASSIFIED')
        def call(*args,**kwargs):
            if self.immediate:return self.session.command(name,*args,**kwargs)
            self.queue.append((name,args,kwargs));return self
        return call
    def execute(self):
        result=[self.session.command(n,*a,**k) for n,a,k in self.queue];self.queue=[];return result


class RedisBatch:
    def __init__(self,guard):
        self.guard=guard;self.client=guard._client
        # Only an explicitly local fixture client may use this implementation.
        # Production configuration/real backend acceptance is separate.
        if self.client.__class__.__module__.split('.')[0]!='fakeredis':
            raise CustodyBlocked('LOCAL_COORDINATOR_CANNOT_USE_REMOTE_CLIENT')
        self.pipe=self.client.pipeline(transaction=True);self.before={};self.values={};self.commands=[];self.removed=[];self.done=False
        self.registry_key=control_key(guard.owner,'references');self.epoch_key=control_key(guard.owner,'writer-epoch')
        self.pipe.watch(self.registry_key,self.epoch_key)
        self.epoch=int(self.pipe.get(self.epoch_key) or 0);self.expiries={}
    def load(self,key):
        key=str(key)
        if key not in self.values:
            self.pipe.watch(key);kind=self.pipe.type(key)
            if isinstance(kind,bytes):kind=kind.decode('ascii')
            if kind=='none':value=None
            elif kind=='string':value=self.pipe.get(key)
            elif kind=='list':value=self.pipe.lrange(key,0,-1)
            elif kind=='zset':value=dict(self.pipe.zrange(key,0,-1,withscores=True))
            else:raise CustodyBlocked('WRONG_REDIS_KEY_TYPE')
            self.before[key]=(kind,deepcopy(value));self.values[key]=(kind,deepcopy(value))
            ttl=self.pipe.pttl(key);self.expiries[key]=None if ttl<0 else datetime.now(timezone.utc).timestamp()*1000+ttl
        return key,self.values[key]
    @staticmethod
    def slice(rows,start,end):
        size=len(rows);start=start if start>=0 else max(0,size+start);end=end if end>=0 else size+end
        return rows[start:end+1] if end>=start else []
    def command(self,name,*args,**kwargs):
        if not args:raise CustodyBlocked('MISSING_REDIS_KEY')
        key,(kind,value)=self.load(args[0]);rest=args[1:]
        result=None
        if name in ('set','setnx'):
            nx=name=='setnx' or kwargs.get('nx',False)
            if nx and kind!='none':return None
            if kwargs.get('xx') and kind=='none':return None
            if kind not in ('none','string'):raise CustodyBlocked('WRONG_REDIS_KEY_TYPE')
            if kind=='string' and raw_bytes(value)!=raw_bytes(rest[0]):self.removed.append(RawRecord(key,key,raw_bytes(value)))
            self.values[key]=('string',rest[0]);result=True
            ttl=kwargs.get('ex')
            if ttl is None and kwargs.get('px') is not None:ttl=float(kwargs['px'])/1000
            if ttl is not None:
                if isinstance(ttl,bool) or float(ttl)<=0:raise CustodyBlocked('INVALID_EXPIRY')
                self.expiries[key]=datetime.now(timezone.utc).timestamp()*1000+float(ttl)*1000
                self.removed.append(RawRecord(key,key,raw_bytes(rest[0])))
            elif not kwargs.get('keepttl'):self.expiries[key]=None
        elif name=='delete':
            result=0
            for item in args:
                k,(t,v)=self.load(item)
                if t!='none':
                    if t=='string':self.removed.append(RawRecord(k,k,raw_bytes(v)))
                    elif t=='list':self.removed.extend(RawRecord(k,digest(raw_bytes(item)),raw_bytes(item)) for item in v)
                    else:self.removed.extend(RawRecord(k,str(member),encode([raw_bytes(member).hex(),score])) for member,score in v.items())
                    result+=1
                self.values[k]=('none',None)
        elif name in ('rpush','ltrim'):
            if kind not in ('none','list'):raise CustodyBlocked('WRONG_REDIS_KEY_TYPE')
            value=list(value or [])
            if name=='rpush':value.extend(rest);result=len(value)
            else:
                kept=self.slice(value,*rest);remaining=Counter(raw_bytes(v) for v in kept)
                for v in value:
                    raw=raw_bytes(v)
                    if remaining[raw]:remaining[raw]-=1
                    else:self.removed.append(RawRecord(key,digest(raw),raw))
                value=kept;result=True
            self.values[key]=('list',value)
        elif name in ('zadd','zrem'):
            if kind not in ('none','zset'):raise CustodyBlocked('WRONG_REDIS_KEY_TYPE')
            value=dict(value or {})
            if name=='zadd':
                if any(not math.isfinite(float(v)) for v in rest[0].values()):raise CustodyBlocked('INVALID_ZSET_SCORE')
                for member,score in rest[0].items():
                    if member in value and float(value[member])!=float(score):
                        self.removed.append(RawRecord(key,str(member),encode([raw_bytes(member).hex(),value[member]])))
                result=sum(k not in value for k in rest[0]);value.update(rest[0])
            else:
                result=sum(k in value for k in rest)
                for member in rest:
                    if member in value:
                        self.removed.append(RawRecord(key,str(member),encode([raw_bytes(member).hex(),value[member]])))
                        value.pop(member)
            self.values[key]=('zset',value)
        elif name in ('expire','pexpireat'):
            result=kind!='none'
            if result:
                self.expiries[key]=datetime.now(timezone.utc).timestamp()*1000+float(rest[0])*1000 if name=='expire' else float(rest[0])
                # TTL is a future destructive boundary, requiring custody now.
                self.removed.append(RawRecord(key,key,raw_bytes(value) if kind=='string' else encode(value)))
        elif name=='type':return kind
        elif name=='exists':return int(kind!='none')
        elif name=='get':
            if kind not in ('none','string'):raise CustodyBlocked('WRONG_REDIS_KEY_TYPE')
            return value
        elif name in ('lrange','llen'):
            if kind not in ('none','list'):raise CustodyBlocked('WRONG_REDIS_KEY_TYPE')
            return self.slice(value or [],*rest) if name=='lrange' else len(value or [])
        elif name in ('zcard','zscore','zrange','zrevrange'):
            if kind not in ('none','zset'):raise CustodyBlocked('WRONG_REDIS_KEY_TYPE')
            value=value or {}
            if name=='zcard':return len(value)
            if name=='zscore':return value.get(rest[0])
            rows=sorted(value.items(),key=lambda p:(p[1],raw_bytes(p[0])),reverse=name=='zrevrange')
            rows=self.slice(rows,*rest)
            return rows if kwargs.get('withscores') else [k for k,_ in rows]
        elif name=='pttl':
            if kind=='none':return -2
            return -1 if self.expiries[key] is None else max(0,int(self.expiries[key]-datetime.now(timezone.utc).timestamp()*1000))
        else:raise CustodyBlocked('COMMAND_NOT_IMPLEMENTED')
        self.commands.append((name,args,kwargs));return result
    def victims(self):return self.removed
    def assert_unreferenced(self,rows):
        references=set(json.loads(self.pipe.get(self.registry_key) or b'[]'))
        if any(row.identity in references for row in rows):raise CustodyBlocked('SHARED_PROTECTED_REFERENCE_HOLD')
    def assert_evidence_only(self):
        prefix=self.guard.owner._key('attribution-os')
        for name,args,kwargs in self.commands:
            key=str(args[0])
            permitted=key==prefix+':audit' or key==prefix+':dead-letters' or key.startswith(prefix+':dead-letter:')
            if not permitted or name not in ('set','rpush','ltrim','zadd') or (name=='set' and not kwargs.get('nx')):
                raise CustodyBlocked('REJECTION_BATCH_CONTAINS_BUSINESS_WRITE')
    def commit(self):
        try:
            self.pipe.multi()
            for n,a,k in self.commands:getattr(self.pipe,n)(*a,**k)
            if self.commands:self.pipe.set(self.epoch_key,self.epoch+1)
            results=self.pipe.execute(raise_on_error=False)
            if any(isinstance(v,Exception) for v in results):
                self.guard.owner.retention.uncertain=True;raise CustodyBlocked('PARTIAL_EXEC_CUSTODY_REVIEW_REQUIRED')
            self.done=True
        except WatchError as error:raise CustodyBlocked('LEDGER_CHANGED_NO_RETRY') from error
        except CustodyBlocked:raise
        except BaseException as error:
            self.guard.owner.retention.uncertain=True
            raise CustodyBlocked('EXEC_OUTCOME_UNCERTAIN_NO_RETRY') from error
    def abort(self):pass
    def close(self):self.closed=True;self.pipe.reset()


def inactive_coordinator():return CustodyCoordinator(inactive=True)
