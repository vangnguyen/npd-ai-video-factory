from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .models import (
    AnswerStatus,
    BusinessAnswer,
    BusinessAnswerItem,
    CommandCenterReport,
    AgentTask,
    ExecutionStatus,
    ToolExecutionResult,
)


CRM_READ_TOOLS = {"crm.leads.read", "crm.audit.read"}
ANALYTICS_READ_TOOLS = {"analytics.read"}
SUPPORTED_READ_TOOLS = CRM_READ_TOOLS | ANALYTICS_READ_TOOLS
ACTIVE_LEAD_STATUSES = {"New", "Assigned", "In Process", "Recycled"}
DEFAULT_CARE_SLA_MINUTES = {
    "New": 15,
    "Assigned": 15,
    "In Process": 24 * 60,
    "Recycled": 24 * 60,
}


def _explicit_crm_stale_days(task: AgentTask) -> int | None:
    configured = task.context.get("crm_stale_days")
    if configured is not None:
        try:
            return max(1, min(int(configured), 365))
        except (TypeError, ValueError):
            pass
    match = re.search(r"(\d{1,3})\s*ngày", task.objective.casefold())
    if match:
        return max(1, min(int(match.group(1)), 365))
    return None


def infer_crm_stale_days(task: AgentTask) -> int:
    """Backward-compatible uniform threshold used only when explicitly supplied."""
    return _explicit_crm_stale_days(task) or 7


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            parsed = datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_int(value: object) -> int | None:
    try:
        return int(value) if value is not None and str(value).strip() else None
    except (TypeError, ValueError):
        return None


def _age_text(age_minutes: int | None) -> str:
    if age_minutes is None:
        return "không xác định được thời gian cập nhật"
    if age_minutes >= 1440:
        return f"{age_minutes // 1440} ngày chưa có cập nhật"
    if age_minutes >= 60:
        return f"{age_minutes // 60} giờ chưa có cập nhật"
    return f"{age_minutes} phút chưa có cập nhật"


def _sla_text(minutes: int) -> str:
    if minutes == 1440:
        return "24 giờ"
    if minutes % 1440 == 0:
        return f"{minutes // 1440} ngày"
    if minutes % 60 == 0:
        return f"{minutes // 60} giờ"
    return f"{minutes} phút"


def _lead_priority(
    record: dict[str, Any],
    *,
    age_days: int | None,
    desired_contact_overdue: bool,
    stale_days: int,
    care_sla_overdue: bool,
) -> tuple[str, int]:
    score = 0
    interest = record.get("cMucDoQuanTam")
    score += {"Nong": 40, "Am": 20, "Lanh": 5}.get(str(interest), 0)
    if desired_contact_overdue:
        score += 30
    if care_sla_overdue:
        score += 20
    if not record.get("assignedUserId"):
        score += 25
    if record.get("status") == "New":
        score += 20
    if age_days is not None:
        score += 20 if age_days >= 30 else 12 if age_days >= 14 else 6 if age_days >= stale_days else 0
    lead_score = _safe_int(record.get("cDiemLead"))
    if lead_score is not None:
        score += min(30, max(0, round(lead_score * 0.3)))
    return ("high" if score >= 60 else "medium" if score >= 30 else "low", score)


def _crm_answer(
    task: AgentTask,
    report: CommandCenterReport,
    executions: list[ToolExecutionResult],
    *,
    now: datetime,
) -> BusinessAnswer:
    latest_result: dict[str, ToolExecutionResult] = {}
    for execution in executions:
        if execution.tool in CRM_READ_TOOLS and execution.tool not in latest_result:
            latest_result[execution.tool] = execution
    latest_success = {
        tool: execution
        for tool, execution in latest_result.items()
        if execution.status == ExecutionStatus.SUCCEEDED
    }
    failed_tools = sorted(
        tool
        for tool, execution in latest_result.items()
        if execution.status == ExecutionStatus.FAILED
    )

    lead_execution = latest_success.get("crm.leads.read")
    audit_execution = latest_success.get("crm.audit.read")
    source = lead_execution or audit_execution
    records: list[dict[str, Any]] = []
    reported_total: object = None
    if source:
        raw_records = source.data.get("list") or source.data.get("records") or []
        records = [row for row in raw_records if isinstance(row, dict)]
        reported_total = source.data.get("total")
        if reported_total is None:
            reported_total = source.data.get("reported_total")

    explicit_stale_days = _explicit_crm_stale_days(task)
    stale_days = explicit_stale_days or 7
    items: list[tuple[int, BusinessAnswerItem]] = []
    unassigned = 0
    missing_contact = 0
    high_priority = 0

    for record in records:
        status = str(record.get("status") or "Không rõ")
        if status not in ACTIVE_LEAD_STATUSES:
            continue
        last_activity = (
            _parse_datetime(record.get("streamUpdatedAt"))
            or _parse_datetime(record.get("modifiedAt"))
            or _parse_datetime(record.get("createdAt"))
        )
        age_minutes = (
            max(0, int((now - last_activity).total_seconds() // 60))
            if last_activity
            else None
        )
        age_days = age_minutes // 1440 if age_minutes is not None else None
        care_sla_minutes = (
            explicit_stale_days * 1440
            if explicit_stale_days is not None
            else DEFAULT_CARE_SLA_MINUTES.get(status, 7 * 1440)
        )
        care_sla_overdue = bool(
            age_minutes is not None and age_minutes >= care_sla_minutes
        )
        desired_contact = _parse_datetime(record.get("cThoiGianLienHeMongMuon"))
        desired_contact_overdue = bool(desired_contact and desired_contact < now)
        is_unassigned = not record.get("assignedUserId")
        has_contact = bool(record.get("hasEmail") or record.get("hasPhone"))
        needs_attention = bool(
            status == "New"
            or is_unassigned
            or desired_contact_overdue
            or care_sla_overdue
        )
        if not needs_attention:
            continue

        reasons: list[str] = []
        if status == "New":
            reasons.append("lead vẫn ở trạng thái New")
        if is_unassigned:
            reasons.append("chưa có người phụ trách")
            unassigned += 1
        if desired_contact_overdue:
            reasons.append("đã quá thời gian liên hệ mong muốn")
        if care_sla_overdue:
            reasons.append(
                f"{_age_text(age_minutes)} (quá SLA {_sla_text(care_sla_minutes)})"
            )
        if not has_contact:
            reasons.append("thiếu email và số điện thoại hợp lệ")
            missing_contact += 1

        priority, priority_score = _lead_priority(
            record,
            age_days=age_days,
            desired_contact_overdue=desired_contact_overdue,
            stale_days=stale_days,
            care_sla_overdue=care_sla_overdue,
        )
        if priority == "high":
            high_priority += 1

        if not has_contact:
            recommendation = "Bổ sung thông tin liên hệ trước khi giao sale follow-up."
        elif is_unassigned:
            recommendation = "Phân công sale phụ trách và đặt lịch follow-up trong ngày."
        elif desired_contact_overdue or record.get("cMucDoQuanTam") == "Nong":
            recommendation = "Ưu tiên liên hệ trong ngày và ghi nhận kết quả vào CRM."
        else:
            recommendation = "Sale kiểm tra lịch sử, liên hệ lại và cập nhật bước tiếp theo trong CRM."

        contact_channels = []
        if record.get("hasPhone"):
            contact_channels.append("điện thoại")
        if record.get("hasEmail"):
            contact_channels.append("email")
        details: dict[str, str | int | float | bool | None] = {
            "Trạng thái": status,
            "Mức độ quan tâm": str(record.get("cMucDoQuanTam") or "Chưa xác định"),
            "Điểm lead": _safe_int(record.get("cDiemLead")),
            "Phụ trách": str(record.get("assignedUserName") or "Chưa phân công"),
            "Dự án quan tâm": str(record.get("cDuAnQuanTam") or "Chưa ghi nhận"),
            "Số ngày chưa cập nhật": age_days,
            "SLA chăm sóc": _sla_text(care_sla_minutes),
            "Kênh có thể liên hệ": ", ".join(contact_channels) or "Chưa có",
            "Nguồn": str(record.get("source") or "Chưa xác định"),
        }
        items.append(
            (
                priority_score,
                BusinessAnswerItem(
                    entity_id=str(record.get("id") or "") or None,
                    title=str(record.get("name") or f"Lead {record.get('id', '')}").strip(),
                    priority=priority,
                    reason="; ".join(reasons),
                    details=details,
                    recommended_action=recommendation,
                ),
            )
        )

    items.sort(key=lambda item: (-item[0], item[1].title.casefold()))
    answer_items = [item for _, item in items]
    completed = bool(source)
    status = AnswerStatus.COMPLETED if completed and not failed_tools else AnswerStatus.PARTIAL
    if not source:
        status = AnswerStatus.FAILED if failed_tools else AnswerStatus.PLANNED

    threshold_description = (
        f"ngưỡng {explicit_stale_days} ngày"
        if explicit_stale_days is not None
        else "SLA theo trạng thái (New/Assigned: 15 phút; In Process/Recycled: 24 giờ)"
    )
    summary = (
        f"Đã kiểm tra {len(records)} lead và phát hiện {len(answer_items)} lead cần chăm sóc "
        f"theo {threshold_description}."
        if source
        else "Chưa đọc được dữ liệu Lead từ EspoCRM nên chưa thể đưa ra danh sách cần chăm sóc."
    )
    caveats = [
        "EspoCRM chưa có trường lastContactAt riêng; hệ thống đang dùng streamUpdatedAt/modifiedAt làm chỉ báo gần nhất và ghi rõ tiêu chí này."
    ]
    if reported_total is not None and _safe_int(reported_total) not in (None, len(records)):
        caveats.append(
            f"Kết quả hiện phân tích {len(records)} trên tổng số {reported_total} lead trả về bởi CRM."
        )
    if failed_tools:
        caveats.append("Không thực thi được: " + ", ".join(sorted(failed_tools)) + ".")

    unsupported_reads = sorted(
        {
            action.tool
            for agent_report in report.reports
            for action in agent_report.actions
            if not action.requires_approval
            and action.tool not in SUPPORTED_READ_TOOLS
            and action.status.value != "executed"
        }
    )
    if unsupported_reads:
        caveats.append("Chưa có adapter dữ liệu thật cho: " + ", ".join(unsupported_reads) + ".")

    evidence = []
    for tool, execution in latest_success.items():
        count = len(execution.data.get("list") or execution.data.get("records") or [])
        evidence.append(f"{tool}: thành công, {count} bản ghi")

    metrics: dict[str, str | int | float | bool] = {
        "Lead đã kiểm tra": len(records),
        "Cần chăm sóc": len(answer_items),
        "Ưu tiên cao": high_priority,
        "Chưa phân công": unassigned,
        "Thiếu thông tin liên hệ": missing_contact,
    }
    if explicit_stale_days is not None:
        metrics["Ngưỡng quá hạn (ngày)"] = explicit_stale_days
    else:
        metrics["SLA New/Assigned (phút)"] = 15
        metrics["SLA In Process/Recycled (giờ)"] = 24

    return BusinessAnswer(
        status=status,
        title="Kết quả kiểm tra lead cần chăm sóc",
        summary=summary,
        metrics=metrics,
        items=answer_items,
        recommendations=[
            "Xử lý lead ưu tiên cao trước, sau đó đến lead quá hạn lâu nhất.",
            "Chỉ phê duyệt liên hệ hoặc cập nhật CRM sau khi người phụ trách kiểm tra từng đề xuất.",
        ],
        caveats=caveats,
        evidence=evidence,
    )


def _analytics_answer(
    task: AgentTask,
    executions: list[ToolExecutionResult],
) -> BusinessAnswer:
    latest = next(
        (item for item in executions if item.tool in ANALYTICS_READ_TOOLS),
        None,
    )
    if latest is None or latest.status != ExecutionStatus.SUCCEEDED:
        detail = latest.detail if latest else "analytics.read chưa được thực thi"
        return BusinessAnswer(
            status=AnswerStatus.FAILED if latest else AnswerStatus.PLANNED,
            title="Báo cáo hiệu quả nguồn lead",
            summary="Chưa đọc được dữ liệu CRM để lập báo cáo marketing/funnel đã kiểm chứng.",
            caveats=[detail or "Không có chi tiết lỗi."],
        )

    data = latest.data
    analyzed = _safe_int(data.get("records_analyzed")) or 0
    recent = _safe_int(data.get("recent_leads")) or 0
    converted = _safe_int(data.get("converted_leads")) or 0
    contactable = _safe_int(data.get("contactable_leads")) or 0
    stale = _safe_int(data.get("stale_active_leads")) or 0
    period_days = _safe_int(data.get("period_days")) or 30

    objective = task.objective.casefold()
    if "dự án" in objective:
        distribution_key, distribution_label = "by_project", "Dự án"
    elif "trạng thái" in objective or "pipeline" in objective:
        distribution_key, distribution_label = "by_status", "Trạng thái"
    elif "mức độ" in objective or "quan tâm" in objective:
        distribution_key, distribution_label = "by_interest", "Mức độ quan tâm"
    else:
        distribution_key, distribution_label = "by_source", "Nguồn lead"

    items: list[BusinessAnswerItem] = []
    for row in list(data.get(distribution_key) or [])[:5]:
        if not isinstance(row, dict):
            continue
        source = str(row.get("name") or "Chưa xác định")
        count = _safe_int(row.get("count")) or 0
        share = float(row.get("share_pct") or 0)
        items.append(
            BusinessAnswerItem(
                title=f"{distribution_label}: {source}",
                priority="high" if items == [] and count else "normal",
                reason=f"Đóng góp {count} lead, chiếm {share:g}% dữ liệu đang phân tích.",
                details={"Số lead": count, "Tỷ trọng (%)": share},
                recommended_action=(
                    "Đối chiếu chất lượng và tỷ lệ chuyển đổi của nhóm này trước khi tăng nguồn lực."
                ),
            )
        )

    recommendations = []
    if stale:
        recommendations.append(f"Ưu tiên xử lý {stale} lead active đã quá 24 giờ chưa cập nhật.")
    if contactable < analyzed:
        recommendations.append(
            f"Hoàn thiện kênh liên hệ cho {analyzed - contactable} lead trước khi đánh giá hiệu quả nguồn."
        )
    if items:
        recommendations.append(
            f"So sánh {distribution_label.casefold()} lớn nhất với trạng thái Converted và mức độ quan tâm trước khi điều chỉnh nguồn lực."
        )
    recommendations.append(
        "Chỉ phê duyệt thay đổi ngân sách sau khi bổ sung chi phí Ads, click và conversion từ nền tảng quảng cáo."
    )

    caveats = [
        "Báo cáo hiện dựa trên EspoCRM Lead read-only; chưa có Ads spend, impressions, clicks hoặc website sessions nên chưa kết luận được CPL, CAC hay ROAS.",
        "Lead quá hạn dùng streamUpdatedAt/modifiedAt làm chỉ báo hoạt động gần nhất, không phải lịch sử liên hệ chuyên biệt.",
    ]
    if not bool(data.get("coverage_complete", True)):
        caveats.append(
            f"Chỉ phân tích {analyzed} trên tổng số {data.get('reported_total')} lead do giới hạn trang đọc."
        )

    return BusinessAnswer(
        status=AnswerStatus.COMPLETED,
        title="Báo cáo hiệu quả nguồn lead từ CRM",
        summary=(
            f"Đã phân tích {analyzed} lead: {recent} lead tạo trong {period_days} ngày, "
            f"{converted} lead Converted và {stale} lead active quá 24 giờ chưa cập nhật."
        ),
        metrics={
            "Lead đã phân tích": analyzed,
            f"Lead mới {period_days} ngày": recent,
            "Đã chuyển đổi": converted,
            "Tỷ lệ Converted (%)": float(data.get("conversion_rate_pct") or 0),
            "Có kênh liên hệ": contactable,
            "Active quá 24 giờ": stale,
        },
        items=items,
        recommendations=recommendations,
        caveats=caveats,
        evidence=[
            f"analytics.read: thành công từ {data.get('data_source', 'nguồn chỉ-đọc')}, {analyzed} bản ghi"
        ],
    )


def synthesize_business_answer(
    task: AgentTask,
    report: CommandCenterReport,
    executions: list[ToolExecutionResult],
    *,
    now: datetime | None = None,
) -> BusinessAnswer:
    reference_time = now or datetime.now(timezone.utc)
    crm_related = any(
        action.tool in CRM_READ_TOOLS
        for agent_report in report.reports
        for action in agent_report.actions
    )
    analytics_related = any(
        action.tool in ANALYTICS_READ_TOOLS
        for agent_report in report.reports
        for action in agent_report.actions
    )
    if crm_related:
        return _crm_answer(task, report, executions, now=reference_time)
    if analytics_related:
        return _analytics_answer(task, executions)

    failed = [item.tool for item in executions if item.status == ExecutionStatus.FAILED]
    succeeded = [item.tool for item in executions if item.status == ExecutionStatus.SUCCEEDED]
    return BusinessAnswer(
        status=(
            AnswerStatus.COMPLETED
            if succeeded and not failed
            else AnswerStatus.PARTIAL
            if succeeded
            else AnswerStatus.FAILED
            if failed
            else AnswerStatus.PLANNED
        ),
        title="Kết quả xử lý yêu cầu",
        summary=report.executive_summary,
        recommendations=[
            priority
            for agent_report in report.reports
            for priority in agent_report.priorities
        ][:8],
        caveats=(
            ["Chưa có adapter dữ liệu thật phù hợp; nội dung hiện là kế hoạch, không phải kết luận đã kiểm chứng."]
            if not succeeded
            else []
        ),
        evidence=[f"{tool}: thành công" for tool in succeeded],
    )
