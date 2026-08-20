# NPD Multi-Agent Management Hub

## Mục tiêu

Agent Hub là lớp điều phối phía trên NPD AI Video Factory. Nó nhận mục tiêu kinh doanh/công việc, chọn agent chuyên môn, tạo kế hoạch hành động, gom báo cáo cho Commander, kiểm soát approval và thực thi tool theo allowlist.

- Phase 1: control plane và approval contracts.
- Phase 2: controlled tool execution cho Video API, EspoCRM read-only và n8n approved-action executor.
- Phase 3: persistence, audit log, Command Center backend và EspoCRM schema discovery.
- Phase 4: owner Command Center UI, bearer-token RBAC và EspoCRM field mapping recommendations.
- Phase 5+: evidence-backed business answers: tự chạy allowlist read-only, tổng hợp kết luận và hiển thị kết quả/giới hạn ngay trong Command Center.

Chi tiết triển khai Phase 4: `docs/PHASE_4_COMMAND_CENTER.md`.

## 7 agent

1. `commander` — định tuyến công việc, tổng hợp ưu tiên, approval, persistence và tool execution.
2. `marketing_leader` — kế hoạch marketing, funnel, KPI, đề xuất ngân sách.
3. `content_trend` — research trend, idea scoring, hook và content brief.
4. `video_producer` — production brief, script/storyboard handoff và video job.
5. `social_media` — đóng gói nội dung đa nền tảng, lịch và publishing preparation.
6. `sales` — lead scoring, sales brief, follow-up và next-best-action.
7. `crm_manager` — data hygiene, duplicate/stale lead detection và pipeline audit.

## API chính

- `GET /health`
- `GET /readyz`
- `GET /command-center`
- `GET /api/v1/whoami`
- `GET /api/v1/agents`
- `POST /api/v1/agent-tasks`
- `GET /api/v1/agent-tasks/{task_id}`
- `POST /api/v1/agent-tasks/{task_id}/analyze`
- `POST /api/v1/agent-tasks/{task_id}/actions/{action_id}/decision`
- `POST /api/v1/agent-tasks/{task_id}/actions/{action_id}/execute`
- `GET /api/v1/agent-tasks/{task_id}/executions`
- `GET /api/v1/agent-tasks/{task_id}/audit`
- `GET /api/v1/command-center`
- `GET /api/v1/integrations/espocrm/schema/{entity_type}`
- `GET /api/v1/integrations/espocrm/mapping/{entity_type}`

## Phase 4 RBAC

Production nên dùng:

```text
AGENT_AUTH_MODE=static_token
AGENT_VIEWER_TOKEN=<random-viewer-token>
AGENT_OPERATOR_TOKEN=<random-operator-token>
AGENT_OWNER_TOKEN=<random-owner-token>
AGENT_BROWSER_AUTH_MODE=google_oidc
AGENT_PUBLIC_BASE_URL=https://mkt.ngocphuongdong.com
AGENT_GOOGLE_CLIENT_ID=<dedicated-web-client-id>
AGENT_GOOGLE_CLIENT_SECRET=<dedicated-web-client-secret>
AGENT_SESSION_SIGNING_KEY=<random-value-at-least-32-characters>
AGENT_OWNER_EMAILS=nguyenvanvangct@gmail.com
```

Quyền:

- `viewer`: đọc Command Center, task, audit, execution và EspoCRM schema/mapping;
- `operator`: toàn bộ quyền viewer + tạo task + execute action hợp lệ;
- `owner`: toàn bộ quyền operator + approve/reject write action.

`AGENT_AUTH_MODE=disabled` chỉ dành cho local dev/test. `/readyz` fail nếu bật static-token auth nhưng thiếu owner token hoặc token role bị trùng.

## Owner Command Center

UI tối giản nằm tại:

```text
/command-center
```

Khi `AGENT_BROWSER_AUTH_MODE=google_oidc`, truy cập trang sẽ chuyển tới `/login` và xác minh danh tính bằng Google. Chỉ email nằm trong allowlist role mới nhận được signed session cookie `HttpOnly`, `Secure`, `SameSite=Lax`; production không lưu bearer token trong `sessionStorage`. Bearer token vẫn được giữ cho smoke test và automation không dùng trình duyệt. UI hỗ trợ xem snapshot, tạo task, xem câu trả lời có bằng chứng, phân tích lại dữ liệu, xem approval queue, approve/reject và audit gần đây.

## Evidence-backed business answer

`POST /api/v1/agent-tasks` không chỉ tạo kế hoạch. Commander tự thực thi đúng các tool trong `AUTO_READ_TOOLS`, sau đó trả về `answer` gồm trạng thái, tóm tắt, chỉ số, danh sách ưu tiên, đề xuất, bằng chứng và giới hạn dữ liệu. `POST /api/v1/agent-tasks/{task_id}/analyze` đọc lại dữ liệu hiện tại và làm mới câu trả lời.

Luồng CRM hiện hỗ trợ:

- đọc Lead thật từ EspoCRM bằng API user read-only;
- lọc lead ở trạng thái đang hoạt động theo New, chưa phân công, quá thời gian liên hệ mong muốn hoặc quá SLA chăm sóc; mặc định New/Assigned là 15 phút, In Process/Recycled là 24 giờ, và yêu cầu có số ngày cụ thể sẽ ghi đè SLA;
- xếp ưu tiên theo mức độ quan tâm, tuổi dữ liệu, trạng thái, phân công và điểm lead;
- không lưu email/số điện thoại thô trong execution/answer, chỉ lưu cờ có/không có kênh liên hệ;
- nói rõ `streamUpdatedAt`/`modifiedAt` chỉ là proxy khi CRM chưa có `lastContactAt`;
- phân biệt `completed`, `partial`, `planned`, `failed`, không biến kế hoạch thành kết luận giả khi adapter chưa có hoặc đọc dữ liệu thất bại.

Auto-analysis không chạy write tool. `crm.records.update`, `ads.budget.update`, `sales.contact.send` và `social.publish` vẫn nằm sau owner approval và executor được cấu hình riêng.

Luồng analytics marketing hiện dùng dữ liệu Lead tổng hợp từ EspoCRM read-only để trả lời theo nguồn, trạng thái, dự án và mức độ quan tâm. Kết quả có số lead mới theo kỳ, tỷ lệ Converted, khả năng liên hệ và lead active quá 24 giờ. Payload chỉ chứa số liệu tổng hợp, không chứa tên lead, email, số điện thoại hoặc người phụ trách. Nếu chưa có Ads spend, impressions, clicks và website sessions, câu trả lời phải ghi rõ chưa thể kết luận CPL, CAC hoặc ROAS.

## Phase 2 tool matrix

| Tool | Adapter | Side effect | Approval |
|---|---|---:|---:|
| `video.jobs.create` | NPD Video API | tạo internal video job | không bắt buộc |
| `crm.leads.read` | EspoCRM REST API | read-only | không |
| `crm.audit.read` | EspoCRM REST API | read-only | không |
| `analytics.read` | EspoCRM Lead aggregate | read-only | không |
| `ads.budget.update` | n8n executor | write | bắt buộc |
| `social.publish` | n8n executor | write | bắt buộc |
| `sales.contact.send` | n8n executor | write | bắt buộc |
| `crm.records.update` | n8n executor | write | bắt buộc |

Các tool planning-only như `research.search`, `content.idea_score`, `video.brief.create` và `social.package.create` chưa có adapter thực thi thật.

## Phase 3 persistence

Runtime Docker dùng Redis backend mặc định cho Agent Hub:

```text
AGENT_STORE_BACKEND=redis
AGENT_REDIS_URL=redis://redis:6379/1
AGENT_STORE_NAMESPACE=npd:agent-hub:v1
```

Video job store tiếp tục dùng Redis DB 0. Agent Hub dùng DB 1 và namespace riêng để tách dữ liệu.

Store lưu `AgentTask`, `CommandCenterReport`, trạng thái action, execution history, per-task/global audit và recent-task index.

## Audit lifecycle

Audit lifecycle gồm `task_created`, `approval_decided`, `execution_started`, `execution_succeeded`, `execution_failed`, `answer_generated`. Audit không lưu secret hoặc toàn bộ CRM payload.

Nếu một write action đã approved nhưng execution thất bại, action trở thành `execution_failed`, được đưa trở lại `approvals_required`, và không được retry cho đến khi owner approve lại.

## EspoCRM schema + mapping

Phase 3 endpoint:

```text
GET /api/v1/integrations/espocrm/schema/Lead
```

Phase 4 endpoint:

```text
GET /api/v1/integrations/espocrm/mapping/Lead
```

Mapping helper so schema thật với alias bảo thủ cho các mục đích như email, phone, source, assigned user, status, project interest, budget, intent và last contact. Không fuzzy-map field lạ; mục đích chưa chắc chắn sẽ được báo `missing` để owner review trước khi pin mapping production.

Để đọc schema thật của NPD cần cấu hình deployment:

```text
ESPOCRM_URL=https://crm.example.com
ESPOCRM_API_KEY=<read-only-api-user-key>
```

Agent Hub hiện không POST/PUT/DELETE trực tiếp tới EspoCRM.

## Video Producer -> Video API

`video.jobs.create` tái sử dụng contract `VideoJobCreate` của `POST /api/v1/video-jobs` và dùng:

```text
Idempotency-Key = agent-{task_id}-{action_id}
```

## n8n approved-action executor

Workflow mẫu `workflows/n8n/agent-hub-approved-action-executor.json` vẫn `active=false` và dry-run. Chưa có credential production cho Ads, social publisher, customer messaging hoặc CRM write.

## Environment

```text
VIDEO_API_URL=http://api:8000
AGENT_TOOL_TIMEOUT_SECONDS=30
ESPOCRM_URL=
ESPOCRM_API_KEY=
N8N_AGENT_EXECUTOR_WEBHOOK_URL=
AGENT_STORE_BACKEND=redis
AGENT_REDIS_URL=redis://redis:6379/1
AGENT_STORE_NAMESPACE=npd:agent-hub:v1
AGENT_AUTH_MODE=static_token
AGENT_VIEWER_TOKEN=
AGENT_OPERATOR_TOKEN=
AGENT_OWNER_TOKEN=
AGENT_BROWSER_AUTH_MODE=google_oidc
AGENT_PUBLIC_BASE_URL=https://mkt.ngocphuongdong.com
AGENT_GOOGLE_CLIENT_ID=
AGENT_GOOGLE_CLIENT_SECRET=
AGENT_SESSION_SIGNING_KEY=
AGENT_SESSION_TTL_SECONDS=28800
AGENT_OWNER_EMAILS=nguyenvanvangct@gmail.com
AGENT_OPERATOR_EMAILS=
AGENT_VIEWER_EMAILS=
```

Secret không commit vào repo.

## Guardrails

- Principle of least privilege cho tool adapter và user role.
- Viewer/operator không thể approve external write action.
- Read và write credentials tách riêng.
- EspoCRM adapter hiện chỉ GET.
- Write tools chỉ đi qua một configured n8n webhook.
- Commander và operator không bypass approval policy.
- Write failure phải owner approve lại.
- Token và browser session không được ghi vào Redis/audit.
- Không commit secret.
- n8n write executor mặc định inactive và dry-run.

## Còn lại sau Phase 4

1. Cấp `ESPOCRM_URL` và API key read-only trên VPS để chạy schema/mapping thật của NPD.
2. Review rồi pin mapping custom fields được chấp nhận.
3. Đặt Agent Hub sau TLS reverse proxy/VPN trước khi public exposure.
4. Thêm email operator/viewer vào allowlist sau khi owner phê duyệt.
5. Bổ sung website/Ads/social read adapters bằng credential chỉ-đọc riêng; không tái sử dụng Meta token có quyền rộng từ dịch vụ nhận lead.
6. Chỉ sau acceptance test mới bật từng production n8n write mapping.
