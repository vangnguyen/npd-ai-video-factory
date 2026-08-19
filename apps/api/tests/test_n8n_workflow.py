import json
from pathlib import Path
from uuid import UUID


def test_sprint_1_n8n_workflow_is_inactive_bounded_and_uses_sample_request() -> None:
    root = Path(__file__).resolve().parents[3]
    workflow = json.loads(
        (root / "workflows" / "n8n" / "sprint-1-smoke-test.json").read_text(encoding="utf-8")
    )
    sample = json.loads(
        (root / "examples" / "vinhomes-green-paradise.request.json").read_text(encoding="utf-8")
    )

    UUID(workflow["id"])
    assert workflow["active"] is False
    nodes = {node["name"]: node for node in workflow["nodes"]}
    assert {
        "Create Video Job",
        "Wait Before Poll",
        "Get Job Status",
        "Terminal Status?",
        "Return Smoke Result",
    } <= nodes.keys()

    assignments = nodes["Configure Smoke Test"]["parameters"]["assignments"]["assignments"]
    embedded_request = next(item["value"] for item in assignments if item["name"] == "request")
    assert embedded_request.startswith("=")
    assert json.loads(embedded_request[1:]) == sample

    terminal_expression = nodes["Terminal Status?"]["parameters"]["conditions"]["conditions"][0][
        "leftValue"
    ]
    assert "$runIndex >= 59" in terminal_expression
    assert "awaiting_review" in terminal_expression
    assert "failed" in terminal_expression
    assert "SMOKE_TEST_TIMEOUT" in nodes["Return Smoke Result"]["parameters"]["jsCode"]
