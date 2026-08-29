import fakeredis
import pytest

from npd_agent_hub.models import AgentTask
from npd_agent_hub.orchestrator import AgentHub
from npd_agent_hub.redis_read_model_probe import ReadModelProbeError, run_probe
from npd_agent_hub.store import MemoryHubStore, RedisHubStore


def test_probe_exercises_redis_read_models_without_returning_values_or_ids():
    client = fakeredis.FakeRedis(decode_responses=True)
    store = RedisHubStore(client=client, namespace="test:agent-hub")
    AgentHub(store=store).run(AgentTask(objective="Synthetic readiness probe"))

    report = run_probe(store)

    assert report["status"] == "PASS"
    assert report["recent_task_index_count"] == 1
    assert report["recent_tasks_restored"] == 1
    assert report["recent_reports_restored"] == 1
    assert report["values_logged"] is False
    assert report["identifiers_logged"] is False
    rendered = json_for_assertion(report)
    assert "Synthetic readiness probe" not in rendered
    assert "agt_" not in rendered


def json_for_assertion(value):
    import json

    return json.dumps(value, sort_keys=True)


def test_probe_rejects_non_redis_backend():
    with pytest.raises(ReadModelProbeError, match="Redis backend"):
        run_probe(MemoryHubStore())
