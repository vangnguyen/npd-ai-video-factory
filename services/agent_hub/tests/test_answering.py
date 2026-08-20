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


def test_default_crm_answer_uses_status_specific_care_sla():
    task = AgentTask(objective="Tìm lead chưa được chăm sóc")
    report = _crm_report(task)
    execution = ToolExecutionResult(
        task_id=task.task_id,
        action_id="act-read",
        tool="crm.leads.read",
        status=ExecutionStatus.SUCCEEDED,
        data={
            "total": 1,
            "list": [
                {
                    "id": "in-process-overdue",
                    "name": "Lead overdue",
                    "status": "In Process",
                    "assignedUserId": "sale-1",
                    "modifiedAt": "2026-08-18 00:00:00",
                    "hasPhone": True,
                }
            ],
        },
    )

    answer = synthesize_business_answer(
        task,
        report,
        [execution],
        now=datetime(2026, 8, 20, tzinfo=timezone.utc),
    )

    assert answer.metrics["SLA New/Assigned (phút)"] == 15
    assert answer.metrics["SLA In Process/Recycled (giờ)"] == 24
    assert "SLA theo trạng thái" in answer.summary
    assert "quá SLA 24 giờ" in answer.items[0].reason


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


def test_marketing_answer_uses_aggregated_crm_analytics_and_states_limits():
    task = AgentTask(objective="Báo cáo hiệu quả marketing theo nguồn lead 30 ngày")
    report = _crm_report(task)
    execution = ToolExecutionResult(
        task_id=task.task_id,
        action_id="act-analytics",
        tool="analytics.read",
        status=ExecutionStatus.SUCCEEDED,
        data={
            "data_source": "EspoCRM Lead read-only",
            "period_days": 30,
            "records_analyzed": 10,
            "reported_total": 10,
            "coverage_complete": True,
            "recent_leads": 4,
            "converted_leads": 2,
            "conversion_rate_pct": 20.0,
            "assigned_leads": 9,
            "contactable_leads": 8,
            "stale_active_leads": 3,
            "by_source": [
                {"name": "Facebook", "count": 6, "share_pct": 60.0},
                {"name": "Website", "count": 4, "share_pct": 40.0},
            ],
        },
    )

    answer = synthesize_business_answer(task, report, [execution])

    assert answer.status.value == "partial"
    assert answer.metrics["Tỷ lệ Converted (%)"] == 20.0
    assert answer.items[0].title == "Nguồn lead: Facebook"
    assert any("Chưa có Ads spend" in caveat for caveat in answer.caveats)
    assert any("analytics.read" in evidence for evidence in answer.evidence)


def test_marketing_answer_uses_available_multi_source_metrics_without_claiming_roas():
    task = AgentTask(objective="Báo cáo campaign Ads và CPL 30 ngày")
    report = _crm_report(task)
    execution = ToolExecutionResult(
        task_id=task.task_id,
        action_id="act-analytics",
        tool="analytics.read",
        status=ExecutionStatus.SUCCEEDED,
        data={
            "period_days": 30,
            "records_analyzed": 20,
            "reported_total": 20,
            "coverage_complete": True,
            "recent_leads": 10,
            "converted_leads": 2,
            "conversion_rate_pct": 10.0,
            "contactable_leads": 18,
            "stale_active_leads": 3,
            "source_status": {
                "crm": "available",
                "meta_ads": "available",
                "ga4": "available",
                "social": "available",
            },
            "external_sources": {
                "meta_ads": {
                    "metrics": {
                        "spend": 1200000,
                        "impressions": 10000,
                        "clicks": 200,
                        "reported_leads": 20,
                        "ctr_pct": 2.0,
                        "cpc": 6000,
                        "reported_cpl": 60000,
                        "currency": "VND",
                    },
                    "campaigns": [
                        {
                            "campaign_id": "cmp-1",
                            "campaign_name": "Campaign A",
                            "spend": 1200000,
                            "impressions": 10000,
                            "clicks": 200,
                            "reported_leads": 20,
                        }
                    ],
                },
                "ga4": {"metrics": {"sessions": 150, "users": 120, "key_events": 15}},
                "social": {"metrics": {"reach": 5000, "engagements": 450}},
            },
        },
    )

    answer = synthesize_business_answer(task, report, [execution])

    assert answer.status.value == "completed"
    assert answer.title == "Báo cáo marketing đa nguồn"
    assert answer.metrics["Chi phí Ads (VND)"] == 1200000
    assert answer.metrics["CPL do Meta báo cáo"] == 60000
    assert answer.metrics["Website sessions"] == 150
    assert answer.items[0].title == "Chiến dịch: Campaign A"
    assert "ROAS" not in answer.metrics
    assert any("chưa kết luận CAC hoặc ROAS" in caveat for caveat in answer.caveats)


def test_marketing_answer_does_not_claim_crm_success_when_only_ads_is_available():
    task = AgentTask(objective="Báo cáo marketing đa nguồn")
    report = _crm_report(task)
    execution = ToolExecutionResult(
        task_id=task.task_id,
        action_id="act-analytics",
        tool="analytics.read",
        status=ExecutionStatus.SUCCEEDED,
        data={
            "period_days": 30,
            "records_analyzed": 0,
            "reported_total": None,
            "coverage_complete": True,
            "source_status": {
                "crm": "failed",
                "meta_ads": "available",
                "ga4": "not_configured",
                "social": "not_configured",
            },
            "external_sources": {
                "meta_ads": {
                    "metrics": {"spend": 100, "impressions": 1000, "clicks": 10}
                }
            },
        },
    )

    answer = synthesize_business_answer(task, report, [execution])

    assert answer.status.value == "partial"
    assert answer.title == "Báo cáo marketing đa nguồn"
    assert "CRM failed" in answer.evidence[0]
    assert "CRM thành công" not in " ".join(answer.evidence)
