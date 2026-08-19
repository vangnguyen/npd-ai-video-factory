from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class HubSettings:
    video_api_url: str = "http://api:8000"
    espocrm_url: str = ""
    espocrm_api_key: str = ""
    n8n_executor_webhook_url: str = ""
    request_timeout_seconds: float = 30.0
    store_backend: str = "memory"
    agent_redis_url: str = "redis://redis:6379/1"
    store_namespace: str = "npd:agent-hub:v1"

    @classmethod
    def from_env(cls) -> "HubSettings":
        return cls(
            video_api_url=os.getenv("VIDEO_API_URL", "http://api:8000").rstrip("/"),
            espocrm_url=os.getenv("ESPOCRM_URL", "").rstrip("/"),
            espocrm_api_key=os.getenv("ESPOCRM_API_KEY", "").strip(),
            n8n_executor_webhook_url=os.getenv("N8N_AGENT_EXECUTOR_WEBHOOK_URL", "").strip(),
            request_timeout_seconds=float(os.getenv("AGENT_TOOL_TIMEOUT_SECONDS", "30")),
            store_backend=os.getenv("AGENT_STORE_BACKEND", "memory").strip().lower(),
            agent_redis_url=os.getenv("AGENT_REDIS_URL", "redis://redis:6379/1").strip(),
            store_namespace=os.getenv("AGENT_STORE_NAMESPACE", "npd:agent-hub:v1").strip(),
        )


settings = HubSettings.from_env()
