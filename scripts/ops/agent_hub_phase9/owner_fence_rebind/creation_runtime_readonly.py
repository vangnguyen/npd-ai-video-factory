"""Read-only exact Agent Hub creation-runtime shape for owner-fence rebind design."""
import hashlib
import http.client
import json
import os
import subprocess
import sys

PROJECT='npd-agent-hub-prod'
SERVICE='agent-hub'
FIELDS=('AGENT_RUNTIME_MODE','AGENT_PROVIDER_HEALTH_SCHEDULER_ENABLED','AGENT_PHASE9_CREATION_CAMPAIGN_ID','AGENT_PHASE9_CREATION_OWNER_ID')

def run(argv):
    result=subprocess.run(argv,capture_output=True,timeout=15,check=False)
    if result.returncode or result.stderr:
        raise RuntimeError('READONLY_CHILD_FAILED')
    return result.stdout

try:
    ids=run(['docker','ps','-aq','--no-trunc','--filter',f'label=com.docker.compose.project={PROJECT}','--filter',f'label=com.docker.compose.service={SERVICE}']).decode().split()
    if len(ids)!=1:raise RuntimeError('TARGET_CARDINALITY')
    item=json.loads(run(['docker','inspect',ids[0]]))[0]
    config=item.get('Config') or {};state=item.get('State') or {};host=item.get('HostConfig') or {}
    env={}
    for line in config.get('Env') or []:
        key,sep,val=line.partition('=')
        if not sep or key in env:raise RuntimeError('ENV_INVALID')
        env[key]=val
    allowed={key:env.get(key) for key in FIELDS}
    env_digest=hashlib.sha256(json.dumps(env,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    labels=config.get('Labels') or {}
    compose={key:labels.get(key) for key in (
        'com.docker.compose.project','com.docker.compose.service',
        'com.docker.compose.project.working_dir','com.docker.compose.project.config_files',
        'com.docker.compose.config-hash',
    )}
    paths=(compose['com.docker.compose.project.config_files'] or '').split(',')
    files=[]
    for path in paths:
        if not path or not os.path.isfile(path):raise RuntimeError('COMPOSE_FILE_MISSING')
        with open(path,'rb') as handle: digest=hashlib.file_digest(handle,'sha256').hexdigest()
        files.append({'path':path,'sha256':digest})
    mounts=[{'destination':m.get('Destination'),'source':m.get('Source'),'rw':m.get('RW'),'type':m.get('Type')} for m in item.get('Mounts') or []]
    networks=sorted((item.get('NetworkSettings') or {}).get('Networks') or {})
    ports=(item.get('NetworkSettings') or {}).get('Ports') or {}
    health={}
    for path in ('/health','/readyz'):
        connection=http.client.HTTPConnection('127.0.0.1',8010,timeout=6)
        try:
            connection.request('GET',path); response=connection.getresponse();health[path]=response.status;response.read(10000)
        finally:connection.close()
    print(json.dumps({
        'status':'PASS_CREATION_RUNTIME_READONLY',
        'container_id':item.get('Id'),'image_id':item.get('Image'),
        'running':state.get('Running'),'health_status':(state.get('Health') or {}).get('Status'),
        'restart_count':item.get('RestartCount'),'health_readback':health,
        'creation_settings':allowed,'full_environment_sha256':env_digest,'environment_count':len(env),
        'mounts':mounts,'mounts_full':item.get('Mounts') or [],'networks':networks,'ports':ports,
        'compose':compose,'compose_files':files,
        'oom_kill_disable_raw':host.get('OomKillDisable'),
        'restart_policy':host.get('RestartPolicy'),
        'command_sha256':hashlib.sha256(json.dumps(config.get('Cmd'),sort_keys=True).encode()).hexdigest(),
        'entrypoint_sha256':hashlib.sha256(json.dumps(config.get('Entrypoint'),sort_keys=True).encode()).hexdigest(),
        'production_writes':0,
    },sort_keys=True))
except Exception:
    print(json.dumps({'status':'HOLD_CREATION_RUNTIME_READONLY','production_writes':0},sort_keys=True));sys.exit(2)
