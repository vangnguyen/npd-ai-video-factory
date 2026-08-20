from __future__ import annotations

from fastapi.responses import HTMLResponse


DASHBOARD_HTML = r'''<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>NPD AI Command Center</title>
<style>
:root{font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#172033;background:#f5f7fb}*{box-sizing:border-box}body{margin:0}.top{background:#111827;color:#fff;padding:18px 22px;display:flex;gap:14px;align-items:center;justify-content:space-between;flex-wrap:wrap}.top h1{font-size:20px;margin:0}.auth{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.auth input,.auth select,.auth button,textarea,button{font:inherit}.auth input{width:min(420px,70vw);padding:9px 11px;border:1px solid #4b5563;border-radius:8px;background:#fff;color:#111827}.auth button,.auth a,.primary{padding:9px 13px;border:0;border-radius:8px;background:#2563eb;color:#fff;cursor:pointer;text-decoration:none}.wrap{max-width:1280px;margin:auto;padding:20px}.notice{padding:12px 14px;border-radius:10px;background:#fff;border:1px solid #e5e7eb;margin-bottom:16px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}.card{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:15px}.metric{font-size:28px;font-weight:750;margin-top:5px}.muted{color:#667085;font-size:13px}.section{margin-top:20px}.section h2{font-size:17px}.panel{background:#fff;border:1px solid #e5e7eb;border-radius:12px;overflow:auto}table{width:100%;border-collapse:collapse;min-width:760px}th,td{text-align:left;padding:11px;border-bottom:1px solid #edf0f4;font-size:13px;vertical-align:top}th{background:#f8fafc}.tag{display:inline-block;padding:3px 7px;border-radius:999px;background:#eef2ff;margin:2px;font-size:12px}.danger{background:#b42318!important}.secondary{background:#475467!important}textarea{width:100%;min-height:76px;padding:10px;border:1px solid #d0d5dd;border-radius:8px}.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.smallbtn{padding:6px 9px;border:0;border-radius:7px;background:#2563eb;color:#fff;cursor:pointer;font-size:12px}.smallbtn.secondary{background:#667085}.smallbtn.danger{background:#b42318}.error{color:#b42318}.ok{color:#027a48}.answer{border-left:4px solid #2563eb}.answer h3{margin:0 0 8px}.answer ul{padding-left:20px}.answer-item{margin-top:10px;padding:12px;border-radius:9px;background:#f8fafc}.answer-item.high{border-left:4px solid #b42318}.answer-item.medium{border-left:4px solid #f79009}.answer-item.low{border-left:4px solid #12b76a}.answer-metrics{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}.answer-metrics span{padding:6px 9px;background:#eef2ff;border-radius:8px;font-size:12px}@media(max-width:600px){.wrap{padding:12px}.top{padding:14px}.auth input{width:100%}}
</style>
</head>
<body>
<div class="top"><h1>NPD AI Command Center</h1><div class="auth"><input id="token" type="password" autocomplete="off" placeholder="Bearer token (owner/operator/viewer)"/><button onclick="saveToken()">Kết nối</button></div></div>
<div class="wrap">
<div id="status" class="notice">Nhập token để tải dữ liệu. Token chỉ lưu trong sessionStorage của trình duyệt.</div>
<div class="grid">
<div class="card"><div class="muted">Tasks gần đây</div><div id="mTasks" class="metric">–</div></div>
<div class="card"><div class="muted">Approval đang chờ</div><div id="mPending" class="metric">–</div></div>
<div class="card"><div class="muted">Đã thực thi</div><div id="mExecuted" class="metric">–</div></div>
<div class="card"><div class="muted">Execution failed</div><div id="mFailed" class="metric">–</div></div>
</div>
<div class="section"><h2>Tạo nhiệm vụ</h2><div class="card"><textarea id="objective" placeholder="Ví dụ: Kiểm tra CRM, tìm lead nóng chưa follow-up và đề xuất việc cần làm ngày mai"></textarea><div class="row" style="margin-top:8px"><button class="primary" onclick="createTask()">Giao cho Commander</button><span class="muted">Cần role operator hoặc owner.</span></div></div></div>
<div class="section"><h2>Kết quả trả lời</h2><div id="answer" class="notice">Chọn “Xem kết quả” hoặc giao một nhiệm vụ mới.</div></div>
<div class="section"><div class="row" style="justify-content:space-between"><h2>Tasks</h2><button class="smallbtn secondary" onclick="refreshAll()">Làm mới</button></div><div class="panel"><table><thead><tr><th>Task</th><th>Mục tiêu</th><th>Agents</th><th>Actions</th><th>Pending</th><th>Failed</th><th>Kết quả</th></tr></thead><tbody id="tasks"></tbody></table></div></div>
<div class="section"><h2>Approval queue</h2><div id="approvals" class="grid"></div></div>
<div class="section"><h2>Audit gần đây</h2><div class="panel"><table><thead><tr><th>Thời gian</th><th>Event</th><th>Task</th><th>Action</th><th>Agent</th></tr></thead><tbody id="audit"></tbody></table></div></div>
</div>
<script>
const $=id=>document.getElementById(id);let token=sessionStorage.getItem('npd_agent_token')||'';$('token').value=token;
function setStatus(text,kind=''){const e=$('status');e.textContent=text;e.className='notice '+kind}
function saveToken(){token=$('token').value.trim();sessionStorage.setItem('npd_agent_token',token);refreshAll()}
async function api(path,options={}){const headers=Object.assign({},options.headers||{});if(token)headers.Authorization='Bearer '+token;if(options.body)headers['Content-Type']='application/json';const r=await fetch(path,Object.assign({},options,{headers}));if(!r.ok){let d;try{d=await r.json()}catch{d={detail:r.statusText}};throw new Error((d&&d.detail)||('HTTP '+r.status))}return r.status===204?null:r.json()}
function esc(v){return String(v??'').replace(/[&<>"']/g,s=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[s]))}
async function refreshAll(){try{const me=await api('/api/v1/whoami');const s=await api('/api/v1/command-center?limit=50&audit_limit=50');setStatus('Đã xác thực: '+me.role+' · storage: '+s.storage_backend,'ok');render(s)}catch(e){setStatus(e.message,'error')}}
function render(s){$('mTasks').textContent=s.tasks.length;$('mPending').textContent=s.approvals_pending;$('mExecuted').textContent=s.tasks.reduce((n,t)=>n+(t.executed_actions||0),0);$('mFailed').textContent=s.execution_failures;$('tasks').innerHTML=s.tasks.map(t=>`<tr><td><code>${esc(t.task_id)}</code></td><td>${esc(t.objective)}</td><td>${(t.selected_agents||[]).map(a=>`<span class="tag">${esc(a)}</span>`).join('')}</td><td>${t.total_actions}</td><td>${t.approvals_pending}</td><td>${t.failed_actions}</td><td><div class="row"><button class="smallbtn" onclick="showAnswer('${esc(t.task_id)}')">Xem kết quả</button><button class="smallbtn secondary" onclick="reanalyze('${esc(t.task_id)}')">Phân tích lại</button></div></td></tr>`).join('');$('audit').innerHTML=(s.recent_audit||[]).map(a=>`<tr><td>${esc(a.created_at)}</td><td>${esc(a.event_type)}</td><td><code>${esc(a.task_id)}</code></td><td>${esc(a.action_id||'')}</td><td>${esc(a.agent||'')}</td></tr>`).join('');loadApprovals(s.tasks)}
function renderAnswer(r){const a=r&&r.answer;if(!a){$('answer').className='notice';$('answer').innerHTML='Nhiệm vụ chưa có kết luận từ dữ liệu thật.';return}const metrics=Object.entries(a.metrics||{}).map(([k,v])=>`<span><strong>${esc(k)}:</strong> ${esc(v)}</span>`).join('');const items=(a.items||[]).map(i=>`<div class="answer-item ${esc(i.priority)}"><strong>${esc(i.title)}</strong> · ${esc(i.priority)}<div>${esc(i.reason)}</div><div class="muted">${Object.entries(i.details||{}).map(([k,v])=>`${esc(k)}: ${esc(v??'—')}`).join(' · ')}</div><div><strong>Đề xuất:</strong> ${esc(i.recommended_action)}</div></div>`).join('');const rec=(a.recommendations||[]).map(x=>`<li>${esc(x)}</li>`).join('');const caveats=(a.caveats||[]).map(x=>`<li>${esc(x)}</li>`).join('');const evidence=(a.evidence||[]).map(x=>`<li>${esc(x)}</li>`).join('');$('answer').className='card answer';$('answer').innerHTML=`<div class="row" style="justify-content:space-between"><h3>${esc(a.title)}</h3><span class="tag">${esc(a.status)}</span></div><p>${esc(a.summary)}</p><div class="answer-metrics">${metrics}</div>${items||'<div class="muted">Không có mục nghiệp vụ cần liệt kê.</div>'}${rec?`<h4>Việc nên làm</h4><ul>${rec}</ul>`:''}${evidence?`<h4>Bằng chứng</h4><ul>${evidence}</ul>`:''}${caveats?`<h4>Giới hạn cần biết</h4><ul>${caveats}</ul>`:''}`}
async function showAnswer(task){try{const r=await api('/api/v1/agent-tasks/'+encodeURIComponent(task));renderAnswer(r);$('answer').scrollIntoView({behavior:'smooth',block:'start'})}catch(e){setStatus(e.message,'error')}}
async function reanalyze(task){try{setStatus('Đang đọc lại dữ liệu và phân tích…');const r=await api('/api/v1/agent-tasks/'+encodeURIComponent(task)+'/analyze',{method:'POST'});renderAnswer(r);setStatus('Đã cập nhật kết quả '+r.task_id,'ok');await refreshAll()}catch(e){setStatus(e.message,'error')}}
async function loadApprovals(tasks){const out=[];for(const t of tasks.slice(0,20)){try{const r=await api('/api/v1/agent-tasks/'+encodeURIComponent(t.task_id));for(const a of (r.approvals_required||[]))out.push({task:t,action:a})}catch{}}$('approvals').innerHTML=out.length?out.map(x=>`<div class="card"><div class="muted">${esc(x.action.agent)} · ${esc(x.action.tool)}</div><strong>${esc(x.action.title)}</strong><p>${esc(x.action.description)}</p><div class="row"><button class="smallbtn" onclick="decision('${esc(x.task.task_id)}','${esc(x.action.action_id)}',true)">Approve</button><button class="smallbtn danger" onclick="decision('${esc(x.task.task_id)}','${esc(x.action.action_id)}',false)">Reject</button></div></div>`).join(''):'<div class="notice">Không có approval đang chờ.</div>'}
async function decision(task,action,approved){try{await api(`/api/v1/agent-tasks/${encodeURIComponent(task)}/actions/${encodeURIComponent(action)}/decision`,{method:'POST',body:JSON.stringify({approved})});await refreshAll()}catch(e){setStatus(e.message,'error')}}
async function createTask(){const objective=$('objective').value.trim();if(objective.length<3)return setStatus('Mục tiêu quá ngắn','error');try{setStatus('Đang đọc dữ liệu và phân tích yêu cầu…');const r=await api('/api/v1/agent-tasks',{method:'POST',body:JSON.stringify({objective})});$('objective').value='';renderAnswer(r);setStatus('Đã có kết quả cho task '+r.task_id,'ok');await refreshAll()}catch(e){setStatus(e.message,'error')}}
if(token)refreshAll();
</script>
</body></html>'''


def command_center_html(*, browser_login_enabled: bool = False) -> HTMLResponse:
    content = DASHBOARD_HTML
    if browser_login_enabled:
        content = content.replace(
            '<div class="auth"><input id="token" type="password" autocomplete="off" placeholder="Bearer token (owner/operator/viewer)"/><button onclick="saveToken()">Kết nối</button></div>',
            '<div class="auth"><span id="identity">Đang xác thực…</span><a class="secondary" href="/logout">Đăng xuất</a></div>',
        ).replace(
            'Nhập token để tải dữ liệu. Token chỉ lưu trong sessionStorage của trình duyệt.',
            'Đang tải dữ liệu Command Center…',
        ).replace(
            "const $=id=>document.getElementById(id);let token=sessionStorage.getItem('npd_agent_token')||'';$('token').value=token;",
            "const $=id=>document.getElementById(id);let token='';",
        ).replace(
            "function saveToken(){token=$('token').value.trim();sessionStorage.setItem('npd_agent_token',token);refreshAll()}",
            "function saveToken(){}",
        ).replace(
            "if(!r.ok){let d;try{d=await r.json()}catch{d={detail:r.statusText}};throw new Error((d&&d.detail)||('HTTP '+r.status))}",
            "if(r.status===401){location.href='/login';throw new Error('login required')}if(!r.ok){let d;try{d=await r.json()}catch{d={detail:r.statusText}};throw new Error((d&&d.detail)||('HTTP '+r.status))}",
        ).replace(
            "setStatus('Đã xác thực: '+me.role+' · storage: '+s.storage_backend,'ok');render(s)",
            "$('identity').textContent=me.subject+' · '+me.role;setStatus('Đã xác thực: '+me.subject+' · '+me.role+' · storage: '+s.storage_backend,'ok');render(s)",
        ).replace("if(token)refreshAll();", "refreshAll();")
    return HTMLResponse(
        content,
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'",
        },
    )
