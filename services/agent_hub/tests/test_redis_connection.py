from pathlib import Path

import pytest

from npd_agent_hub.config import HubSettings
from npd_agent_hub.redis_connection import create_redis_client, read_redis_password_file
from npd_agent_hub.store import RedisHubStore, build_store


PASSWORD = "A" * 43


def write_password(tmp_path: Path, value: str = PASSWORD) -> Path:
    path = tmp_path / "agent-redis-password"
    path.write_text(value + "\n", encoding="utf-8")
    return path.resolve()


def test_password_file_is_passed_separately_from_url(monkeypatch, tmp_path: Path):
    password_file = write_password(tmp_path)
    seen = {}

    def fake_from_url(url, **kwargs):
        seen.update(url=url, **kwargs)
        return object()

    monkeypatch.setattr("npd_agent_hub.redis_connection.Redis.from_url", fake_from_url)
    client = create_redis_client(
        "redis://agent-redis:6379/0",
        password_file=str(password_file),
    )

    assert client is not None
    assert seen == {
        "url": "redis://agent-redis:6379/0",
        "password": PASSWORD,
        "decode_responses": True,
    }
    assert PASSWORD not in seen["url"]


def test_password_file_contract_fails_closed(tmp_path: Path):
    password_file = write_password(tmp_path, "weak")
    with pytest.raises(ValueError, match="43-128 base64url"):
        read_redis_password_file(str(password_file))
    with pytest.raises(ValueError, match="absolute path"):
        read_redis_password_file("relative/password")

    write_password(tmp_path)
    with pytest.raises(ValueError, match="must not embed"):
        create_redis_client(
            "redis://:embedded@agent-redis:6379/0",
            password_file=str(password_file),
        )


def test_build_store_forwards_password_file(monkeypatch, tmp_path: Path):
    password_file = write_password(tmp_path)
    sentinel = object()
    seen = {}

    def fake_client(url, *, password_file, decode_responses=True):
        seen.update(url=url, password_file=password_file, decode_responses=decode_responses)
        return sentinel

    monkeypatch.setattr("npd_agent_hub.store.create_redis_client", fake_client)
    settings = HubSettings(
        store_backend="redis",
        agent_redis_url="redis://agent-redis:6379/0",
        agent_redis_password_file=str(password_file),
    )
    store = build_store(settings)

    assert isinstance(store, RedisHubStore)
    assert store.redis is sentinel
    assert seen["password_file"] == str(password_file)
    assert PASSWORD not in repr(settings)
