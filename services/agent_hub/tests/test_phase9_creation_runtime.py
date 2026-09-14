"""Offline Memory/fakeredis only; no native session, source or production write."""
from __future__ import annotations

import asyncio
import hashlib

import fakeredis
import pytest
from fastapi.testclient import TestClient

import npd_agent_hub.main as main
from npd_agent_hub.auth import authorizer
from npd_agent_hub.attribution import AttributionService
from npd_agent_hub.config import HubSettings
from npd_agent_hub.delivery_observability import AttributionDeliveryService
from npd_agent_hub.orchestrator import AgentHub
from npd_agent_hub.phase9_creation_runtime import Phase9CreationDenied, verify_creation_fence
from npd_agent_hub.provider_health import ProviderHealthService
from npd_agent_hub.provider_health_scheduler import ProviderHealthScheduler
from npd_agent_hub.store import MemoryHubStore, RedisHubStore
from npd_agent_hub.tools import ToolExecutor

CID="CMP-AHINTERNAL-P9SLACOHORT-202609-01"
OWNER="LOCAL-EXACT-INTERNAL-OWNER"
TOKEN="LOCAL-CREATION-OWNER-ONLY-NOT-PRODUCTION"

def config(**changes):
    fields=dict(runtime_mode="phase9_creation",phase9_creation_campaign_id=CID,
        phase9_creation_owner_id=OWNER,provider_health_scheduler_enabled=False,
        auth_mode="static_token",owner_token=TOKEN,
        operator_token="LOCAL-OPERATOR-NOT-PRODUCTION",viewer_token="LOCAL-VIEWER-NOT-PRODUCTION")
    fields.update(changes)
    return HubSettings(**fields)

def payload():
    digest=lambda s:hashlib.sha256(s.encode()).hexdigest()
    return dict(name="P9SLACOHORT",project="Local internal acceptance",project_code="AHINTERNAL",
        objective="One synthetic local-only creation",audience=["Internal"],budget={"amount":0,"currency":"VND"},
        start_date="2026-09-01",end_date="2026-09-30",
        kpi_targets=[dict(name="Internal SLA",target=1,unit="case",funnel_stage="lead")],owner=OWNER,
        internal_cohort=dict(classification="phase9_internal_non_customer",canonical_campaign_id=CID,
            subject_ref="lead:LOCAL-NATIVE-STUB-NOT-PRODUCTION",owner_id=OWNER,
            owner_approval_sha256=digest("LOCAL synthetic creation grant"),
            non_customer_proof_sha256=digest("LOCAL synthetic native evidence"),
            scope="phase9_one_internal_task_report_audit_one_nba_review"))

def local_app(monkeypatch):
    settings=config()
    store=MemoryHubStore()
    local=AgentHub(store=store,executor=ToolExecutor(settings=settings))
    monkeypatch.setattr(main,"hub",local)
    monkeypatch.setattr(authorizer,"settings",settings)
    def external_forbidden(*a,**k):
        raise AssertionError("external/provider/business executor invoked in creation mode")
    monkeypatch.setattr(local.executor,"probe_provider_health",external_forbidden)
    monkeypatch.setattr(local,"run",external_forbidden)
    monkeypatch.setattr(local,"analyze",external_forbidden)
    monkeypatch.setattr(local,"execute",external_forbidden)
    return local,store

@pytest.mark.parametrize("backend",["memory","redis"])
def test_startup_has_no_status_initialization_lease_loop_or_store_write(backend):
    store=MemoryHubStore() if backend=="memory" else RedisHubStore(client=fakeredis.FakeRedis(decode_responses=True),namespace="LOCAL-FENCE")
    settings=config()
    delivery=AttributionDeliveryService(store,AttributionService(store),settings)
    service=ProviderHealthService(store,delivery)
    scheduler=ProviderHealthScheduler(store,service,settings)
    async def run():
        await scheduler.start()
        await asyncio.sleep(0)
        assert scheduler._task is None
        assert store.get_provider_health_scheduler_status() is None
        for force in (False,True):
            with pytest.raises(ValueError,match="SCHEDULER_DENIED"):
                await scheduler.run_once(force=force)
        await scheduler.stop()
    asyncio.run(run())
    if backend=="redis": assert list(store.redis.scan_iter())==[]
    else:
        assert not store.attribution_audit and not store.provider_health_snapshots and not store.provider_alerts
        assert store.provider_health_scheduler_status is None and store.provider_health_scheduler_lease is None

def test_actual_app_lifespan_and_health_no_autonomous_business_write(monkeypatch):
    local,store=local_app(monkeypatch)
    def forbidden(*a,**k): raise AssertionError("scheduler service invoked")
    monkeypatch.setattr(local.provider_health,"evaluate_cached",forbidden)
    with TestClient(main.app) as client:
        assert client.get("/health").status_code==200
        assert client.get("/readyz").status_code==200
        assert local.provider_health_scheduler._task is None
        assert store.provider_health_scheduler_status is None
        assert not store.attribution_audit and not store.tasks and not store.campaigns
    assert store.provider_health_scheduler_status is None

@pytest.mark.parametrize("method,path",[
    ("POST","/api/v1/provider-health/evaluate"),("POST","/api/v1/provider-health/refresh"),
    ("POST","/api/v1/attribution/deliveries/heartbeats"),("POST","/api/v1/attribution/deliveries"),
    ("POST","/api/v1/agent-tasks"),("POST","/api/v1/agent-tasks/LOCAL/analyze"),
    ("POST","/api/v1/agent-tasks/LOCAL/actions/LOCAL/execute"),
    ("POST","/api/v1/campaigns/from-brief"),("PATCH",f"/api/v1/campaigns/{CID}"),
    ("POST","/api/v1/experiments"),("POST","/agent-hub/events/v1"),
    ("GET","/api/v1/integrations/espocrm/schema/Lead"),("GET","/auth/google/login"),
    ("GET","/api/v1/campaigns/WRONG"),("DELETE",f"/api/v1/campaigns/{CID}"),
])
def test_run_now_provider_delivery_task_and_unrelated_routes_deny_before_handler(monkeypatch,method,path):
    local,store=local_app(monkeypatch)
    with TestClient(main.app) as client:
        response=client.request(method,path,headers={"Authorization":"Bearer "+TOKEN},json={})
    assert response.status_code==403 and response.json()["detail"]=="PHASE9_CREATION_ROUTE_DENIED"
    assert not store.campaigns and not store.tasks and not store.attribution_audit
    assert store.provider_health_scheduler_status is None

def test_exact_owner_creation_and_exact_readbacks_stay_available(monkeypatch):
    local,store=local_app(monkeypatch)
    with TestClient(main.app) as client:
        headers={"Authorization":"Bearer "+TOKEN}
        created=client.post("/api/v1/campaigns",headers=headers,json=payload())
        assert created.status_code==201 and created.json()["campaign_id"]==CID
        assert client.get(f"/api/v1/campaigns/{CID}",headers=headers).status_code==200
        assert client.get(f"/api/v1/campaigns/{CID}/audit",headers=headers).status_code==200
        replay=client.post("/api/v1/campaigns",headers=headers,json=payload())
        # Existing Campaign ID generation rejects the second sequence when it
        # cannot equal the immutable cohort CID, before another store write.
        assert replay.status_code==422
    assert len(store.campaigns)==1 and len(store.campaign_audit[CID])==1
    assert not store.attribution_audit and not store.tasks
    assert store.provider_health_scheduler_status is None

@pytest.mark.parametrize("defect",["missing_cohort","wrong_campaign","wrong_owner","nonzero_budget","wrong_name","forged_marker","extra_field"])
def test_wrong_or_unclassified_campaign_denies_without_fallback(monkeypatch,defect):
    _,store=local_app(monkeypatch); body=payload()
    if defect=="missing_cohort": body.pop("internal_cohort")
    elif defect=="wrong_campaign": body["internal_cohort"]["canonical_campaign_id"]="CMP-WRONG-LOCAL-202609-01"
    elif defect=="wrong_owner": body["owner"]="LOCAL-WRONG"
    elif defect=="nonzero_budget": body["budget"]["amount"]=1
    elif defect=="wrong_name": body["name"]="Wrong"
    elif defect=="forged_marker": body["internal_cohort"]["customer_contact"]=True
    elif defect=="extra_field": body["execute"]=True
    with TestClient(main.app) as client:
        response=client.post("/api/v1/campaigns",headers={"Authorization":"Bearer "+TOKEN},json=body)
    assert response.status_code==403
    assert not store.campaigns and not store.campaign_audit and not store.attribution_audit

@pytest.mark.parametrize("token",["LOCAL-OPERATOR-NOT-PRODUCTION","LOCAL-VIEWER-NOT-PRODUCTION","LOCAL-WRONG"])
def test_existing_server_rbac_still_denies_non_owner_creation(monkeypatch,token):
    _,store=local_app(monkeypatch)
    with TestClient(main.app) as client:
        response=client.post("/api/v1/campaigns",headers={"Authorization":"Bearer "+token},json=payload())
    assert response.status_code in {401,403}
    assert not store.campaigns

@pytest.mark.parametrize("changes",[
    {"runtime_mode":"unknown"},{"provider_health_scheduler_enabled":True},
    {"phase9_creation_campaign_id":""},{"phase9_creation_owner_id":""},
])
def test_invalid_creation_config_fails_before_startup(changes):
    with pytest.raises(ValueError): config(**changes)

def test_missing_creation_mode_cannot_satisfy_gate_even_if_scheduler_false(monkeypatch):
    monkeypatch.delenv("AGENT_RUNTIME_MODE",raising=False)
    monkeypatch.setenv("AGENT_PROVIDER_HEALTH_SCHEDULER_ENABLED","false")
    settings=HubSettings.from_env()
    assert settings.runtime_mode=="normal"
    with pytest.raises(Phase9CreationDenied): verify_creation_fence(settings,campaign_id=CID,owner_id=OWNER)
    verify_creation_fence(config(),campaign_id=CID,owner_id=OWNER)


def test_creation_env_requires_explicit_scheduler_false(monkeypatch):
    monkeypatch.setenv("AGENT_RUNTIME_MODE","phase9_creation")
    monkeypatch.setenv("AGENT_PHASE9_CREATION_CAMPAIGN_ID",CID)
    monkeypatch.setenv("AGENT_PHASE9_CREATION_OWNER_ID",OWNER)
    monkeypatch.delenv("AGENT_PROVIDER_HEALTH_SCHEDULER_ENABLED",raising=False)
    with pytest.raises(ValueError,match="explicit scheduler false"):
        HubSettings.from_env()
    monkeypatch.setenv("AGENT_PROVIDER_HEALTH_SCHEDULER_ENABLED","false")
    verify_creation_fence(HubSettings.from_env(),campaign_id=CID,owner_id=OWNER)


def test_malformed_creation_json_denies_without_any_write(monkeypatch):
    _,store=local_app(monkeypatch)
    with TestClient(main.app) as client:
        response=client.post("/api/v1/campaigns",headers={"Authorization":"Bearer "+TOKEN,
            "Content-Type":"application/json"},content=b'{"broken":')
    assert response.status_code==403 and not store.campaigns
    assert not store.attribution_audit and store.provider_health_scheduler_status is None


def test_existing_scheduler_status_bytes_remain_unchanged(monkeypatch):
    local,store=local_app(monkeypatch)
    from npd_agent_hub.provider_health_models import ProviderHealthSchedulerStatus
    # Existing normal-mode history is retained, rather than overwritten to
    # manufacture a disabled-state receipt.
    status=ProviderHealthSchedulerStatus(enabled=True,interval_seconds=300,run_count=7)
    store.save_provider_health_scheduler_status(status)
    before=status.model_dump_json()
    with TestClient(main.app) as client:
        assert client.get("/health").status_code==200
        assert local.provider_health_scheduler._task is None
    assert store.get_provider_health_scheduler_status().model_dump_json()==before

def test_normal_disabled_scheduler_retains_force_evaluation_and_status_initialization():
    settings=HubSettings(provider_health_scheduler_enabled=False)
    store=MemoryHubStore()
    service=ProviderHealthService(store,AttributionDeliveryService(store,AttributionService(store),settings))
    scheduler=ProviderHealthScheduler(store,service,settings)
    async def run():
        await scheduler.start()
        assert store.provider_health_scheduler_status is not None
        result=await scheduler.run_once(force=True)
        assert result.run_count==1 and scheduler._task is None
        await scheduler.stop()
    asyncio.run(run())
    assert any(a.event_type=="provider_health_scheduled_evaluation" for a in store.attribution_audit)
