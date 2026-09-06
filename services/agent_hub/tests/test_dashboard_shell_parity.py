import hashlib

from npd_agent_hub.dashboard import command_center_html


def test_static_token_dashboard_bytes_remain_unchanged():
    response = command_center_html(browser_login_enabled=False)
    assert len(response.body) == 81636
    assert hashlib.sha256(response.body).hexdigest() == (
        "6d930ec00a96babb48d80d90bdc99e1c4829137cf9376a60e2b35915d1a6b70e"
    )


def test_google_login_dashboard_bytes_remain_unchanged():
    response = command_center_html(browser_login_enabled=True)
    assert len(response.body) == 81506
    assert hashlib.sha256(response.body).hexdigest() == (
        "05b09814ada2bbb0314121720d61026525571fe10536cd71f040e071ec8005da"
    )
