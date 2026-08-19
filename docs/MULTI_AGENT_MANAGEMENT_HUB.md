# NPD Multi-Agent Management Hub

## Mục tiêu

Agent Hub là lớp điều phối phía trên NPD AI Video Factory. Nó nhận mục tiêu kinh doanh/công việc, chọn agent chuyên môn, tạo kế hoạch hành động, gom báo cáo cho Commander và chặn các hành động có tác động bên ngoài bằng approval gate.

Phase 1 tạo control plane. Phase 2 bổ sung tool execution có kiểm soát cho Video API, EspoCRM read-only và n8n approved-action executor.

## 7 agent

1. `commander` — định tuyến công việc, tổng hợp ưu tiên, kiểm soát approval và tool execution.
2. `marketing_leader` — kế hoạch marketing, funnel, KPI, đề xuất ngân sách.
3. `content_trend` — research trend, idea scoring, hook và content brief.
4. `video_producer` — production brief, script/storyboard handoff và video job.
5. `social_media` — đóng gói nội dung đa nền tảng, lịch và publishing preparation.
6. `sales` — lead scoring, sales brief, follow-up và next-best-action.
7. `crm_manager` — data hygiene, duplicate/stale lead detection và pipeline audit.

## API

- `GET /health`
- `GET /api/v1/agents`
- `POST /api/v1/agent-tasks`
- `GET /api/v1/agent-tasks/{task_id}`
- `POST /api/v1/agent-tasks/{task_id}/actions/{action_id}/decision`
- `POST /api/v1/agent-tasks/{task_id}/actions/{action_id}/execute`

Ví dụ task tổng quát:

```json
{
  "objective": "Quản lý công việc toàn bộ hệ thống marketing, video, sales và CRM",
  "context": {
    "period": "this_week"
  },
  "constraints": [
    "Không tự publish",
    "Không thay đổi ngân sách nếu chưa duyệt"
  ]
}
```

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

Các tool planning-only như `analytics.read`, `research.search`, `content.idea_score`, `video.brief.create` và `social.package.create` chưa có adapter thực thi trong Phase 2.

## Video Producer -> Video API

`video.jobs.create` tái sử dụng nguyên contract `VideoJobCreate` hiện hữu của `POST /api/v1/video-jobs`. Agent Hub không tự đoán project hoặc media folder khi thực thi thật; caller phải truyền `context.video_job` hợp lệ.

Ví dụ:

```json
{
  "objective": "Tạo video giới thiệu dự án",
  "preferred_agents": ["video_producer"],
  "context": {
    "video_job": {
      "topic": "3 điểm đáng chú ý của dự án",
      "project": "vinhomes-green-paradise",
      "video": {
        "duration_seconds": 30,
        "aspect": "9:16",
        "language": "vi",
        "template": "real-estate-short-v1"
      },
      "content": {
        "objective": "awareness",
        "audience": "khách hàng quan tâm bất động sản",
        "tone": "thông tin, rõ ràng",
        "cta": "Tìm hiểu thêm"
      },
      "media": {
        "source": "local",
        "project_asset_folder": "vinhomes-green-paradise",
        "minimum_clips": 5,
        "allow_stock": false,
        "allow_ai_generation": false
      }
    }
  }
}
```

Mỗi request dùng `Idempotency-Key = agent-{task_id}-{action_id}` để tránh tạo job lặp khi retry.

## EspoCRM read-only

Sales và CRM Manager có thể đọc entity `Lead` qua EspoCRM REST API khi cấu hình:

```text
ESPOCRM_URL=https://crm.example.com
ESPOCRM_API_KEY=<read-only-api-user-key>
```

Khuyến nghị tạo API User riêng chỉ có quyền đọc các entity/field cần thiết. Agent Hub Phase 2 không có code POST/PUT/DELETE trực tiếp tới EspoCRM.

`crm.audit.read` hiện tính các tín hiệu cơ bản trên batch Lead đã đọc:

- thiếu cả email và số điện thoại;
- chưa assigned user;
- record stale theo `modifiedAt` và `context.crm_stale_days`.

## n8n approved-action executor

Workflow mẫu:

`workflows/n8n/agent-hub-approved-action-executor.json`

Workflow được commit ở trạng thái `active=false`. Nó nhận POST envelope từ Agent Hub, xác nhận action có `status=approved`, kiểm tra tool thuộc allowlist và trả về dry-run acceptance.

Biến môi trường:

```text
N8N_AGENT_EXECUTOR_WEBHOOK_URL=https://n8n.example.com/webhook/npd-agent-executor
```

Phase 2 chưa nối credential hoặc node production cho Ads, social publisher, customer messaging và CRM write. Chỉ sau khi mapping từng tool được review mới thay dry-run branch bằng action thật.

## Approval policy

Các action đọc dữ liệu, research, phân tích và tạo draft có thể đi thẳng tới bước chuẩn bị. Các action sau mặc định cần approval:

- thay đổi ngân sách quảng cáo;
- publish nội dung công khai;
- gửi liên hệ cho khách hàng;
- ghi/sửa dữ liệu CRM.

Commander chặn `/execute` nếu action write chưa approved. Executor n8n kiểm tra approval lần hai; đây là defense-in-depth chứ không chỉ dựa vào UI.

## Environment

```text
VIDEO_API_URL=http://api:8000
AGENT_TOOL_TIMEOUT_SECONDS=30
ESPOCRM_URL=
ESPOCRM_API_KEY=
N8N_AGENT_EXECUTOR_WEBHOOK_URL=
```

Secret không commit vào repo.

## Kiến trúc hiện tại

```text
User / Dashboard / n8n
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
                  |
                Worker
                  |
               Renderer

Approved write actions
        |
        v
 n8n executor webhook
        |
   Phase 2 dry-run
```

## Guardrails

- Principle of least privilege cho từng tool adapter.
- Read và write credentials tách riêng.
- EspoCRM adapter Phase 2 chỉ dùng GET.
- Write tools chỉ đi qua một configured n8n webhook, không nhận arbitrary URL từ payload.
- Commander không được bypass approval policy.
- n8n executor kiểm tra approval và allowlist lần hai.
- Không lưu secret trong repo.
- Workflow n8n write executor mặc định inactive và dry-run.

## Còn lại sau Phase 2

1. Redis/Postgres persistence cho agent task, action, execution history và audit log.
2. EspoCRM schema discovery/OpenAPI để map custom fields của hệ thống NPD.
3. Read adapters cho analytics, website, ads metrics và social metrics.
4. LLM provider cho reasoning/brief generation với deterministic fallback cho test.
5. Mapping từng approved write tool sang workflow n8n production sau khi credential và acceptance test đầy đủ.
6. Dashboard/Command Center cho owner review, approve và theo dõi agent execution.
