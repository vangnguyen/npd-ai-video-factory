from __future__ import annotations

from collections import Counter
from datetime import timezone

from .delivery_observability import AttributionDeliveryService
from .journeys import JourneyService
from .lead_scoring import LeadScoringService
from .models import (
    AgentName,
    AgentReport,
    AgentTask,
    AnswerStatus,
    BusinessAnswer,
    BusinessAnswerItem,
)
from .phase9_sales_shadow_evaluation_models import Phase9SalesShadowEvaluationRequest
from .sales_intelligence import SalesIntelligenceService
from .sales_intelligence_models import SalesSLAStatus
from .sales_next_best_action import SalesAwareNextBestActionService
from .store import HubStore


CONTEXT_KEY = "phase9_review"
WORKFLOW_VERSION = "phase-9-marketing-review-v1"
MAX_REVIEW_CASES = 20
REVIEW_AGENTS = (
    AgentName.CRM_MANAGER,
    AgentName.SALES,
    AgentName.MARKETING_LEADER,
)
ACTION_LABELS = {
    "collect_more_evidence": "Bổ sung evidence trước khi quyết định",
    "review_sales_follow_up": "Nhân sự xem xét việc chăm sóc khách",
    "review_appointment_preparation": "Nhân sự xem xét chuẩn bị lịch hẹn",
    "review_post_visit_follow_up": "Nhân sự xem xét chăm sóc sau tham quan",
    "review_negotiation_next_step": "Nhân sự xem xét bước đàm phán tiếp theo",
    "review_customer_handoff": "Nhân sự xem xét bàn giao khách hàng",
    "review_customer_care": "Nhân sự xem xét chăm sóc khách hàng",
    "review_lost_reason": "Nhân sự xem xét nguyên nhân mất cơ hội",
    "review_reengagement": "Nhân sự xem xét khơi lại tương tác",
}
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2, "normal": 3}


def request_for_task(task: AgentTask) -> Phase9SalesShadowEvaluationRequest:
    request = Phase9SalesShadowEvaluationRequest.model_validate(task.context[CONTEXT_KEY])
    if len(request.cases) > MAX_REVIEW_CASES:
        raise ValueError("phase9_review accepts at most 20 cases per pilot task")
    return request


def plan_marketing_review(task: AgentTask) -> list[AgentReport]:
    """Specialize existing roles without proposing external execution actions."""
    request_for_task(task)
    return [
        AgentReport(
            agent=AgentName.CRM_MANAGER,
            summary="Kiểm tra Journey và chất lượng evidence đã có trong Agent Hub.",
            priorities=["Phân biệt thiếu dữ liệu với tín hiệu bất lợi đã được xác minh."],
            metrics_to_watch=["evaluated_subjects", "missing_evidence_subjects"],
            handoffs=[AgentName.SALES],
        ),
        AgentReport(
            agent=AgentName.SALES,
            summary="Dùng service Phase 9 hiện có để tính Lead Score và NBA v2.",
            priorities=["Mỗi đề xuất phải có lý do, phiên bản và evidence tham chiếu."],
            metrics_to_watch=["verified_sla_subjects", "high_priority_reviews"],
            handoffs=[AgentName.MARKETING_LEADER],
        ),
        AgentReport(
            agent=AgentName.MARKETING_LEADER,
            summary="Tổng hợp danh sách xem xét nội bộ và các dữ liệu cần bổ sung.",
            priorities=["Chỉ chuyển thông tin hỗ trợ quyết định, không tự liên hệ khách."],
            metrics_to_watch=["reviewed_subjects", "failed_subjects", "missing_inputs"],
            handoffs=[AgentName.COMMANDER],
        ),
    ]


def analyze_marketing_review(
    task: AgentTask,
    store: HubStore,
    journeys: JourneyService,
    delivery: AttributionDeliveryService,
) -> tuple[list[AgentReport], BusinessAnswer]:
    """Run the existing Phase 9 services once per unique subject, with no providers.

    This is deterministic, service-backed coordination of existing roles, not a new
    LLM agent runtime. Only the caller (AgentHub) persists its normal task/report/audit.
    The services here do not ingest evidence, create a review vote, or contact anyone.
    """
    request = request_for_task(task)
    cases = list({case.subject_ref: case for case in request.cases}.values())
    as_of = cases[0].as_of.astimezone(timezone.utc)
    sales_service = SalesIntelligenceService(store, journeys, delivery)
    scoring = LeadScoringService(journeys)
    nba = SalesAwareNextBestActionService(journeys)
    items: list[BusinessAnswerItem] = []
    evidence_refs: set[str] = set()
    failures: Counter[str] = Counter()
    missing_inputs: Counter[str] = Counter()
    verified_sla_subjects = 0
    verified_breach_subjects = 0
    missing_context_subjects = 0
    untrusted_journey_subjects = 0
    evaluated_subjects = 0

    for case in cases:
        try:
            # CRM Manager: read canonical Journey; do not synthesize CRM stages.
            projection = journeys.project(case.subject_ref)
            # Sales: reuse the signed-completeness/SLA, score and NBA policies.
            sales = sales_service.preview(case)
            score = scoring.score(
                case.subject_ref, as_of=case.as_of, sales_intelligence=sales
            )
            recommendation = nba.recommend(
                case.subject_ref, sales_intelligence=sales, lead_score=score
            )
        except (KeyError, ValueError) as exc:
            category = "not_found" if isinstance(exc, KeyError) else "invalid_evidence"
            failures[category] += 1
            items.append(
                BusinessAnswerItem(
                    entity_id=case.subject_ref,
                    title=f"Chưa đủ evidence: {case.subject_ref}",
                    priority="normal",
                    reason="Không tìm thấy hoặc không xác minh được evidence hợp lệ; không chấm điểm và không suy luận khách kém tiềm năng.",
                    details={"evaluation_status": category, "execution_enabled": False},
                    recommended_action="Bổ sung hoặc đối chiếu evidence tại hệ thống nguồn; chưa liên hệ khách tự động.",
                )
            )
            continue

        evaluated_subjects += 1
        missing = sorted(set(score.missing_inputs) | set(recommendation.missing_context))
        missing_inputs.update(missing)
        missing_context_subjects += bool(missing)
        untrusted_journey_subjects += bool(projection.untrusted_evidence_count)
        verified_sla_subjects += bool(sales.completeness_verified)
        verified_breach_subjects += bool(
            sales.completeness_verified
            and SalesSLAStatus.BREACHED
            in {sales.first_response_sla.status, sales.visit_booking_sla.status}
        )
        evidence_refs.update(recommendation.evidence_refs)
        items.append(
            BusinessAnswerItem(
                entity_id=case.subject_ref,
                title=f"Xem xét nội bộ: {case.subject_ref}",
                priority=recommendation.priority.value,
                reason=recommendation.reason,
                details={
                    "evaluation_status": "evaluated",
                    "journey_state": projection.current_state.value,
                    "lead_score": score.score,
                    "recommendation_version": recommendation.recommendation_version,
                    "recommended_action_code": recommendation.recommended_action.value,
                    "confidence": recommendation.confidence,
                    "first_response_sla": sales.first_response_sla.status.value,
                    "visit_booking_sla": sales.visit_booking_sla.status.value,
                    "completeness_verified": sales.completeness_verified,
                    "source_complete": sales.source_complete,
                    "internal_review_minutes": recommendation.sla_minutes,
                    "missing_inputs": ", ".join(missing),
                    "evidence_refs": ", ".join(recommendation.evidence_refs),
                    "as_of": as_of.isoformat(),
                    "shadow_mode": True,
                    "execution_enabled": False,
                    "customer_contact_enabled": False,
                },
                recommended_action=ACTION_LABELS[recommendation.recommended_action.value],
            )
        )

    # Marketing Leader consumes the CRM/Sales result, rather than fetching providers
    # again or re-scoring the same subjects. Priority comes only from the NBA policy.
    items.sort(key=lambda item: (PRIORITY_ORDER[item.priority], item.entity_id or ""))
    high_priority = sum(item.priority == "high" for item in items)
    failed_subjects = sum(failures.values())
    reports = plan_marketing_review(task)
    reports[0].summary = (
        f"Đọc {len(cases)} hồ sơ tham chiếu: {evaluated_subjects} đánh giá được, "
        f"{failed_subjects} thiếu hoặc không xác minh được evidence; "
        f"{untrusted_journey_subjects} có Journey evidence không tin cậy."
    )
    reports[1].summary = (
        f"Đã tính Score/NBA v2 cho {evaluated_subjects} hồ sơ bằng policy Phase 9 hiện có; "
        f"{verified_sla_subjects} có completeness đã xác minh, "
        f"{verified_breach_subjects} có SLA breach đã xác minh."
    )
    reports[2].summary = (
        f"Danh sách có {high_priority} đề xuất ưu tiên cao để nhân sự xem xét; "
        f"{missing_context_subjects} hồ sơ còn thiếu ngữ cảnh. Không tạo task liên hệ hoặc thay đổi ngân sách."
    )
    reports[2].priorities = [
        "Xem lý do và evidence trước khi quyết định hành động.",
        "Bổ sung dữ liệu thiếu; không dùng điểm này như xác suất mua hoặc dự báo doanh thu.",
    ]
    status = (
        AnswerStatus.FAILED
        if not evaluated_subjects
        else AnswerStatus.PARTIAL
        if failed_subjects or missing_context_subjects or untrusted_journey_subjects
        else AnswerStatus.COMPLETED
    )
    caveats = [
        "Chỉ đọc evidence hiện có trong Agent Hub; luồng này không gọi trực tiếp CRM, Ads hoặc provider bên ngoài.",
        "Đây là phối hợp vai trò bằng service/rule hiện có, không phải một lượt gọi LLM mới.",
        "Lead Score không phải xác suất mua. Thiếu proof completeness không được đổi thành SLA breach đã xác minh.",
        "Thời gian SLA/NBA mô tả ưu tiên xem xét nội bộ, không phải lệnh gọi hoặc nhắn khách.",
        "Task/report/audit nội bộ được lưu theo cơ chế Commander hiện có; touchpoint, heartbeat, review votes và hệ thống nguồn không bị sửa.",
        "Evidence/ref đầu vào phải là mã tham chiếu giả danh; không nhập tên, điện thoại hoặc email khách vào objective/context.",
        "as_of là thời điểm đánh giá theo contract Phase 9 hiện có; đây không phải snapshot lịch sử bất biến.",
    ]
    if missing_inputs:
        caveats.append("Dữ liệu còn thiếu: " + ", ".join(sorted(missing_inputs)))
    answer = BusinessAnswer(
        status=status,
        title="Phase 9 — Danh sách xem xét khách hàng cho Marketing và Sales",
        summary=(
            f"CRM Manager → Sales → Marketing Leader: {evaluated_subjects}/{len(cases)} "
            f"hồ sơ đánh giá được; {high_priority} đề xuất ưu tiên cao, "
            f"{failed_subjects} hồ sơ chưa đủ evidence. Không thực hiện hành động bên ngoài."
        ),
        metrics={
            "workflow_version": WORKFLOW_VERSION,
            "requested_cases": len(request.cases),
            "unique_subjects": len(cases),
            "duplicate_cases": len(request.cases) - len(cases),
            "evaluated_subjects": evaluated_subjects,
            "failed_subjects": failed_subjects,
            "missing_context_subjects": missing_context_subjects,
            "verified_sla_subjects": verified_sla_subjects,
            "verified_breach_subjects": verified_breach_subjects,
            "high_priority_reviews": high_priority,
            "shadow_mode": True,
            "external_writes_enabled": False,
            "customer_contact_enabled": False,
            "execution_enabled": False,
        },
        items=items,
        recommendations=[
            "Nhân sự xem xét các đề xuất theo ưu tiên và evidence; không tự gửi tin hoặc gọi khách.",
            "Dùng review API NBA v2 hiện có để ghi relevant/not_relevant/needs_more_context sau khi người dùng đánh giá; lượt phân tích này không tạo review vote.",
            "Chỉ mở Phase 10 theo capability được Owner phê duyệt sau khi pilot dữ liệu thật được nghiệm thu.",
        ],
        caveats=caveats,
        evidence=[WORKFLOW_VERSION, "phase-9b-nba-v2", *sorted(evidence_refs)],
        generated_at=as_of,
    )
    return reports, answer
