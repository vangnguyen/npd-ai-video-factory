from __future__ import annotations

from pydantic import BaseModel

from .campaign_models import ProviderStatus


class ProviderContract(BaseModel):
    provider: str
    target_system: str
    status: ProviderStatus
    required_configuration: list[str]
    live_execution_enabled: bool = False
    notes: list[str]


def campaign_provider_contracts() -> dict[str, ProviderContract]:
    """Configuration contracts only; no credential values are returned or stored."""
    return {
        "meta_ads": ProviderContract(
            provider="meta_ads_readonly",
            target_system="Meta Marketing API",
            status=ProviderStatus.READ_ONLY,
            required_configuration=["META_ADS_ACCOUNT_ID", "META_ADS_ACCESS_TOKEN", "META_GRAPH_VERSION"],
            notes=["Reuse Phase 6A read-only insights for planning", "launch and budget mutation disabled"],
        ),
        "google_ads": ProviderContract(
            provider="google_ads_interface",
            target_system="Google Ads API",
            status=ProviderStatus.NOT_CONFIGURED,
            required_configuration=["GOOGLE_ADS_CUSTOMER_ID", "GOOGLE_ADS_DEVELOPER_TOKEN_REF", "GOOGLE_ADS_OAUTH_CREDENTIAL_REF"],
            notes=["Planning/validation contract only", "do not claim live Google Ads data"],
        ),
        "email": ProviderContract(
            provider="dedicated_email_marketing_interface",
            target_system="Dedicated email marketing provider",
            status=ProviderStatus.NOT_CONFIGURED,
            required_configuration=["EMAIL_MARKETING_PROVIDER", "EMAIL_MARKETING_CREDENTIAL_REF", "EMAIL_MARKETING_SENDER_ID"],
            notes=["WordPress Gmail SMTP is explicitly excluded from bulk marketing", "bulk send disabled"],
        ),
        "zalo_zbs": ProviderContract(
            provider="zalo_zbs_oa_interface",
            target_system="Zalo OA/ZBS marketing provider",
            status=ProviderStatus.NOT_CONFIGURED,
            required_configuration=["ZBS_PROVIDER", "ZBS_OA_ID", "ZBS_CREDENTIAL_REF"],
            notes=["Do not reuse transactional GMF flow", "consent/frequency validation required", "bulk send disabled"],
        ),
        "web_landing": ProviderContract(
            provider="wordpress_sales_hub_contract",
            target_system="Existing WordPress/Sales Hub",
            status=ProviderStatus.CONTRACT_ONLY,
            required_configuration=["WORDPRESS_STAGING_TARGET", "WORDPRESS_CREDENTIAL_REF"],
            notes=["staging/preview metadata only", "production publish disabled"],
        ),
    }
