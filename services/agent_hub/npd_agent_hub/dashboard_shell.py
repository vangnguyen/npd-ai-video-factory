from __future__ import annotations

from fastapi.responses import HTMLResponse


def render_dashboard_html(
    dashboard_html: str, *, browser_login_enabled: bool = False
) -> HTMLResponse:
    content = dashboard_html
    if browser_login_enabled:
        content = content.replace(
            '<div class="auth"><input id="token" type="password" autocomplete="off" placeholder="Bearer token (owner/operator/viewer)"/><button onclick="saveToken()">Kết nối</button></div>',
            '<div class="auth"><span id="identity">Đang xác thực…</span><a class="secondary" href="/logout">Đăng xuất</a></div>',
        ).replace(
            'Nhập token để tải dữ liệu. Token chỉ lưu trong sessionStorage của trình duyệt.',
            'Đang tải dữ liệu Command Center…',
        ).replace(
            "const $=id=>document.getElementById(id);let token=sessionStorage.getItem('npd_agent_token')||'';$('token').value=token;let activeQuestionGroup='Tất cả';",
            "const $=id=>document.getElementById(id);let token='';let activeQuestionGroup='Tất cả';",
        ).replace(
            "function saveToken(){token=$('token').value.trim();sessionStorage.setItem('npd_agent_token',token);refreshAll()}",
            "function saveToken(){}",
        ).replace(
            "if(!r.ok){let d;try{d=await r.json()}catch{d={detail:r.statusText}};throw new Error((d&&d.detail)||('HTTP '+r.status))}",
            "if(r.status===401){location.href='/login';throw new Error('login required')}if(!r.ok){let d;try{d=await r.json()}catch{d={detail:r.statusText}};throw new Error((d&&d.detail)||('HTTP '+r.status))}",
        ).replace(
            "setStatus('Đã xác thực: '+me.role+' · storage: '+s.storage_backend,'ok');render(s);renderSources(sources)",
            "$('identity').textContent=me.subject+' · '+me.role;setStatus('Đã xác thực: '+me.subject+' · '+me.role+' · storage: '+s.storage_backend,'ok');render(s);renderSources(sources)",
        ).replace(
            "renderQuestions();if(token)refreshAll();",
            "renderQuestions();refreshAll();",
        )
    return HTMLResponse(
        content,
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'",
        },
    )
