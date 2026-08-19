# NPD Multi-Agent Management Hub

## Mục tiêu

Agent Hub là lớp điều phối phía trên NPD AI Video Factory. Nó nhận mục tiêu kinh doanh/công việc, chọn agent chuyên môn, tạo kế hoạch hành động, gom báo cáo cho Commander, kiểm soát approval và thực thi tool theo allowlist.

- Phase 1: control plane và approval contracts.
- Phase 2: controlled tool execution cho Video API, EspoCRM read-only và n8n approved-action executor.
- Phase 3: persistence, audit log, Command Center backend và EspoCRM schema discovery.

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
- `GET /api/v1/agents`
- `POST /api/v1/agent-tasks`
- `GET /api/v1/agent-tasks/{task_id}`
- `POST /api/v1/agent-tasks/{task_id}/actions/{action_id}/decision`
- `POST /api/v1/agent-tasks/{task_id}/actions/{action_id}/execute`
- `GET /api/v1/agent-tasks/{task_id}/executions`
- `GET /api/v1/agent-tasks/{task_id}/audit`
- `GET /api/v1/command-center`
- `GET /api/v1/integrations/espocrm/schema/{entity_type}`

## Phase 2 tool matrix

| Tool | Adapter | Side effect | Approval |
|---|---|---:|---:|
| `video.jobs.create` | NPD Video API | tạo internal video job | không bắt buộc |
| `crm.leads.read` | EspoCRM REST API | read-only | không |
| `crm.audit.read` | EspoCRM REST API | read-only | không |
| `ads.budget.update` | n8n executor | write | bắt buộc |
| `social.publish` | n8n executor | write | bắt buộc |
| `sales.contact.send` | n8n executor | write | bắt buộc |
| `crm.records.update` | n8n executor | write | bắt buộc |

Các tool planning-only như `analytics.read`, `research.search`, `content.idea_score`, `video.brief.create` và `social.package.create` chưa có adapter thực thi thật.

## Phase 3 persistence

Runtime Docker dùng Redis backend mặc định cho Agent Hub:

```text
AGENT_STORE_BACKEND=redis
AGENT_REDIS_URL=redis://redis:6379/1
AGENT_STORE_NAMESPACE=npd:agent-hub:v1
```

Video job store tiếp tục dùng Redis DB 0. Agent Hub dùng DB 1 và namespace riêng để tách dữ liệu.

Store lưu:

- `AgentTask`;
- `CommandCenterReport` và trạng thái từng action;
- execution history;
- per-task audit log;
- global recent audit log;
- recent-task index theo thời gian cập nhật.

`memory` backend vẫn tồn tại để test/dev. Tests dùng cả Memory store và `fakeredis` để chứng minh round-trip và phục hồi sau khi tạo một `AgentHub` instance mới.

## Audit lifecycle

Audit log không lưu secret hoặc toàn bộ payload CRM. Nó ghi các sự kiện kiểm soát:

- `task_created`;
- `approval_decided`;
- `execution_started`;
- `execution_succeeded`;
- `execution_failed`.

Metadata audit chỉ giữ thông tin cần cho kiểm soát như tool, approval result, external ID và resulting status.

Nếu một write action đã approved nhưng execution thất bại, action trở thành `execution_failed`, được đưa trở lại `approvals_required`, và không được retry cho đến khi owner approve lại.

## Command Center backend

`GET /api/v1/command-center` trả snapshot gồm:

- task gần đây;
- agent đã được chọn;
- tổng action;
- số approval đang chờ;
- số action đã execute;
- số action execution failed;
- recent audit events;
- storage backend hiện tại.

Các endpoint chi tiết:

```text
GET /api/v1/agent-tasks/{task_id}/executions
GET /api/v1/agent-tasks/{task_id}/audit
```

Đây là backend contract để UI owner dashboard có thể được dựng mà không cần đọc trực tiếp Redis.

## EspoCRM schema discovery

Phase 3 thêm read-only endpoint:

```text
GET /api/v1/integrations/espocrm/schema/Lead
```

Adapter gọi EspoCRM Metadata endpoint với key `entityDefs.{EntityType}` và `X-Api-Key` của API User read-only. Kết quả được thu gọn thành field-level schema gồm:

- field name;
- type;
- required;
- read-only;
- not-storable;
- enum options (nếu có).

Mục đích là đọc custom fields của chính EspoCRM instance NPD trước khi map Sales/CRM agents. Endpoint này không đọc record khách hàng và không ghi dữ liệu CRM.

## Video Producer -> Video API

`video.jobs.create` tái sử dụng contract `VideoJobCreate` hiện hữu của `POST /api/v1/video-jobs`. Caller phải truyền `context.video_job` hợp lệ. Mỗi request dùng:

```text
Idempotency-Key = agent-{task_id}-{action_id}
```

## EspoCRM read-only records

Sales và CRM Manager có thể đọc entity `Lead` khi cấu hình:

```text
ESPOCRM_URL=https://crm.example.com
ESPOCRM_API_KEY=<read-only-api-user-key>
```

Khuyến nghị tạo API User riêng chỉ có quyền đọc các entity/field cần thiết. Agent Hub hiện không POST/PUT/DELETE trực tiếp tới EspoCRM.

`crm.audit.read` tính các tín hiệu cơ bản trên batch Lead:

- thiếu cả email và số điện thoại;
- chưa assigned user;
- stale theo `modifiedAt` và `context.crm_stale_days`.

## n8n approved-action executor

Workflow mẫu:

`workflows/n8n/agent-hub-approved-action-executor.json`

Workflow được commit ở trạng thái `active=false`. Nó nhận POST envelope từ Agent Hub, xác nhận action có `status=approved`, kiểm tra tool thuộc allowlist và trả dry-run acceptance.

```text
N8N_AGENT_EXECUTOR_WEBHOOK_URL=https://n8n.example.com/webhook/npd-agent-executor
```

Chưa có credential hoặc production node cho Ads, social publisher, customer messaging và CRM write.

## Approval policy

Các action đọc dữ liệu, research, phân tích và tạo draft có thể đi đến bước chuẩn bị. Các action sau mặc định cần approval:

- thay đổi ngân sách quảng cáo;
- publish nội dung công khai;
- gửi liên hệ cho khách hàng;
- ghi/sửa dữ liệu CRM.

Commander kiểm tra approval trước execution. n8n executor kiểm tra approval và allowlist lần hai.

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
```

Secret không commit vào repo.

## Kiến trúc Phase 3

```text
User / future Dashboard / n8n
        |
        v
    Commander
        |
   +----+-----------------------------+
   |       |        |       |         |
Marketing Content  Video   Social    Sales <-> CRM
                  |                   |
                  v                   v
              Video API          EspoCRM GET
                  |                   |
                Worker          Metadata schema
                  |
               Renderer

Commander state / approvals / executions / audit
        |
        v
   Redis DB 1

Approved write actions
        |
        v
 n8n executor webhook
        |
   inactive dry-run
```

## Guardrails

- Principle of least privilege cho từng adapter.
- Read và write credentials tách riêng.
- EspoCRM record adapter và schema discovery đều read-only.
- Write tools chỉ đi qua configured n8n webhook, không nhận arbitrary URL từ payload.
- Commander không bypass approval policy.
- Write failure bắt buộc re-approval trước retry.
- Audit log không lưu secret hoặc full CRM payload.
- Redis namespace tách khỏi video job store.
- Workflow n8n write executor mặc định inactive và dry-run.

## Còn lại sau Phase 3

1. Owner-auth/RBAC cho Command Center trước khi expose ra Internet.
2. UI Command Center để xem task, audit, approve/reject và execute approved actions.
3. Dùng schema discovery trên EspoCRM NPD thật để map Lead/Contact/Opportunity custom fields.
4. Read adapters cho analytics, website, ads metrics và social metrics.
5. LLM provider cho reasoning/brief generation với deterministic fallback cho test.
6. Mapping từng approved write tool sang workflow n8n production sau khi credential và acceptance test đầy đủ.
