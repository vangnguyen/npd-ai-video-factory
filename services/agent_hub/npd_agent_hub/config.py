from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class HubSettings:
    video_api_url: str = "http://api:8000"
    espocrm_url: str = ""
    espocrm_api_key: str = ""
    espocrm_opportunity_campaign_field: str = ""
    espocrm_journey_stage_map_json: str = ""
    n8n_executor_webhook_url: str = ""
    request_timeout_seconds: float = 30.0
    store_backend: str = "memory"
    agent_redis_url: str = "redis://redis:6379/1"
    agent_redis_password_file: str = field(default="", repr=False)
    store_namespace: str = "npd:agent-hub:v1"
    auth_mode: str = "disabled"
    viewer_token: str = ""
    operator_token: str = ""
    owner_token: str = ""
    browser_auth_mode: str = "disabled"
    public_base_url: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    session_signing_key: str = field(default="", repr=False)
    session_ttl_seconds: int = 28800
    owner_emails: tuple[str, ...] = ()
    operator_emails: tuple[str, ...] = ()
    viewer_emails: tuple[str, ...] = ()
    meta_ads_account_id: str = ""
    meta_ads_access_token: str = ""
    meta_graph_version: str = ""
    ga4_property_id: str = ""
    ga4_service_account_file: str = ""
    social_meta_page_id: str = ""
    social_meta_access_token: str = ""
    social_meta_graph_version: str = ""
    social_insights_url: str = ""
    social_insights_token: str = ""
    attribution_receipt_signing_key: str = field(default="", repr=False)
    attribution_receipt_key_id: str = "npd-attribution-v1"
    attribution_verification_keys_file: str = ""
    attribution_delivery_max_attempts: int = 4
    attribution_freshness_slos_json: str = ""
    provider_health_scheduler_enabled: bool = False
    provider_health_scheduler_interval_seconds: int = 300

    @classmethod
    def from_env(cls) -> "HubSettings":
        def boolean(name: str, default: bool = False) -> bool:
            raw = os.getenv(name, "true" if default else "false").strip().lower()
            if raw not in {"true", "false"}:
                raise ValueError(f"{name} must be true or false")
            return raw == "true"

        def email_list(name: str) -> tuple[str, ...]:
            return tuple(
                dict.fromkeys(
                    value.strip().lower()
                    for value in os.getenv(name, "").split(",")
                    if value.strip()
                )
            )

        return cls(
            video_api_url=os.getenv("VIDEO_API_URL", "http://api:8000").rstrip("/"),
            espocrm_url=os.getenv("ESPOCRM_URL", "").rstrip("/"),
            espocrm_api_key=os.getenv("ESPOCRM_API_KEY", "").strip(),
            espocrm_opportunity_campaign_field=os.getenv(
                "ESPOCRM_OPPORTUNITY_CAMPAIGN_FIELD", ""
            ).strip(),
            espocrm_journey_stage_map_json=os.getenv(
                "ESPOCRM_JOURNEY_STAGE_MAP_JSON", ""
            ).strip(),
            n8n_executor_webhook_url=os.getenv("N8N_AGENT_EXECUTOR_WEBHOOK_URL", "").strip(),
            request_timeout_seconds=float(os.getenv("AGENT_TOOL_TIMEOUT_SECONDS", "30")),
            store_backend=os.getenv("AGENT_STORE_BACKEND", "memory").strip().lower(),
            agent_redis_url=os.getenv("AGENT_REDIS_URL", "redis://redis:6379/1").strip(),
            agent_redis_password_file=os.getenv(
                "AGENT_REDIS_PASSWORD_FILE", ""
            ).strip(),
            store_namespace=os.getenv("AGENT_STORE_NAMESPACE", "npd:agent-hub:v1").strip(),
            auth_mode=os.getenv("AGENT_AUTH_MODE", "disabled").strip().lower(),
            viewer_token=os.getenv("AGENT_VIEWER_TOKEN", "").strip(),
            operator_token=os.getenv("AGENT_OPERATOR_TOKEN", "").strip(),
            owner_token=os.getenv("AGENT_OWNER_TOKEN", "").strip(),
            browser_auth_mode=os.getenv("AGENT_BROWSER_AUTH_MODE", "disabled").strip().lower(),
            public_base_url=os.getenv("AGENT_PUBLIC_BASE_URL", "").strip().rstrip("/"),
            google_client_id=os.getenv("AGENT_GOOGLE_CLIENT_ID", "").strip(),
            google_client_secret=os.getenv("AGENT_GOOGLE_CLIENT_SECRET", "").strip(),
            session_signing_key=os.getenv("AGENT_SESSION_SIGNING_KEY", "").strip(),
            session_ttl_seconds=int(os.getenv("AGENT_SESSION_TTL_SECONDS", "28800")),
            owner_emails=email_list("AGENT_OWNER_EMAILS"),
            operator_emails=email_list("AGENT_OPERATOR_EMAILS"),
            viewer_emails=email_list("AGENT_VIEWER_EMAILS"),
            meta_ads_account_id=os.getenv("META_ADS_ACCOUNT_ID", "").strip(),
            meta_ads_access_token=os.getenv("META_ADS_ACCESS_TOKEN", "").strip(),
            meta_graph_version=os.getenv("META_GRAPH_VERSION", "").strip(),
            ga4_property_id=os.getenv("GA4_PROPERTY_ID", "").strip(),
            ga4_service_account_file=os.getenv("GA4_SERVICE_ACCOUNT_FILE", "").strip(),
            social_meta_page_id=os.getenv("SOCIAL_META_PAGE_ID", "").strip(),
            social_meta_access_token=os.getenv("SOCIAL_META_ACCESS_TOKEN", "").strip(),
            social_meta_graph_version=os.getenv("SOCIAL_META_GRAPH_VERSION", "").strip(),
            social_insights_url=os.getenv("SOCIAL_INSIGHTS_URL", "").strip(),
            social_insights_token=os.getenv("SOCIAL_INSIGHTS_TOKEN", "").strip(),
            attribution_receipt_signing_key=(
                os.getenv("AGENT_ATTRIBUTION_ACTIVE_SIGNING_KEY", "").strip()
                or os.getenv("AGENT_ATTRIBUTION_RECEIPT_SIGNING_KEY", "").strip()
            ),
            attribution_receipt_key_id=(
                os.getenv("AGENT_ATTRIBUTION_ACTIVE_KEY_ID", "").strip()
                or os.getenv(
                    "AGENT_ATTRIBUTION_RECEIPT_KEY_ID", "npd-attribution-v1"
                ).strip()
            ),
            attribution_verification_keys_file=os.getenv(
                "AGENT_ATTRIBUTION_VERIFICATION_KEYS_FILE", ""
            ).strip(),
            attribution_delivery_max_attempts=int(
                os.getenv("AGENT_ATTRIBUTION_DELIVERY_MAX_ATTEMPTS", "4")
            ),
            attribution_freshness_slos_json=os.getenv(
                "AGENT_ATTRIBUTION_FRESHNESS_SLOS_JSON", ""
            ).strip(),
            provider_health_scheduler_enabled=boolean(
                "AGENT_PROVIDER_HEALTH_SCHEDULER_ENABLED"
            ),
            provider_health_scheduler_interval_seconds=int(
                os.getenv("AGENT_PROVIDER_HEALTH_SCHEDULER_INTERVAL_SECONDS", "300")
            ),
        )


settings = HubSettings.from_env()
