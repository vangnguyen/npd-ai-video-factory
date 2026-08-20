from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .models import (
    AnswerStatus,
    BusinessAnswer,
    BusinessAnswerItem,
    CommandCenterReport,
    ExecutionStatus,
    AgentTask,
    ToolExecutionResult,
)


CRM_READ_TOOLS = {"crm.leads.read", "crm.audit.read"}
ACTIVE_LEAD_STATUSES = {"New", "Assigned", "In Process", "Recycled"}


def infer_crm_stale_days(task: AgentTask) -> int:
    configured = task.context.get("crm_stale_days")
    if configured is not None:
        try:
            return max(1, min(int(configured), 365))
        except (TypeError, ValueError):
            pass
    match = re.search(r"(\d{1,3})\s*ngày", task.objective.casefold())
    if match:
        return max(1, min(int(match.group(1)), 365))
    return 7


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


def _lead_priority(
    record: dict[str, Any],
    *,
    age_days: int | None,
    desired_contact_overdue: bool,
    stale_days: int,
) -> tuple[str, int]:
    score = 0
    interest = record.get("cMucDoQuanTam")
    score += {"Nong": 40, "Am": 20, "Lanh": 5}.get(str(interest), 0)
    if desired_contact_overdue:
        score += 30
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

    stale_days = infer_crm_stale_days(task)
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
        age_days = max(0, (now - last_activity).days) if last_activity else None
        desired_contact = _parse_datetime(record.get("cThoiGianLienHeMongMuon"))
        desired_contact_overdue = bool(desired_contact and desired_contact < now)
        is_unassigned = not record.get("assignedUserId")
        has_contact = bool(record.get("hasEmail") or record.get("hasPhone"))
        needs_attention = bool(
            status == "New"
            or is_unassigned
            or desired_contact_overdue
            or (age_days is not None and age_days >= stale_days)
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
        if age_days is not None and age_days >= stale_days:
            reasons.append(f"{age_days} ngày chưa có cập nhật")
        if not has_contact:
            reasons.append("thiếu email và số điện thoại hợp lệ")
            missing_contact += 1

        priority, priority_score = _lead_priority(
            record,
            age_days=age_days,
            desired_contact_overdue=desired_contact_overdue,
            stale_days=stale_days,
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

    summary = (
        f"Đã kiểm tra {len(records)} lead và phát hiện {len(answer_items)} lead cần chăm sóc "
        f"theo ngưỡng {stale_days} ngày."
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
            and action.tool not in CRM_READ_TOOLS
            and action.status.value != "executed"
        }
    )
    if unsupported_reads:
        caveats.append("Chưa có adapter dữ liệu thật cho: " + ", ".join(unsupported_reads) + ".")

    evidence = []
    for tool, execution in latest_success.items():
        count = len(execution.data.get("list") or execution.data.get("records") or [])
        evidence.append(f"{tool}: thành công, {count} bản ghi")

    return BusinessAnswer(
        status=status,
        title="Kết quả kiểm tra lead cần chăm sóc",
        summary=summary,
        metrics={
            "Lead đã kiểm tra": len(records),
            "Cần chăm sóc": len(answer_items),
            "Ưu tiên cao": high_priority,
            "Chưa phân công": unassigned,
            "Thiếu thông tin liên hệ": missing_contact,
            "Ngưỡng quá hạn (ngày)": stale_days,
        },
        items=answer_items,
        recommendations=[
            "Xử lý lead ưu tiên cao trước, sau đó đến lead quá hạn lâu nhất.",
            "Chỉ phê duyệt liên hệ hoặc cập nhật CRM sau khi người phụ trách kiểm tra từng đề xuất.",
        ],
        caveats=caveats,
        evidence=evidence,
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
    if crm_related:
        return _crm_answer(task, report, executions, now=reference_time)

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
