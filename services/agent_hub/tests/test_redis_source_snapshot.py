import fakeredis
import pytest

from npd_agent_hub.redis_source_snapshot import SourceSnapshotError, snapshot_source


def test_source_snapshot_reports_only_safe_namespace_aggregates():
    client = fakeredis.FakeRedis(decode_responses=True)
    client.set("npd:agent-hub:v1:task:one", "private-value")
    client.rpush("npd:agent-hub:v1:audit:one", "private-event")
    client.set("outside:key", "not-migrated")

    report = snapshot_source(client, namespace="npd:agent-hub:v1")

    assert report["status"] == "PASS"
    assert report["db_key_count"] == 3
    assert report["namespace_key_count"] == 2
    assert report["outside_namespace_key_count"] == 1
    assert report["namespace_type_counts"] == {"list": 1, "string": 1}
    rendered = str(report)
    assert "task:one" not in rendered
    assert "private-value" not in rendered
    assert report["values_logged"] is False
    assert report["identifiers_logged"] is False


def test_exclusive_source_snapshot_rejects_outside_keys():
    client = fakeredis.FakeRedis(decode_responses=True)
    client.set("npd:agent-hub:v1:task:one", "value")
    client.set("outside:key", "value")

    with pytest.raises(SourceSnapshotError, match="outside"):
        snapshot_source(
            client,
            namespace="npd:agent-hub:v1",
            require_exclusive_namespace=True,
        )
