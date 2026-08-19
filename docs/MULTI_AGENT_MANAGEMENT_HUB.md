# NPD Multi-Agent Management Hub

## Mục tiêu

Agent Hub là lớp điều phối phía trên NPD AI Video Factory. Nó nhận mục tiêu kinh doanh/công việc, chọn agent chuyên môn, tạo kế hoạch hành động, gom báo cáo cho Commander và chặn các hành động có tác động bên ngoài bằng approval gate.

Sprint này chỉ tạo control plane. Không tự publish, không tự chi tiền quảng cáo, không tự liên hệ khách hàng và không tự sửa CRM.

## 7 agent

1. `commander` — định tuyến công việc, tổng hợp ưu tiên, kiểm soát approval.
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

Ví dụ task:

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

## Approval policy

Các action đọc dữ liệu, research, phân tích và tạo draft có thể đi thẳng tới bước chuẩn bị. Các action sau mặc định cần approval:

- thay đổi ngân sách quảng cáo;
- publish nội dung công khai;
- gửi liên hệ cho khách hàng;
- ghi/sửa dữ liệu CRM.

Approval hiện chỉ thay đổi trạng thái action. Tool adapter thực thi thật sẽ được thêm ở sprint kế tiếp để giữ ranh giới quyền rõ ràng.

## Kiến trúc đích

```text
User / Dashboard / n8n
        |
        v
    Commander
        |
   +----+-----------------------------+
   |       |        |       |         |
Marketing Content  Video   Social    Sales <-> CRM
   |       |        |       |         |
Analytics Research VideoAPI Publishers EspoCRM
                    |
                  Worker
                    |
                 Renderer
```

## Thứ tự tích hợp tiếp theo

1. Kết nối `video.jobs.create` với FastAPI video job hiện tại.
2. Kết nối EspoCRM read-only cho Sales/CRM agents.
3. Kết nối n8n làm tool executor cho approved actions.
4. Thêm LLM provider cho reasoning/brief generation, giữ deterministic fallback cho test.
5. Thêm persistence/audit log cho agent task và approval.
6. Sau khi đủ bằng chứng vận hành mới cân nhắc social publisher và ads write adapters.

## Guardrails

- Principle of least privilege cho từng tool adapter.
- Read và write credentials tách riêng.
- Mọi write action phải có audit trail.
- Không lưu secret trong repo.
- Không cho Commander bypass approval policy.
- Không merge chung với PR renderer đang nghiệm thu nếu chưa review độc lập.
