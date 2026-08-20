import re

from npd_agent_hub.dashboard import DASHBOARD_HTML, command_center_html


def test_dashboard_lists_exactly_twenty_business_questions():
    questions = re.findall(r"\{group:'[^']+',agent:'[^']+',text:'", DASHBOARD_HTML)

    assert len(questions) == 20
    assert "CRM & Sales" in DASHBOARD_HTML
    assert "Marketing" in DASHBOARD_HTML
    assert "Website & GA4" in DASHBOARD_HTML
    assert "Social & Content" in DASHBOARD_HTML
    assert "Điều hành" in DASHBOARD_HTML


def test_dashboard_prioritizes_approvals_and_limits_visible_tasks():
    assert DASHBOARD_HTML.index("Approval queue") < DASHBOARD_HTML.index("5 task gần nhất")
    assert "const recent=(s.tasks||[]).slice(0,5)" in DASHBOARD_HTML
    assert "for(const t of tasks.slice(0,20))" in DASHBOARD_HTML
    assert "confirm(`${verb} action này?" in DASHBOARD_HTML


def test_dashboard_renders_campaign_comparison_as_vnd_table():
    assert "Bảng so sánh chiến dịch" in DASHBOARD_HTML
    assert "Số tiền đã chi (VND)" in DASHBOARD_HTML
    assert "CPL Meta" in DASHBOARD_HTML
    assert "Intl.NumberFormat('vi-VN'" in DASHBOARD_HTML


def test_google_login_dashboard_keeps_questions_and_removes_token_input():
    response = command_center_html(browser_login_enabled=True)
    content = response.body.decode("utf-8")

    assert 'id="identity"' in content
    assert 'id="token"' not in content
    assert "20 câu hỏi nghiệp vụ gợi ý" in content
    assert "renderQuestions();refreshAll();" in content
