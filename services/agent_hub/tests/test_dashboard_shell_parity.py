from npd_agent_hub.dashboard import DASHBOARD_HTML, command_center_html


def test_static_token_shell_retains_actual_dashboard_and_capability_gate():
    response = command_center_html(browser_login_enabled=False)
    assert response.body == DASHBOARD_HTML.encode("utf-8")
    assert response.headers["Cache-Control"] == "no-store"
    assert b'id="sharedAnalyze" class="primary" data-analyze disabled' in response.body
    assert b"sessionStorage.getItem('npd_agent_token')" in response.body


def test_google_shell_retains_capability_gate_and_authenticated_identity():
    response = command_center_html(browser_login_enabled=True)
    assert response.headers["Cache-Control"] == "no-store"
    assert b'span id="identity"' in response.body and b'id="token"' not in response.body
    assert b"sessionStorage.getItem('npd_agent_token')" not in response.body
    assert b"$('identity').textContent=me.subject" in response.body
    assert b"acceptCapabilityBootstrap(me,generation)" in response.body
    assert b"if(r.status===401){location.href='/login'" in response.body
