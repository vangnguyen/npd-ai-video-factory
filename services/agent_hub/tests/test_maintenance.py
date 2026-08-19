import fakeredis

from npd_agent_hub.maintenance import MaintenanceError, export_namespace, restore_namespace


def test_export_and_restore_only_agent_namespace():
    source = fakeredis.FakeRedis(decode_responses=True)
    source.set("npd:agent-hub:v1:task:agt_1", '{"task_id":"agt_1"}')
    source.rpush("npd:agent-hub:v1:audit:agt_1", "event-1", "event-2")
    source.zadd("npd:agent-hub:v1:tasks", {"agt_1": 123.5})
    source.set("unrelated:key", "must-not-export")

    payload = export_namespace(source, "npd:agent-hub:v1")

    assert payload["key_count"] == 3
    assert all(item["key"].startswith("npd:agent-hub:v1:") for item in payload["items"])

    target = fakeredis.FakeRedis(decode_responses=True)
    restored = restore_namespace(
        target,
        payload,
        namespace="npd:agent-hub:v1",
    )

    assert restored == 3
    assert target.get("npd:agent-hub:v1:task:agt_1") == '{"task_id":"agt_1"}'
    assert target.lrange("npd:agent-hub:v1:audit:agt_1", 0, -1) == ["event-1", "event-2"]
    assert target.zscore("npd:agent-hub:v1:tasks", "agt_1") == 123.5
    assert target.get("unrelated:key") is None


def test_restore_refuses_namespace_mismatch_and_implicit_replace():
    redis_client = fakeredis.FakeRedis(decode_responses=True)
    redis_client.set("npd:agent-hub:v1:existing", "1")
    payload = {
        "version": 1,
        "namespace": "npd:agent-hub:v1",
        "items": [
            {"key": "npd:agent-hub:v1:new", "type": "string", "value": "2"},
        ],
    }

    try:
        restore_namespace(redis_client, payload, namespace="npd:agent-hub:v1")
        assert False, "restore must require explicit replace when namespace is not empty"
    except MaintenanceError as exc:
        assert "--replace" in str(exc)

    try:
        restore_namespace(
            fakeredis.FakeRedis(decode_responses=True),
            payload,
            namespace="different:namespace",
        )
        assert False, "namespace mismatch must fail"
    except MaintenanceError as exc:
        assert "does not match" in str(exc)


def test_replace_restore_removes_stale_agent_keys_but_not_other_namespaces():
    redis_client = fakeredis.FakeRedis(decode_responses=True)
    redis_client.set("npd:agent-hub:v1:stale", "old")
    redis_client.set("video:job:1", "keep")
    payload = {
        "version": 1,
        "namespace": "npd:agent-hub:v1",
        "items": [
            {"key": "npd:agent-hub:v1:current", "type": "string", "value": "new"},
        ],
    }

    restore_namespace(
        redis_client,
        payload,
        namespace="npd:agent-hub:v1",
        replace=True,
    )

    assert redis_client.get("npd:agent-hub:v1:stale") is None
    assert redis_client.get("npd:agent-hub:v1:current") == "new"
    assert redis_client.get("video:job:1") == "keep"
