from datetime import datetime, timezone

from npd_agent_hub.answering import synthesize_business_answer
from npd_agent_hub.models import (
    AgentTask,
    CommandCenterReport,
    ExecutionStatus,
    ToolExecutionResult,
)
from npd_agent_hub.orchestrator import AgentHub


def _crm_report(task: AgentTask) -> CommandCenterReport:
    return AgentHub().run(task)


def test_crm_answer_identifies_and_prioritizes_stale_leads_without_pii():
    task = AgentTask(
        objective="Tìm lead chưa được chăm sóc quá 10 ngày",
        context={"crm_stale_days": 10},
    )
    report = _crm_report(task)
    execution = ToolExecutionResult(
        task_id=task.task_id,
        action_id="act-read",
        tool="crm.leads.read",
        status=ExecutionStatus.SUCCEEDED,
        data={
            "total": 3,
            "list": [
                {
                    "id": "hot-overdue",
                    "name": "Lead nóng quá hạn",
                    "status": "In Process",
                    "assignedUserId": "sale-1",
                    "assignedUserName": "Sale A",
                    "modifiedAt": "2026-07-01 00:00:00",
                    "cMucDoQuanTam": "Nong",
                    "cDiemLead": 90,
                    "hasPhone": True,
                    "hasEmail": False,
                },
                {
                    "id": "new-unassigned",
                    "name": "Lead mới chưa phân công",
                    "status": "New",
                    "modifiedAt": "2026-08-19 00:00:00",
                    "cMucDoQuanTam": "Am",
                    "hasPhone": False,
                    "hasEmail": False,
                },
                {
                    "id": "fresh",
                    "name": "Lead đang được chăm sóc",
                    "status": "In Process",
                    "assignedUserId": "sale-2",
                    "modifiedAt": "2026-08-19 00:00:00",
                    "hasPhone": True,
                },
            ],
        },
    )

    answer = synthesize_business_answer(
        task,
        report,
        [execution],
        now=datetime(2026, 8, 20, tzinfo=timezone.utc),
    )

    assert answer.status.value == "completed"
    assert answer.metrics["Lead đã kiểm tra"] == 3
    assert answer.metrics["Cần chăm sóc"] == 2
    assert [item.entity_id for item in answer.items] == ["hot-overdue", "new-unassigned"]
    serialized = answer.model_dump_json()
    assert "private@example.com" not in serialized
    assert "0900000000" not in serialized
    assert any("lastContactAt" in caveat for caveat in answer.caveats)


def test_crm_answer_is_honest_when_read_adapter_fails():
    task = AgentTask(objective="Kiểm tra CRM và lead")
    report = _crm_report(task)
    execution = ToolExecutionResult(
        task_id=task.task_id,
        action_id="act-read",
        tool="crm.leads.read",
        status=ExecutionStatus.FAILED,
        detail="CRM unavailable",
    )

    answer = synthesize_business_answer(task, report, [execution])

    assert answer.status.value == "failed"
    assert answer.items == []
    assert "Chưa đọc được dữ liệu" in answer.summary
