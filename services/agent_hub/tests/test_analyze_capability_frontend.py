from pathlib import Path
import json
import shutil
import subprocess
import pytest
from npd_agent_hub.dashboard import command_center_html

@pytest.mark.parametrize("google",[False,True])
def test_actual_dashboard_capability_states_and_action_guards(google):
    executable=shutil.which("node")
    assert executable, "Node is required for actual dashboard JS regression"
    fixture=Path(__file__).with_name("analyze_capability_browser_fixture.js")
    response=command_center_html(browser_login_enabled=google)
    old_fixture=Path(__file__).parent/"fixtures/viewer_analyze_enabled.v1.json"
    result=subprocess.run([executable,str(fixture),str(old_fixture)],input=response.body,capture_output=True,timeout=30,shell=False)
    assert result.returncode==0,result.stderr.decode("utf-8","replace")
    value=json.loads(result.stdout)
    assert value["viewer_ui"]=="disabled" and value["viewer_action_requests"]==0
    assert value["production_requests"]==0
    assert value["old_behavior"]=="shared Analyze enabled for Viewer"
    assert b"__ANALYZE_CAPABILITY__" not in response.body
