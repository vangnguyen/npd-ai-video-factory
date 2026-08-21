from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timezone

from .campaign_models import (
    ApprovalRequirement,
    ApprovalState,
    AuditMetadata,
    Campaign,
    CampaignApprovalDecision,
    CampaignAuditEvent,
    CampaignBriefRequest,
    CampaignBudget,
    CampaignChannel,
    CampaignCreate,
    CampaignDraftUpdate,
    CampaignStatus,
    CampaignSummary,
    ChannelPlan,
    CreativeBrief,
    KPITarget,
    LandingPageDraft,
    PlanningStage,
    ProviderStatus,
    SalesHandoff,
    SequenceDraft,
    TrackingContract,
    build_campaign_id,
    slug_token,
)
from .store import HubStore


ALLOWED_TRANSITIONS: dict[CampaignStatus, set[CampaignStatus]] = {
    CampaignStatus.DRAFT: {CampaignStatus.PLANNED, CampaignStatus.CANCELLED},
    CampaignStatus.PLANNED: {
        CampaignStatus.DRAFT,
        CampaignStatus.AWAITING_APPROVAL,
        CampaignStatus.CANCELLED,
    },
    CampaignStatus.AWAITING_APPROVAL: {
        CampaignStatus.PLANNED,
        CampaignStatus.APPROVED,
        CampaignStatus.CANCELLED,
    },
    CampaignStatus.APPROVED: {
        CampaignStatus.READY_TO_EXECUTE,
        CampaignStatus.CANCELLED,
    },
    CampaignStatus.READY_TO_EXECUTE: {
        CampaignStatus.ACTIVE,
        CampaignStatus.CANCELLED,
    },
    CampaignStatus.ACTIVE: {
        CampaignStatus.PAUSED,
        CampaignStatus.COMPLETED,
        CampaignStatus.CANCELLED,
    },
    CampaignStatus.PAUSED: {
        CampaignStatus.ACTIVE,
        CampaignStatus.COMPLETED,
        CampaignStatus.CANCELLED,
    },
    CampaignStatus.COMPLETED: set(),
    CampaignStatus.CANCELLED: set(),
}


SIDE_EFFECT_STATUSES = {
    CampaignStatus.ACTIVE,
    CampaignStatus.PAUSED,
    CampaignStatus.COMPLETED,
}


class CampaignService:
    """Campaign planning control plane with no production side effects in Phase 6B."""

    def __init__(self, store: HubStore, *, execution_enabled: bool = False) -> None:
        self.store = store
        self.execution_enabled = execution_enabled

    def _audit(
        self,
        campaign: Campaign,
        *,
        event_type: str,
        actor: str,
        from_status: CampaignStatus | None = None,
        scope: str | None = None,
        detail: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        self.store.append_campaign_audit(
            CampaignAuditEvent(
                campaign_id=campaign.campaign_id,
                event_type=event_type,
                actor=actor,
                from_status=from_status,
                to_status=campaign.status,
                scope=scope,
                detail=detail,
                metadata=metadata or {},
            )
        )

    def _next_id(self, request: CampaignCreate) -> str:
        prefix = (
            f"CMP-{slug_token(request.project_code, max_length=12)}-"
            f"{slug_token(request.name, max_length=20)}-{request.start_date:%Y%m}-"
        )
        existing = {
            campaign.campaign_id
            for campaign in self.store.list_campaigns(limit=1000)
            if campaign.campaign_id.startswith(prefix)
        }
        for sequence in range(1, 100):
            candidate = build_campaign_id(
                project_code=request.project_code,
                campaign_name=request.name,
                start_date=request.start_date,
                sequence=sequence,
            )
            if candidate not in existing:
                return candidate
        raise ValueError("campaign sequence is exhausted for this project/month")

    @staticmethod
    def _tracking(campaign_id: str) -> TrackingContract:
        return TrackingContract(
            campaign_id=campaign_id,
            utm_campaign=campaign_id.casefold(),
        )

    @staticmethod
    def _approval_package() -> list[ApprovalRequirement]:
        return [
            ApprovalRequirement(scope="meta_ads", action="ads.launch/budget mutation", target_system="Meta Ads", reason="Creates financial spend or changes live delivery."),
            ApprovalRequirement(scope="google_ads", action="ads.launch/budget mutation", target_system="Google Ads", reason="Creates financial spend or changes live delivery."),
            ApprovalRequirement(scope="email", action="email.bulk_send", target_system="Dedicated email marketing provider", reason="Bulk contact requires consent, audience and content approval."),
            ApprovalRequirement(scope="zalo_zbs", action="zalo_zbs.bulk_send", target_system="Zalo OA/ZBS provider", reason="Bulk messaging requires consent and frequency approval."),
            ApprovalRequirement(scope="web_landing", action="landing.production_publish", target_system="WordPress/Sales Hub", reason="Production publishing changes a public customer surface."),
            ApprovalRequirement(scope="crm", action="crm.mass_write", target_system="EspoCRM", reason="Mass writes affect pipeline and reporting."),
            ApprovalRequirement(scope="customer_contact", action="customer contact", target_system="Sales/customer channels", reason="Customer contact must be owner-approved and attributable."),
        ]

    def create(self, request: CampaignCreate, *, actor: str) -> Campaign:
        campaign_id = self._next_id(request)
        campaign = Campaign(
            campaign_id=campaign_id,
            name=request.name,
            project=request.project,
            project_code=slug_token(request.project_code, max_length=12),
            objective=request.objective,
            audience=request.audience,
            budget=request.budget,
            start_date=request.start_date,
            end_date=request.end_date,
            kpi_targets=request.kpi_targets,
            tracking=self._tracking(campaign_id),
            crm_source_refs=request.crm_source_refs
            or {
                "lead_entity": "EspoCRM Lead",
                "opportunity_entity": "EspoCRM Opportunity",
                "write_mode": "disabled",
            },
            attribution_refs=request.attribution_refs
            or {
                "model": "first_touch+last_touch placeholder",
                "revenue_attribution": "phase_7_not_implemented",
            },
            approval_package=self._approval_package(),
            audit_metadata=AuditMetadata(
                created_by=actor,
                updated_by=actor,
                owner=request.owner,
                source_request=None,
            ),
        )
        self.store.save_campaign(campaign)
        self._audit(
            campaign,
            event_type="campaign_created",
            actor=actor,
            metadata={"planning_only": True, "production_write_enabled": False},
        )
        return campaign

    def create_from_brief(self, brief: CampaignBriefRequest, *, actor: str) -> Campaign:
        text = brief.request.strip()
        normalized = text.casefold()
        month_match = re.search(r"tháng\s*(1[0-2]|0?[1-9])", normalized)
        month = int(month_match.group(1)) if month_match else datetime.now(timezone.utc).month
        today = datetime.now(timezone.utc).date()
        year = today.year + (1 if month < today.month - 6 else 0)
        start = date(year, month, 1)
        end = date(year, month, calendar.monthrange(year, month)[1])

        budget_match = re.search(r"ngân\s*sách\s*([\d.,]+)\s*(triệu|tỷ)?", normalized)
        budget_number = float((budget_match.group(1) if budget_match else "0").replace(".", "").replace(",", "."))
        unit = budget_match.group(2) if budget_match else None
        budget_amount = int(budget_number * (1_000_000_000 if unit == "tỷ" else 1_000_000 if unit == "triệu" else 1))
        if budget_amount <= 0:
            raise ValueError("business request must include a positive campaign budget")

        lead_match = re.search(r"(\d+)\s*lead", normalized)
        visit_match = re.search(r"(\d+)\s*khách\s*(?:đi\s*)?xem", normalized)
        leads = int(lead_match.group(1)) if lead_match else 100
        visits = int(visit_match.group(1)) if visit_match else max(1, round(leads * 0.1))
        project = "Vinhomes Green Paradise – Vịnh Tiên" if "vịnh tiên" in normalized else "Campaign project"
        project_code = "VGP" if "vịnh tiên" in normalized else "NPD"
        name = "Vịnh Tiên" if "vịnh tiên" in normalized else f"Campaign tháng {month}"

        campaign = self.create(
            CampaignCreate(
                name=name,
                project=project,
                project_code=project_code,
                objective=text,
                audience=[
                    "Nhà đầu tư bất động sản trung-cao cấp",
                    "Khách quan tâm Vịnh Tiên/Vinhomes Green Paradise",
                    "Lead CRM đã đồng ý nhận marketing",
                ],
                budget=CampaignBudget(amount=budget_amount, currency="VND"),
                start_date=start,
                end_date=end,
                kpi_targets=[
                    KPITarget(name="Marketing leads", target=leads, unit="lead", funnel_stage="lead"),
                    KPITarget(name="Khách đi xem", target=visits, unit="booking", funnel_stage="site_visit"),
                    KPITarget(name="Lead-to-visit", target=round(visits * 100 / leads, 2), unit="percent", funnel_stage="conversion"),
                ],
                owner=brief.owner or actor,
            ),
            actor=actor,
        )
        campaign.audit_metadata.source_request = text
        self.store.save_campaign(campaign)
        return self.refresh_plans(campaign.campaign_id, actor=actor)

    def get(self, campaign_id: str) -> Campaign:
        campaign = self.store.get_campaign(campaign_id)
        if campaign is None:
            raise KeyError(campaign_id)
        return campaign

    def list(self, *, limit: int = 50, status: CampaignStatus | None = None) -> list[Campaign]:
        return self.store.list_campaigns(limit=limit, status=status)

    def update_draft(self, campaign_id: str, update: CampaignDraftUpdate, *, actor: str) -> Campaign:
        campaign = self.get(campaign_id)
        if campaign.status not in {CampaignStatus.DRAFT, CampaignStatus.PLANNED}:
            raise ValueError("draft-safe fields can only be updated in draft/planned status")
        before = campaign.model_dump(mode="json")
        changes = update.model_dump(exclude_none=True)
        owner = changes.pop("owner", None)
        for field, value in changes.items():
            setattr(campaign, field, value)
        if owner:
            campaign.audit_metadata.owner = owner
        campaign.audit_metadata.updated_by = actor
        campaign.audit_metadata.version += 1
        campaign.updated_at = datetime.now(timezone.utc)
        # Revalidate dates/secrets after assignment.
        campaign = Campaign.model_validate(campaign.model_dump())
        self.store.save_campaign(campaign)
        self._audit(
            campaign,
            event_type="campaign_updated",
            actor=actor,
            metadata={"changed_fields": sorted(key for key in changes if before.get(key) != campaign.model_dump(mode="json").get(key))},
        )
        return campaign

    def refresh_plans(self, campaign_id: str, *, actor: str) -> Campaign:
        campaign = self.get(campaign_id)
        if campaign.status not in {CampaignStatus.DRAFT, CampaignStatus.PLANNED}:
            raise ValueError("channel plans can only be generated in draft/planned status")
        total = campaign.budget.amount
        campaign.channel_plans = [
            ChannelPlan(
                channel=CampaignChannel.META_ADS,
                specialist_agent="performance_ads",
                stage=PlanningStage.PREVIEW,
                provider_status=ProviderStatus.READ_ONLY,
                objective="Generate qualified leads with a structure ready for owner review.",
                audience=campaign.audience,
                proposed_budget=CampaignBudget(amount=round(total * 0.50), currency=campaign.budget.currency),
                deliverables=["Meta campaign/ad set/ad structure", "audience proposal", "budget pacing", "creative A/B test matrix", "UTM/source ID map"],
                structure={"campaigns": ["Prospecting", "Retargeting"], "optimization": "Lead", "launch": "disabled"},
                validation=["Meta Ads insights may be reused read-only", "no live launch or budget mutation"],
            ),
            ChannelPlan(
                channel=CampaignChannel.GOOGLE_ADS,
                specialist_agent="performance_ads",
                stage=PlanningStage.PREVIEW,
                provider_status=ProviderStatus.NOT_CONFIGURED,
                objective="Capture high-intent search demand without claiming live Google Ads data.",
                audience=["Search intent: Vịnh Tiên", "Brand/project keyword groups"],
                proposed_budget=CampaignBudget(amount=round(total * 0.25), currency=campaign.budget.currency),
                deliverables=["search campaign/ad group structure", "keyword themes", "negative keyword draft", "RSA copy draft", "conversion validation checklist"],
                structure={"campaign_type": "Search", "api_adapter": "contract_only", "live_data": "not_configured", "launch": "disabled"},
                validation=["Google Ads API credentials are not configured", "forecast values are proposals, not live performance"],
            ),
            ChannelPlan(
                channel=CampaignChannel.EMAIL,
                specialist_agent="email_marketing",
                stage=PlanningStage.PREVIEW,
                provider_status=ProviderStatus.NOT_CONFIGURED,
                objective="Nurture consented leads toward a site visit.",
                audience=["Consented CRM leads segmented by recency and interest"],
                deliverables=["segmentation", "4-step nurture sequence", "subject/content A/B drafts", "campaign tracking map"],
                structure={"provider": "dedicated_marketing_provider_required", "wordpress_gmail_smtp": "forbidden_for_bulk", "send": "disabled"},
                validation=["provider credential not configured", "bulk send remains disabled"],
            ),
            ChannelPlan(
                channel=CampaignChannel.ZALO_ZBS,
                specialist_agent="zalo_zbs_marketing",
                stage=PlanningStage.PREVIEW,
                provider_status=ProviderStatus.NOT_CONFIGURED,
                objective="Prepare consent-aware OA/ZBS follow-up and CRM handoff.",
                audience=["Consented Zalo/OA audience", "Lead segments eligible by frequency policy"],
                deliverables=["segment definition", "template/sequence drafts", "consent checks", "frequency cap", "CRM handoff"],
                structure={"provider": "zbs_oa_marketing_provider_required", "gmf_transactional_reuse": "forbidden", "send": "disabled"},
                validation=["ZBS/OA marketing provider not configured", "live message send remains disabled"],
            ),
            ChannelPlan(
                channel=CampaignChannel.WEB_LANDING,
                specialist_agent="web_landing",
                stage=PlanningStage.PREVIEW,
                provider_status=ProviderStatus.CONTRACT_ONLY,
                objective="Create a conversion-focused staging brief with complete tracking propagation.",
                audience=campaign.audience,
                proposed_budget=CampaignBudget(amount=round(total * 0.10), currency=campaign.budget.currency),
                deliverables=["landing-page brief", "CTA/form structure", "SEO/CRO checklist", "WordPress staging metadata", "tracking validation"],
                structure={"target": "existing WordPress/Sales Hub", "environment": "staging", "production_publish": "disabled"},
                validation=["staging/preview first", "no autonomous production publish"],
            ),
        ]
        campaign.creatives = [
            CreativeBrief(name="Vịnh Tiên – sống nghỉ dưỡng", format="vertical video/static", hook="Một điểm đến, ba giá trị: sống, nghỉ dưỡng và đầu tư.", message="Khám phá hệ sinh thái và tiềm năng Vịnh Tiên.", cta="Đăng ký nhận tư vấn và lịch tham quan", variants=["lifestyle", "investment proof", "site-visit invitation"], stage=PlanningStage.PREVIEW),
            CreativeBrief(name="Vịnh Tiên – bằng chứng dự án", format="carousel/video", hook="Điều gì tạo nên lợi thế dài hạn của Vịnh Tiên?", message="Tóm tắt vị trí, tiện ích và luận điểm đầu tư có nguồn kiểm chứng.", cta="Nhận tài liệu dự án", variants=["30-second", "6-card carousel"], stage=PlanningStage.PREVIEW),
        ]
        campaign.landing_pages = [
            LandingPageDraft(
                title="Vịnh Tiên tháng 9 – đăng ký tư vấn",
                target_path=f"/campaigns/{campaign.campaign_id.casefold()}",
                sections=["Hero/value proposition", "Project proof", "Audience-fit benefits", "FAQ", "Site-visit CTA"],
                cta="Đăng ký tư vấn / lịch đi xem",
                form_fields=["name", "phone", "email_optional", "interest", "consent"],
                tracking_fields=list(type(campaign.tracking).model_fields),
            )
        ]
        campaign.email_sequence_refs = [
            SequenceDraft(
                channel="email",
                provider_status=ProviderStatus.NOT_CONFIGURED,
                segment="Consented leads: new, engaged, re-engagement",
                steps=[
                    {"day": "0", "purpose": "Welcome/project value", "ab_test": "Benefit vs curiosity subject"},
                    {"day": "2", "purpose": "Proof and FAQ", "ab_test": "Location vs lifestyle"},
                    {"day": "5", "purpose": "Site-visit invitation", "ab_test": "Schedule vs consultation CTA"},
                    {"day": "10", "purpose": "Re-engagement", "ab_test": "Update vs limited slots"},
                ],
                frequency_guardrail="Max 2 marketing emails per 7 days; stop on unsubscribe",
                tracking_fields=["campaign_id", "utm_source", "utm_medium", "utm_campaign", "utm_content", "lead_id"],
            )
        ]
        campaign.zalo_zbs_sequence_refs = [
            SequenceDraft(
                channel="zalo_zbs",
                provider_status=ProviderStatus.NOT_CONFIGURED,
                segment="Explicitly consented Zalo/OA leads only",
                steps=[
                    {"step": "1", "purpose": "Project summary template", "handoff": "capture intent"},
                    {"step": "2", "purpose": "Site-visit invitation", "handoff": "create sales task draft"},
                    {"step": "3", "purpose": "Human sales handoff", "handoff": "EspoCRM/Sales Hub"},
                ],
                frequency_guardrail="Max 1 promotional message per 72 hours; transactional GMF flow is not reused",
                tracking_fields=["campaign_id", "lead_id", "consent", "template_ref", "last_touch"],
            )
        ]
        campaign.sales_handoff = SalesHandoff()
        previous = campaign.status
        campaign.status = CampaignStatus.PLANNED
        campaign.updated_at = datetime.now(timezone.utc)
        campaign.audit_metadata.updated_by = actor
        campaign.audit_metadata.version += 1
        self.store.save_campaign(campaign)
        self._audit(
            campaign,
            event_type="channel_plans_refreshed",
            actor=actor,
            from_status=previous,
            metadata={
                "specialist_agents": [
                    "performance_ads",
                    "email_marketing",
                    "zalo_zbs_marketing",
                    "web_landing",
                ],
                "execution_enabled": False,
            },
        )
        return campaign

    def request_approval(self, campaign_id: str, *, scope: str, actor: str, note: str | None = None) -> Campaign:
        campaign = self.get(campaign_id)
        if campaign.status != CampaignStatus.PLANNED:
            raise ValueError("campaign approval can only be requested from planned status")
        valid_scopes = {"campaign", *[plan.channel.value for plan in campaign.channel_plans]}
        if scope not in valid_scopes:
            raise ValueError("approval scope is not part of this campaign")
        previous = campaign.status
        campaign.status = CampaignStatus.AWAITING_APPROVAL
        for plan in campaign.channel_plans:
            if scope == "campaign" or plan.channel.value == scope:
                plan.approval_state = ApprovalState.AWAITING_APPROVAL
        campaign.updated_at = datetime.now(timezone.utc)
        campaign.audit_metadata.updated_by = actor
        campaign.audit_metadata.version += 1
        self.store.save_campaign(campaign)
        self._audit(campaign, event_type="approval_requested", actor=actor, from_status=previous, scope=scope, detail=note)
        return campaign

    def decide_approval(
        self,
        campaign_id: str,
        *,
        scope: str,
        decision: CampaignApprovalDecision,
        actor: str,
    ) -> Campaign:
        campaign = self.get(campaign_id)
        if campaign.status != CampaignStatus.AWAITING_APPROVAL:
            raise ValueError("campaign is not awaiting approval")
        matching = [plan for plan in campaign.channel_plans if scope == "campaign" or plan.channel.value == scope]
        if not matching:
            raise ValueError("approval scope is not part of this campaign")
        for plan in matching:
            plan.approval_state = ApprovalState.APPROVED if decision.approved else ApprovalState.REJECTED
        previous = campaign.status
        if scope == "campaign":
            campaign.status = CampaignStatus.APPROVED if decision.approved else CampaignStatus.PLANNED
            for requirement in campaign.approval_package:
                requirement.approved = decision.approved
        elif decision.approved and all(
            plan.approval_state == ApprovalState.APPROVED for plan in campaign.channel_plans
        ):
            campaign.status = CampaignStatus.APPROVED
        else:
            campaign.status = CampaignStatus.PLANNED
        for requirement in campaign.approval_package:
            if scope == "campaign" or requirement.scope == scope:
                requirement.approved = decision.approved
        campaign.updated_at = datetime.now(timezone.utc)
        campaign.audit_metadata.updated_by = actor
        campaign.audit_metadata.version += 1
        self.store.save_campaign(campaign)
        self._audit(
            campaign,
            event_type="approval_decided",
            actor=actor,
            from_status=previous,
            scope=scope,
            detail=decision.note,
            metadata={"approved": decision.approved, "production_side_effect": False},
        )
        return campaign

    def transition(self, campaign_id: str, *, target: CampaignStatus, actor: str, owner_authorized: bool, note: str | None = None) -> Campaign:
        campaign = self.get(campaign_id)
        if target not in ALLOWED_TRANSITIONS[campaign.status]:
            raise ValueError(f"invalid campaign transition: {campaign.status.value} -> {target.value}")
        if target in SIDE_EFFECT_STATUSES and not owner_authorized:
            raise PermissionError("owner approval is required for a side-effect lifecycle transition")
        if target == CampaignStatus.ACTIVE and not self.execution_enabled:
            raise ValueError("Phase 6B production execution is disabled; campaign cannot become active")
        previous = campaign.status
        campaign.status = target
        campaign.updated_at = datetime.now(timezone.utc)
        campaign.audit_metadata.updated_by = actor
        campaign.audit_metadata.version += 1
        self.store.save_campaign(campaign)
        self._audit(campaign, event_type="status_transitioned", actor=actor, from_status=previous, detail=note)
        return campaign

    def history(self, campaign_id: str, *, limit: int = 100) -> list[CampaignAuditEvent]:
        self.get(campaign_id)
        return self.store.list_campaign_audit(campaign_id, limit=limit)

    def summary(self, campaign_id: str) -> CampaignSummary:
        campaign = self.get(campaign_id)
        return CampaignSummary(
            campaign_id=campaign.campaign_id,
            name=campaign.name,
            project=campaign.project,
            status=campaign.status,
            budget=campaign.budget,
            kpi_targets=campaign.kpi_targets,
            channel_status={
                plan.channel.value: f"{plan.stage.value}/{plan.provider_status.value}/{plan.approval_state.value}"
                for plan in campaign.channel_plans
            },
            approvals_pending=sum(
                plan.approval_state == ApprovalState.AWAITING_APPROVAL
                for plan in campaign.channel_plans
            ),
            execution_enabled=self.execution_enabled,
            updated_at=campaign.updated_at,
        )
