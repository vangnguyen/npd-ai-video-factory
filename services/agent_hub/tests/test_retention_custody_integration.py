"""Local safety, CAS and migration proof. No actual Redis/S3/production access."""
import asyncio
from dataclasses import replace
from datetime import datetime,timezone
from types import SimpleNamespace
from unittest.mock import patch
import fakeredis
import pytest
from redis.exceptions import ResponseError
from local_custody_fixture import fixture_retention
from npd_agent_hub.retention_custody import (ArchiveReceipt,CustodyBlocked,CustodyCoordinator,
    CustodyPolicy,GuardedRedis,PROTECTED,RawRecord,control_key,custody_operation,digest)
from npd_agent_hub.retention_backend_contract import S3Requirements,static_put_plan,verify_static_readback,release_hold
from npd_agent_hub.store import RedisHubStore,MemoryHubStore,build_store
from npd_agent_hub.config import HubSettings
from npd_agent_hub.maintenance import export_namespace,restore_namespace
from fastapi.testclient import TestClient


def owner(coordinator=None,client=None):
    obj=SimpleNamespace(retention=coordinator or fixture_retention(),_key=lambda *p: ':'.join(('synthetic:retention',*p)))
    obj.redis=GuardedRedis(client or fakeredis.FakeRedis(decode_responses=True),obj)
    return obj


def append(obj,raw='new',cap=5000):
    with obj.retention.batch(obj):
        obj.redis.rpush('synthetic:retention:audit',raw)
        obj.redis.ltrim('synthetic:retention:audit',-cap,-1)


@pytest.mark.parametrize('size',[4999,5000])
def test_append_at_cap_archives_exact_current_victim_before_cas(size):
    obj=owner();client=obj.redis._client;key='synthetic:retention:audit'
    rows=[' {"source_ledger_id":"%d"}\r\n'%i for i in range(size)]
    client.rpush(key,*rows);append(obj)
    assert client.llen(key)==min(size+1,5000)
    assert len(obj.retention.archive.rows)==(size==5000)
    if size==5000:
        record=next(iter(obj.retention.archive.rows.values()))
        assert record.raw==rows[0].encode() and record.identifier==digest(record.raw)
        assert record.raw!=rows[0].strip().encode()
    assert int(client.get(control_key(obj,'writer-epoch')))==1


@pytest.mark.parametrize('failure',['archive','digest','unknown','protected','missing_links','hold_change'])
def test_failure_aborts_entire_batch_with_original_bytes_retained(failure):
    obj=owner();client=obj.redis._client;key='synthetic:retention:audit';client.rpush(key,'old')
    if failure=='archive':obj.retention.archive.fail=True
    elif failure=='digest':obj.retention.archive.verify=lambda *a: (_ for _ in ()).throw(CustodyBlocked('DIGEST_MISMATCH'))
    elif failure=='unknown':obj.retention.classify=lambda r:'unclassified'
    elif failure=='protected':obj.retention.classify=lambda r:'terminal_phase9_recovery'
    elif failure=='missing_links':obj.retention.resolve_links=None
    else:
        original=obj.retention.archive.preserve
        def changed(*args):
            result=original(*args);obj.retention.protect(args[0].identity);return result
        obj.retention.archive.preserve=changed
    with pytest.raises(CustodyBlocked):
        with obj.retention.batch(obj):
            obj.redis.set('synthetic:retention:business','would-be-partial')
            obj.redis.rpush(key,'new');obj.redis.ltrim(key,-1,-1)
    assert client.get('synthetic:retention:business') is None
    assert client.lrange(key,0,-1)==['old']


@pytest.mark.parametrize('category',sorted(PROTECTED))
def test_protected_and_unknown_never_evict_even_after_period(category):
    obj=owner();obj.retention.classify=lambda r:category
    obj.redis._client.rpush('synthetic:retention:audit','old')
    with pytest.raises(CustodyBlocked,match='MUST_NOT_EVICT'):append(obj,cap=1)


def test_concurrent_append_into_new_key_is_detected_by_shared_epoch():
    first=owner();second=owner(client=first.redis._client)
    first.redis._client.rpush('synthetic:retention:audit','old')
    original=first.retention.archive.preserve
    def concurrent(*args):
        result=original(*args)
        with second.retention.batch(second):second.redis.set('synthetic:retention:concurrent-new-key','other-writer')
        return result
    first.retention.archive.preserve=concurrent
    with pytest.raises(CustodyBlocked,match='LEDGER_CHANGED_NO_RETRY'):append(first,cap=1)
    assert first.redis._client.lrange('synthetic:retention:audit',0,-1)==['old']
    assert len(first.retention.archive.rows)==1


def test_shared_reference_registry_blocks_other_coordinator():
    first=owner();second=owner(client=first.redis._client);key='synthetic:retention:audit'
    raw=b'old-terminal-custody';row=RawRecord(key,digest(raw),raw)
    first.redis._client.rpush(key,raw);second.retention.register_reference(row.identity)
    with pytest.raises(CustodyBlocked,match='SHARED_PROTECTED'):append(first,cap=1)
    assert first.redis._client.lrange(key,0,-1)==[raw.decode()]


def test_linked_raw_copy_is_independently_bound_and_tamper_rejected():
    obj=owner();key='synthetic:retention:audit';obj.redis._client.rpush(key,'old')
    obj.retention.resolve_links=lambda r,s:(('snapshot:owned',b' {"s": 1}\r\n'),)
    append(obj,cap=1);record=next(iter(obj.retention.archive.rows.values()));receipt=obj.retention.receipts[-1]
    assert record.links==(('snapshot:owned',b' {"s": 1}\r\n'),)
    assert receipt.link_digests==(('snapshot:owned',digest(record.links[0][1])),)
    bad=replace(receipt,link_digests=())
    with pytest.raises(CustodyBlocked):obj.retention.archive.verify(record,obj.retention.policy,bad)


def test_exec_partial_error_is_review_custody_never_retry():
    obj=owner();client=obj.redis._client
    with pytest.raises(CustodyBlocked,match='PARTIAL_EXEC'):
        with obj.retention.batch(obj) as session:
            obj.redis.set('synthetic:retention:only-first','partial')
            def partial(**kwargs):
                client.set('synthetic:retention:only-first','partial')
                return [True,ResponseError('synthetic runtime EXEC error')]
            session.pipe.execute=partial
    assert obj.retention.uncertain and client.get('synthetic:retention:only-first')=='partial'
    with pytest.raises(CustodyBlocked,match='REVIEW_REQUIRED'):append(obj)


def test_lost_exec_response_is_not_retried():
    obj=owner();calls=[]
    with pytest.raises(CustodyBlocked,match='UNCERTAIN_NO_RETRY'):
        with obj.retention.batch(obj) as session:
            obj.redis.set('synthetic:retention:new','new')
            def lost(**kwargs):calls.append(1);raise TimeoutError('synthetic lost ACK')
            session.pipe.execute=lost
    assert calls==[1] and obj.retention.uncertain


def test_failed_archive_preserves_memory_batch_and_mutable_prior_version():
    coord=fixture_retention();obj=SimpleNamespace(retention=coord,ledger=['old'],records={'old':{'value':1}})
    coord.archive.fail=True
    with pytest.raises(CustodyBlocked):
        with coord.batch(obj):obj.ledger=['new'];obj.records['old']={'value':2}
    assert obj.ledger==['old'] and obj.records=={'old':{'value':1}}
    assert coord.local_prior_versions


def test_child_task_cannot_borrow_active_memory_authority():
    coord=fixture_retention();obj=SimpleNamespace(retention=coord,records={})
    @custody_operation('target')
    async def write(target):target.records['child']=1
    @custody_operation('target')
    async def parent(target):
        target.records['parent']=1
        with pytest.raises(CustodyBlocked,match='CONCURRENT_TASK'):await asyncio.create_task(write(target))
    asyncio.run(parent(obj));assert obj.records=={'parent':1}


def test_child_task_cannot_reuse_context_after_parent_commit():
    coord=fixture_retention();obj=SimpleNamespace(retention=coord,records={})
    @custody_operation('target')
    async def write(target,ready):
        await ready.wait()
        with pytest.raises(CustodyBlocked,match='EXPIRED_BATCH'):
            with target.retention.batch(target):target.records['replay']=1
    async def run():
        ready=asyncio.Event()
        with coord.batch(obj):task=asyncio.create_task(write(obj,ready))
        ready.set()
        # The operation decorator itself rejects the expired inherited context.
        with pytest.raises(CustodyBlocked,match='EXPIRED_BATCH'):await task
    asyncio.run(run());assert obj.records=={}


def test_policy_change_during_archive_cannot_lower_retention():
    obj=owner();obj.redis._client.rpush('synthetic:retention:audit','old')
    original=obj.retention.archive.preserve
    def changed(*args):
        receipt=original(*args)
        obj.retention.policy=replace(obj.retention.policy,category_periods=(('ordinary_nonpilot_audit_and_linked_snapshot',90),))
        return receipt
    obj.retention.archive.preserve=changed
    with pytest.raises(CustodyBlocked,match='POLICY_OR_BACKEND_CHANGED'):append(obj,cap=1)
    assert obj.redis._client.lrange('synthetic:retention:audit',0,-1)==['old']


def test_guard_default_and_raw_proxy_do_not_activate_production():
    client=fakeredis.FakeRedis(decode_responses=True);store=RedisHubStore(client=client)
    with pytest.raises(CustodyBlocked,match='UNGUARDED'):store.redis.pipeline()
    with pytest.raises(CustodyBlocked,match='NOT_ACTIVATED'):
        with store.retention.batch(store):pass
    with pytest.raises(CustodyBlocked,match='UNGUARDED'):store.redis.set('synthetic:key','new')
    with pytest.raises(CustodyBlocked,match='NOT_CLASSIFIED'):store.redis.eval('synthetic',0)
    assert list(client.scan_iter('*'))==[]
    assert build_store(HubSettings(store_backend='memory')).retention.inactive


def test_actual_api_factory_hold_keeps_viewer_deny_and_operator_hold():
    from npd_agent_hub.main import app,hub
    from npd_agent_hub.auth import authorizer
    from npd_agent_hub.retention_custody import inactive_coordinator
    frozen=MemoryHubStore(retention=inactive_coordinator())
    auth=HubSettings(auth_mode='static_token',viewer_token='synthetic-viewer',operator_token='synthetic-operator',owner_token='synthetic-owner')
    with patch.object(hub,'store',frozen),patch.object(hub.provider_health_scheduler,'store',frozen),patch.object(authorizer,'settings',auth),TestClient(app) as client:
        assert client.get('/health').status_code==200
        for token,expected in [('synthetic-viewer',403),('synthetic-operator',503)]:
            response=client.post('/api/v1/agent-tasks',headers={'Authorization':'Bearer '+token},json={'objective':'synthetic internal fixture'})
            assert response.status_code==expected
        assert response.json()=={'detail':'RETENTION_CUSTODY_HOLD'}
    assert frozen.tasks=={} and frozen.audit=={}


@pytest.mark.parametrize('names',[(None,'verifier','custodian'),('same','same','custodian'),('owner','verifier','verifier')])
def test_named_authority_separation_fail_closed(names):
    policy=CustodyPolicy('synthetic',category_mapping_owner_adopted=True,
        named_owner=names[0],named_verifier=names[1],named_custodian=names[2])
    with pytest.raises(CustodyBlocked):policy.validate_authorities()


def test_period_mapping_requires_new_owner_disposition_and_no_hold_release():
    with pytest.raises(CustodyBlocked,match='NOT_ADOPTED'):CustodyPolicy('proposal',named_owner='o',named_verifier='v',named_custodian='c').validate_authorities()
    with pytest.raises(CustodyBlocked,match='NOT_AUTHORIZED'):release_hold('expired-version')


def test_migration_restore_defaults_hold_and_protected_custody_aborts_replace():
    source=fakeredis.FakeRedis(decode_responses=True);target=fakeredis.FakeRedis(decode_responses=True)
    source.set('synthetic:retention:new','new');target.set('synthetic:retention:old-terminal','original')
    payload=export_namespace(source,'synthetic:retention')
    with pytest.raises(CustodyBlocked,match='NOT_ACTIVATED'):restore_namespace(target,payload,namespace='synthetic:retention',replace=True)
    coord=fixture_retention();coord.classify=lambda r:'terminal_phase9_recovery'
    with pytest.raises(CustodyBlocked,match='MUST_NOT_EVICT'):restore_namespace(target,payload,namespace='synthetic:retention',replace=True,retention=coord)
    assert target.get('synthetic:retention:old-terminal')=='original' and target.get('synthetic:retention:new') is None


def requirements():
    return S3Requirements('synthetic-account','synthetic-region','synthetic-bucket','synthetic-prefix','synthetic-key',
        True,True,'GOVERNANCE',True,True,True,True,True)


def test_static_s3_plan_and_readback_are_not_actual_backend_authority():
    obj=owner();record=RawRecord('synthetic-source','synthetic-id',b'raw\r\n',(('linked',b'linked-raw'),))
    plan=static_put_plan(record,'ordinary_nonpilot_audit_and_linked_snapshot',obj.retention.policy,requirements(),datetime.now(timezone.utc).isoformat())
    proof={'synthetic_local_only':True,'raw_bytes':record.raw,'linked_bytes':record.links,'raw_sha256':digest(record.raw),
        'VersionId':'synthetic-version','independent_reader':True,'Key':plan['Key'],
        'retention_mode':'GOVERNANCE','retain_until_utc':plan['ObjectLockRetainUntilDate']}
    assert plan['IfNoneMatch']=='*' and not plan['execution_authorized']
    assert verify_static_readback(record,plan,proof)['actual_backend_acceptance']=='NOT_RUN'
    for field,value in [('raw_bytes',b'wrong'),('linked_bytes',()),('VersionId','null'),('independent_reader',False),('Key','wrong')]:
        with pytest.raises(CustodyBlocked):verify_static_readback(record,plan,{**proof,field:value})
    with pytest.raises(CustodyBlocked,match='NOT_IMPLEMENTED'):verify_static_readback(record,plan,{**proof,'synthetic_local_only':False})


@pytest.mark.parametrize('field',['versioning','object_lock','deny_unconditional_put','deny_delete_markers','independent_reader','lifecycle_deletion_disabled','governance_bypass_denied'])
def test_missing_s3_requirement_holds(field):
    with pytest.raises(CustodyBlocked):replace(requirements(),**{field:False}).validate()
