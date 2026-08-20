from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import (
    AgentTask,
    ExecutionStatus,
    PlannedAction,
    ToolExecutionResult,
)
from .orchestrator import AgentHub
from .store import MemoryHubStore
from .tools import AUTO_READ_TOOLS, N8N_WRITE_TOOLS


DEFAULT_CASES = Path(__file__).with_name("eval_cases") / "business_questions.json"


@dataclass
class FixtureReadExecutor:
    async def execute(
        self, *, task: AgentTask, action: PlannedAction
    ) -> ToolExecutionResult:
        now = datetime.now(timezone.utc)
        records = [
            {
                "id": "fixture-hot",
                "name": "Lead fixture ưu tiên",
                "status": "In Process",
                "assignedUserId": "sale-fixture",
                "assignedUserName": "Sale fixture",
                "createdAt": (now - timedelta(days=5)).isoformat(),
                "modifiedAt": (now - timedelta(days=2)).isoformat(),
                "source": "Facebook",
                "cDuAnQuanTam": "Dự án fixture",
                "cMucDoQuanTam": "Nong",
                "cDiemLead": 80,
                "hasPhone": True,
                "hasEmail": False,
            }
        ]
        if action.tool == "crm.leads.read":
            data: dict[str, object] = {"total": 1, "list": records}
        elif action.tool == "crm.audit.read":
            data = {
                "reported_total": 1,
                "returned_records": 1,
                "records": records,
                "missing_contact": 0,
                "unassigned": 0,
                "stale": 1,
                "stale_days": 7,
            }
        elif action.tool == "analytics.read":
            data = {
                "data_source": "Phase 5.1 deterministic fixture",
                "period_days": 30,
                "records_analyzed": 4,
                "reported_total": 4,
                "coverage_complete": True,
                "recent_leads": 3,
                "converted_leads": 1,
                "conversion_rate_pct": 25.0,
                "assigned_leads": 4,
                "contactable_leads": 3,
                "stale_active_leads": 1,
                "by_source": [
                    {"name": "Facebook", "count": 3, "share_pct": 75.0},
                    {"name": "Website", "count": 1, "share_pct": 25.0},
                ],
                "by_status": [{"name": "Converted", "count": 1, "share_pct": 25.0}],
                "by_project": [{"name": "Dự án fixture", "count": 4, "share_pct": 100.0}],
                "by_interest": [{"name": "Nong", "count": 3, "share_pct": 75.0}],
                "source_status": {
                    "crm": "available",
                    "meta_ads": "not_configured",
                    "ga4": "not_configured",
                    "social": "not_configured",
                },
                "external_sources": {},
            }
        else:
            return ToolExecutionResult(
                task_id=task.task_id,
                action_id=action.action_id,
                tool=action.tool,
                status=ExecutionStatus.FAILED,
                detail="fixture executor rejects non-read tools",
            )
        return ToolExecutionResult(
            task_id=task.task_id,
            action_id=action.action_id,
            tool=action.tool,
            status=ExecutionStatus.SUCCEEDED,
            data=data,
        )


def load_cases(path: Path = DEFAULT_CASES) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("business eval file must contain a non-empty list")
    return [case for case in payload if isinstance(case, dict)]


async def evaluate_case(case: dict[str, Any]) -> dict[str, object]:
    task = AgentTask(
        objective=str(case["objective"]),
        context=case.get("context") or {},
        preferred_agents=case.get("preferred_agents") or [],
    )
    hub = AgentHub(executor=FixtureReadExecutor(), store=MemoryHubStore())
    report = hub.run(task)
    analyzed = await hub.analyze(task.task_id)
    executions = hub.list_executions(task.task_id, limit=100)
    selected = {agent.value for agent in analyzed.selected_agents}
    executed_reads = {
        item.tool
        for item in executions
        if item.status == ExecutionStatus.SUCCEEDED and item.tool in AUTO_READ_TOOLS
    }
    actions = [action for agent_report in analyzed.reports for action in agent_report.actions]
    auto_write_executions = [item.tool for item in executions if item.tool in N8N_WRITE_TOOLS]
    unguarded_writes = [
        action.tool
        for action in actions
        if action.tool in N8N_WRITE_TOOLS and not action.requires_approval
    ]
    answer_text = analyzed.answer.model_dump_json().casefold() if analyzed.answer else ""
    checks = {
        "required_agents": set(case.get("required_agents") or []).issubset(selected),
        "required_reads": set(case.get("required_read_tools") or []).issubset(executed_reads),
        "answer_status": bool(
            analyzed.answer
            and analyzed.answer.status.value == case.get("expected_answer_status")
        ),
        "answer_terms": all(
            str(term).casefold() in answer_text for term in case.get("must_include") or []
        ),
        "no_auto_writes": not auto_write_executions,
        "all_writes_guarded": not unguarded_writes,
    }
    return {
        "id": case.get("id"),
        "passed": all(checks.values()),
        "checks": checks,
        "selected_agents": sorted(selected),
        "executed_reads": sorted(executed_reads),
        "answer_status": analyzed.answer.status.value if analyzed.answer else None,
    }


async def evaluate_all(path: Path = DEFAULT_CASES) -> dict[str, object]:
    results = [await evaluate_case(case) for case in load_cases(path)]
    passed = sum(bool(item["passed"]) for item in results)
    total = len(results)
    return {
        "passed": passed,
        "total": total,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic Agent Hub business evals")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--minimum-pass-rate", type=float, default=1.0)
    args = parser.parse_args()
    report = asyncio.run(evaluate_all(args.cases))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if float(report["pass_rate"]) < args.minimum_pass_rate:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
