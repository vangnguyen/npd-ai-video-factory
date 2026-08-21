from __future__ import annotations

from abc import ABC, abstractmethod

from .models import (
    AgentDescriptor,
    AgentName,
    AgentReport,
    AgentTask,
    PlannedAction,
    RiskLevel,
)


def action(
    *,
    agent: AgentName,
    title: str,
    description: str,
    tool: str,
    risk: RiskLevel = RiskLevel.LOW,
    requires_approval: bool = False,
    approval_reason: str | None = None,
    payload: dict[str, object] | None = None,
) -> PlannedAction:
    return PlannedAction(
        agent=agent,
        title=title,
        description=description,
        tool=tool,
        risk=risk,
        requires_approval=requires_approval,
        approval_reason=approval_reason,
        payload=payload or {},
    )


class BaseAgent(ABC):
    name: AgentName
    role: str
    capabilities: tuple[str, ...]

    @property
    def descriptor(self) -> AgentDescriptor:
        return AgentDescriptor(
            name=self.name,
            role=self.role,
            capabilities=list(self.capabilities),
        )

    @abstractmethod
    def plan(self, task: AgentTask) -> AgentReport:
        raise NotImplementedError


class MarketingLeaderAgent(BaseAgent):
    name = AgentName.MARKETING_LEADER
    role = "Lập kế hoạch marketing, phân bổ ưu tiên và theo dõi hiệu quả tăng trưởng."
    capabilities = (
        "campaign planning",
        "budget recommendations",
        "funnel analysis",
        "KPI review",
        "SEO and paid media coordination",
    )

    def plan(self, task: AgentTask) -> AgentReport:
        return AgentReport(
            agent=self.name,
            summary=f"Chuyển mục tiêu '{task.objective}' thành kế hoạch marketing có KPI, kênh và nhịp review.",
            priorities=[
                "Xác định mục tiêu kinh doanh và KPI đầu ra trước khi chọn kênh.",
                "Ưu tiên kênh/nội dung theo tác động dự kiến và chi phí thực thi.",
                "Thiết lập vòng review tuần để cắt hoạt động kém hiệu quả và tăng hoạt động tốt.",
            ],
            actions=[
                action(
                    agent=self.name,
                    title="Tổng hợp marketing scorecard",
                    description="Đọc dữ liệu campaign, website và lead để lập scorecard theo kênh.",
                    tool="analytics.read",
                    payload={"objective": task.objective},
                ),
                action(
                    agent=self.name,
                    title="Đề xuất điều chỉnh ngân sách",
                    description="Đề xuất tăng/giảm ngân sách theo CPL, conversion và chất lượng lead.",
                    tool="ads.budget.update",
                    risk=RiskLevel.HIGH,
                    requires_approval=True,
                    approval_reason="Thay đổi ngân sách quảng cáo tạo tác động tài chính thực.",
                ),
            ],
            metrics_to_watch=["qualified leads", "CPL", "conversion rate", "CAC", "revenue contribution"],
            handoffs=[AgentName.CONTENT_TREND, AgentName.SALES],
        )


class ContentTrendAgent(BaseAgent):
    name = AgentName.CONTENT_TREND
    role = "Tìm trend, nghiên cứu chủ đề, chấm điểm ý tưởng và tạo content brief."
    capabilities = (
        "trend research",
        "idea scoring",
        "content briefs",
        "hook generation",
        "monetization fit",
    )

    def plan(self, task: AgentTask) -> AgentReport:
        return AgentReport(
            agent=self.name,
            summary=f"Xây research backlog và chấm điểm ý tưởng phục vụ mục tiêu '{task.objective}'.",
            priorities=[
                "Tìm tín hiệu mới từ thị trường, social và đối thủ.",
                "Chấm ý tưởng theo viral potential, cạnh tranh, monetization và độ khó sản xuất.",
                "Chỉ chuyển ý tưởng đạt ngưỡng sang Video Producer.",
            ],
            actions=[
                action(
                    agent=self.name,
                    title="Research trend và đối thủ",
                    description="Thu thập tín hiệu trend, định dạng đang tăng và khoảng trống nội dung.",
                    tool="research.search",
                    payload={"objective": task.objective},
                ),
                action(
                    agent=self.name,
                    title="Tạo idea shortlist",
                    description="Tạo shortlist có hook, angle, monetization path và điểm ưu tiên.",
                    tool="content.idea_score",
                ),
            ],
            metrics_to_watch=["trend velocity", "idea score", "hook strength", "production difficulty", "monetization fit"],
            handoffs=[AgentName.VIDEO_PRODUCER, AgentName.SOCIAL_MEDIA],
        )


class VideoProducerAgent(BaseAgent):
    name = AgentName.VIDEO_PRODUCER
    role = "Biến ý tưởng thành video brief và điều phối pipeline sản xuất video."
    capabilities = (
        "script planning",
        "storyboard",
        "shot planning",
        "video job submission",
        "quality-control handoff",
    )

    def plan(self, task: AgentTask) -> AgentReport:
        return AgentReport(
            agent=self.name,
            summary=f"Chuẩn hóa '{task.objective}' thành production brief có hook, scene, voice, subtitle và QC.",
            priorities=[
                "Chốt mục tiêu video, nền tảng, thời lượng và CTA.",
                "Tạo script/storyboard theo scene để voice và subtitle bám khung hình.",
                "Giữ human review trước khi phát hành nội dung ra kênh công khai.",
            ],
            actions=[
                action(
                    agent=self.name,
                    title="Tạo production brief",
                    description="Tạo brief gồm hook, script, storyboard, asset needs, voice và CTA.",
                    tool="video.brief.create",
                    payload={"objective": task.objective},
                ),
                action(
                    agent=self.name,
                    title="Tạo video job",
                    description="Đẩy brief đã hợp lệ sang NPD AI Video Factory và chờ QC/review.",
                    tool="video.jobs.create",
                    risk=RiskLevel.MEDIUM,
                ),
            ],
            metrics_to_watch=["render success", "subtitle sync", "audio quality", "QC pass rate", "review turnaround"],
            handoffs=[AgentName.SOCIAL_MEDIA],
        )


class SocialMediaAgent(BaseAgent):
    name = AgentName.SOCIAL_MEDIA
    role = "Phân phối, tái sử dụng và tối ưu nội dung theo từng nền tảng social."
    capabilities = (
        "cross-platform adaptation",
        "caption planning",
        "content calendar",
        "publishing preparation",
        "performance review",
    )

    def plan(self, task: AgentTask) -> AgentReport:
        return AgentReport(
            agent=self.name,
            summary=f"Chuẩn bị kế hoạch phân phối đa nền tảng cho '{task.objective}'.",
            priorities=[
                "Tạo phiên bản phù hợp TikTok, YouTube Shorts, Facebook Reels và Instagram Reels.",
                "Tách hook/caption/CTA theo hành vi từng nền tảng.",
                "Không tự publish khi chưa có phê duyệt nội dung cuối.",
            ],
            actions=[
                action(
                    agent=self.name,
                    title="Tạo distribution package",
                    description="Chuẩn bị caption, title, hashtag, thumbnail brief và lịch đề xuất.",
                    tool="social.package.create",
                    payload={"objective": task.objective},
                ),
                action(
                    agent=self.name,
                    title="Publish nội dung",
                    description="Đăng nội dung đã duyệt lên các kênh được chọn.",
                    tool="social.publish",
                    risk=RiskLevel.HIGH,
                    requires_approval=True,
                    approval_reason="Đăng công khai đại diện cho thương hiệu và có thể gây tác động danh tiếng.",
                ),
            ],
            metrics_to_watch=["views", "retention", "completion rate", "CTR", "affiliate/lead conversion"],
            handoffs=[AgentName.MARKETING_LEADER],
        )


class SalesAgent(BaseAgent):
    name = AgentName.SALES
    role = "Ưu tiên lead, chuẩn bị tư vấn và hỗ trợ follow-up cho đội sales."
    capabilities = (
        "lead scoring",
        "sales brief",
        "follow-up recommendations",
        "objection handling",
        "next-best-action",
    )

    def plan(self, task: AgentTask) -> AgentReport:
        return AgentReport(
            agent=self.name,
            summary=f"Biến mục tiêu '{task.objective}' thành danh sách next-best-action cho sales.",
            priorities=[
                "Ưu tiên lead theo intent, recency, budget fit và hành vi.",
                "Chuẩn bị briefing trước cuộc gọi thay vì để sale đọc toàn bộ lịch sử.",
                "Theo dõi lead nóng chưa được chăm sóc và follow-up quá hạn.",
            ],
            actions=[
                action(
                    agent=self.name,
                    title="Chấm điểm và xếp hàng lead",
                    description="Tạo danh sách lead ưu tiên cùng lý do và next-best-action.",
                    tool="crm.leads.read",
                    payload={"objective": task.objective},
                ),
                action(
                    agent=self.name,
                    title="Liên hệ khách hàng",
                    description="Gửi tin nhắn/email hoặc kích hoạt hành động liên hệ đã chuẩn bị.",
                    tool="sales.contact.send",
                    risk=RiskLevel.HIGH,
                    requires_approval=True,
                    approval_reason="Liên hệ khách hàng là hành động bên ngoài cần người phụ trách duyệt.",
                ),
            ],
            metrics_to_watch=["response rate", "appointment rate", "qualified lead rate", "follow-up SLA", "conversion"],
            handoffs=[AgentName.CRM_MANAGER, AgentName.MARKETING_LEADER],
        )


class CRMManagerAgent(BaseAgent):
    name = AgentName.CRM_MANAGER
    role = "Kiểm soát chất lượng dữ liệu CRM, pipeline và kỷ luật follow-up."
    capabilities = (
        "CRM hygiene",
        "duplicate detection",
        "pipeline anomaly detection",
        "follow-up SLA review",
        "data-quality recommendations",
    )

    def plan(self, task: AgentTask) -> AgentReport:
        return AgentReport(
            agent=self.name,
            summary=f"Kiểm tra sức khỏe CRM và dữ liệu liên quan đến '{task.objective}'.",
            priorities=[
                "Phát hiện lead thiếu dữ liệu, trùng lặp hoặc sai nguồn.",
                "Cảnh báo lead nóng chưa được xử lý và cơ hội bị đứng pipeline.",
                "Tách thao tác sửa dữ liệu khỏi thao tác đọc/phân tích để có approval rõ ràng.",
            ],
            actions=[
                action(
                    agent=self.name,
                    title="CRM health audit",
                    description="Đọc CRM để phát hiện dữ liệu thiếu, lead trùng và follow-up quá hạn.",
                    tool="crm.audit.read",
                    payload={"objective": task.objective},
                ),
                action(
                    agent=self.name,
                    title="Cập nhật CRM",
                    description="Áp dụng tag/stage/field corrections đã được xác nhận.",
                    tool="crm.records.update",
                    risk=RiskLevel.MEDIUM,
                    requires_approval=True,
                    approval_reason="Ghi dữ liệu vào CRM có thể ảnh hưởng pipeline và báo cáo kinh doanh.",
                ),
            ],
            metrics_to_watch=["missing-field rate", "duplicate rate", "overdue follow-up", "stale opportunities", "pipeline hygiene"],
            handoffs=[AgentName.SALES],
        )


SPECIALIST_AGENTS: dict[AgentName, BaseAgent] = {
    AgentName.MARKETING_LEADER: MarketingLeaderAgent(),
    AgentName.CONTENT_TREND: ContentTrendAgent(),
    AgentName.VIDEO_PRODUCER: VideoProducerAgent(),
    AgentName.SOCIAL_MEDIA: SocialMediaAgent(),
    AgentName.SALES: SalesAgent(),
    AgentName.CRM_MANAGER: CRMManagerAgent(),
}


ROUTING_KEYWORDS: dict[AgentName, tuple[str, ...]] = {
    AgentName.MARKETING_LEADER: ("marketing", "quảng cáo", "ads", "seo", "campaign", "ngân sách", "kpi"),
    AgentName.CONTENT_TREND: ("trend", "content", "ý tưởng", "chủ đề", "viral", "hook", "niche"),
    AgentName.VIDEO_PRODUCER: ("video", "script", "storyboard", "voice", "subtitle", "render"),
    AgentName.SOCIAL_MEDIA: ("tiktok", "youtube", "facebook", "reel", "instagram", "social", "đăng bài"),
    AgentName.SALES: ("sales", "sale", "khách", "tư vấn", "chăm sóc", "follow-up", "booking"),
    AgentName.CRM_MANAGER: (
        "crm",
        "espo",
        "pipeline",
        "contact",
        "data",
        "khách hàng",
        "chăm sóc",
        "follow-up",
    ),
}


BROAD_OBJECTIVE_KEYWORDS = (
    "quản lý công việc",
    "điều hành",
    "tổng quan",
    "toàn bộ",
    "doanh nghiệp",
    "hệ thống",
    "command center",
)


def select_agents(task: AgentTask) -> list[AgentName]:
    preferred = [name for name in task.preferred_agents if name in SPECIALIST_AGENTS]
    if preferred:
        return list(dict.fromkeys(preferred))

    text = task.objective.casefold()
    if any(keyword in text for keyword in BROAD_OBJECTIVE_KEYWORDS):
        return list(SPECIALIST_AGENTS)

    scored: list[tuple[int, AgentName]] = []
    for name, keywords in ROUTING_KEYWORDS.items():
        score = sum(1 for keyword in keywords if keyword in text)
        if score:
            scored.append((score, name))
    scored.sort(key=lambda item: (-item[0], item[1].value))

    if scored:
        return [name for _, name in scored[:3]]

    return [
        AgentName.MARKETING_LEADER,
        AgentName.CONTENT_TREND,
        AgentName.SALES,
        AgentName.CRM_MANAGER,
    ]
