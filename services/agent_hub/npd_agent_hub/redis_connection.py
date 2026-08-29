from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

from redis import Redis


REDIS_PASSWORD = re.compile(r"^[A-Za-z0-9_-]{43,128}$")


def read_redis_password_file(path_value: str) -> str | None:
    """Read a base64url Redis password without exposing its path or value in errors."""

    if not path_value:
        return None
    path = Path(path_value)
    if not path.is_absolute():
        raise ValueError("AGENT_REDIS_PASSWORD_FILE must be an absolute path")
    try:
        password = path.read_text(encoding="utf-8").rstrip("\r\n")
    except OSError as exc:
        raise ValueError("AGENT_REDIS_PASSWORD_FILE could not be read") from exc
    if not REDIS_PASSWORD.fullmatch(password):
        raise ValueError(
            "AGENT_REDIS_PASSWORD_FILE must contain 43-128 base64url characters"
        )
    return password


def create_redis_client(
    redis_url: str,
    *,
    password_file: str = "",
    decode_responses: bool = True,
) -> Redis:
    password = read_redis_password_file(password_file)
    try:
        parsed = urlsplit(redis_url)
    except ValueError as exc:
        raise ValueError("AGENT_REDIS_URL is invalid") from exc
    if parsed.scheme not in {"redis", "rediss", "unix"}:
        raise ValueError("AGENT_REDIS_URL must use redis, rediss, or unix")
    if password is not None and parsed.password is not None:
        raise ValueError(
            "AGENT_REDIS_URL must not embed a password when AGENT_REDIS_PASSWORD_FILE is set"
        )
    options: dict[str, object] = {"decode_responses": decode_responses}
    if password is not None:
        options["password"] = password
    return Redis.from_url(redis_url, **options)
