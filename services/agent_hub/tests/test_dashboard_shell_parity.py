import hashlib

from npd_agent_hub.dashboard import command_center_html


def test_static_token_dashboard_bytes_remain_unchanged():
    response = command_center_html(browser_login_enabled=False)
    assert len(response.body) == 95725
    assert hashlib.sha256(response.body).hexdigest() == (
        "2730a60844d833b53477985829a692beabbff8418bfd79c2b4c78f7d99d62e27"
    )


def test_google_login_dashboard_bytes_remain_unchanged():
    response = command_center_html(browser_login_enabled=True)
    assert len(response.body) == 95595
    assert hashlib.sha256(response.body).hexdigest() == (
        "d05ab01f525139d252a8fbffe7acda35462545522326b3bf6498f005a78e8ea9"
    )
