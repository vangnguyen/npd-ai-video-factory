from copy import deepcopy

import fakeredis
import pytest

from npd_agent_hub.maintenance import (
    MaintenanceError,
    export_namespace,
    restore_namespace,
    verify_namespace,
)


def test_export_and_restore_only_agent_namespace():
    source = fakeredis.FakeRedis(decode_responses=True)
    source.set("npd:agent-hub:v1:task:agt_1", '{"task_id":"agt_1"}')
    source.rpush("npd:agent-hub:v1:audit:agt_1", "event-1", "event-2")
    source.zadd("npd:agent-hub:v1:tasks", {"agt_1": 123.5})
    source.set("unrelated:key", "must-not-export")

    payload = export_namespace(source, "npd:agent-hub:v1")

    assert payload["version"] == 2
    assert payload["key_count"] == 3
    assert payload["type_counts"] == {"list": 1, "string": 1, "zset": 1}
    assert payload["source_consistency"] == "PASS"
    assert len(payload["namespace_sha256"]) == 64
    assert len(payload["content_sha256"]) == 64
    assert all(item["key"].startswith("npd:agent-hub:v1:") for item in payload["items"])
    assert all(item["pttl_ms"] == -1 for item in payload["items"])
    assert all(item["expires_at_epoch_ms"] is None for item in payload["items"])

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
    assert verify_namespace(target, payload, namespace="npd:agent-hub:v1")["status"] == "PASS"


def test_v2_export_restore_preserves_absolute_ttl_semantics():
    source = fakeredis.FakeRedis(decode_responses=True)
    source.set("npd:agent-hub:v1:provider-health:scheduler:lease", "owner", px=60_000)

    payload = export_namespace(source, "npd:agent-hub:v1")
    exported = payload["items"][0]
    assert 0 < exported["pttl_ms"] <= 60_000
    assert exported["expires_at_epoch_ms"] > payload["created_at_epoch_ms"]

    target = fakeredis.FakeRedis(decode_responses=True)
    assert restore_namespace(target, payload, namespace="npd:agent-hub:v1") == 1
    restored_ttl = target.pttl("npd:agent-hub:v1:provider-health:scheduler:lease")
    assert 0 < restored_ttl <= exported["pttl_ms"]
    report = verify_namespace(target, payload, namespace="npd:agent-hub:v1")
    assert report["ttl_key_count"] == 1
    assert report["values_logged"] is False


def test_v2_restore_fails_closed_on_checksum_corruption_before_writing():
    source = fakeredis.FakeRedis(decode_responses=True)
    source.set("npd:agent-hub:v1:current", "original")
    payload = export_namespace(source, "npd:agent-hub:v1")
    corrupted = deepcopy(payload)
    corrupted["items"][0]["value"] = "tampered"

    target = fakeredis.FakeRedis(decode_responses=True)
    with pytest.raises(MaintenanceError, match="checksum mismatch"):
        restore_namespace(target, corrupted, namespace="npd:agent-hub:v1")
    assert list(target.scan_iter("*")) == []


def test_export_fails_closed_on_unsupported_type():
    source = fakeredis.FakeRedis(decode_responses=True)
    source.hset("npd:agent-hub:v1:unsupported", mapping={"field": "value"})

    with pytest.raises(MaintenanceError, match="unsupported Redis type"):
        export_namespace(source, "npd:agent-hub:v1")


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


def test_legacy_v1_restore_remains_supported_without_adding_ttls():
    payload = {
        "version": 1,
        "namespace": "npd:agent-hub:v1",
        "key_count": 1,
        "items": [
            {"key": "npd:agent-hub:v1:legacy", "type": "string", "value": "kept"},
        ],
    }
    target = fakeredis.FakeRedis(decode_responses=True)

    assert restore_namespace(target, payload, namespace="npd:agent-hub:v1") == 1
    assert target.get("npd:agent-hub:v1:legacy") == "kept"
    assert target.pttl("npd:agent-hub:v1:legacy") == -1


def test_legacy_v1_restore_accepts_unsorted_items_and_verifies_canonical_key_order():
    payload = {
        "version": 1,
        "namespace": "npd:agent-hub:v1",
        "key_count": 2,
        "items": [
            {"key": "npd:agent-hub:v1:z-last", "type": "string", "value": "z"},
            {"key": "npd:agent-hub:v1:a-first", "type": "string", "value": "a"},
        ],
    }
    target = fakeredis.FakeRedis(decode_responses=True)

    assert restore_namespace(target, payload, namespace="npd:agent-hub:v1") == 2
    assert verify_namespace(target, payload, namespace="npd:agent-hub:v1")["status"] == "PASS"
