# Biên bản bàn giao và roadmap Agent Hub

Ngày chốt: 11/09/2026 20:16 ICT  
Repository: `vangnguyen/npd-ai-video-factory`  
Remote `main` đã đối chiếu: `43a1cca354d12893ee33b6e43cd9117794f78e04`

## 1. Kết luận điều hành

Agent Hub đã hoàn thành phần lớn nền tảng source, reliability, attribution và
Phase 9 Journey/Lead Score/NBA theo chế độ recommendation-only. Chuỗi clean-port
và Phase 9 source đã được merge; CI của các PR trọng yếu đều xanh.

Điểm chưa hoàn thành là **production acceptance**. Limited Phase 9 Pilot Fresh
V2 ngày 11/09/2026 đã dừng fail-closed ở remote read-only preflight, trước claim,
staging và mutation. Vì vậy:

- Phase 9 chưa được nghiệm thu sử dụng nội bộ;
- không có deployment mới;
- không có UAT production;
- operation cũ là terminal và không được reuse;
- Phase 10, AH-R01 chưa được cấp quyền;
- AH-03 và AH-04 vẫn NO-GO.

## 2. Các hạng mục đã triển khai

| Nhóm | Trạng thái | Bằng chứng chính |
| --- | --- | --- |
| Nền tảng Agent Hub Phase 1-8.9 | Source/release foundation đã triển khai theo handoff lịch sử | Agent Hub 0.13.0 là release ổn định lịch sử; các capability external vẫn disabled |
| AH-01/AH-01B/AH-01C | Audit/readiness source hoàn tất; shutdown vẫn NO-GO | 46 components, `UNKNOWN=0`, publication/storage/runtime/backup evidence và kế hoạch shutdown |
| AH-02 boundary | Contract/mock boundary Agent Hub ↔ Video Factory đã có | DTO, auth/webhook/idempotency và integration tests; không tự cấp production integration |
| Clean-port delivery router | MERGED qua PR #63 | Merge `6e3a0f5e9a959884ba06abf7e2a412364b7b3df0` |
| Clean-port HubStore protocol | MERGED qua PR #64 | Merge `3c8f2573056ef04c815f3138f1610bcfd48016e4` |
| Dashboard shell extraction | MERGED qua PR #66 | Merge `e2a80f46d5f991cde405fd77e4b79b7a1385a6cc` |
| VND-only business currency | MERGED qua PR #65 | Merge `e04413a4ac314927c87ad0b480b9e4034874e628`; non-VND fail-closed |
| Phase 9 marketing review | MERGED qua PR #62 | Merge `78d85647b4fd3e7d6e4fdae49925f205c459a22d`; evidence-backed Commander workflow |
| Phase 9 browser preset/UAT surface | MERGED qua PR #67 | Merge/main `43a1cca354d12893ee33b6e43cd9117794f78e04` |
| Phase 9 package preparation | PASS ngoài production | Fresh backup 10,692/10,692, isolated restore/RBAC rehearsal PASS, package tests 31/31 |
| Owner gate materialization | PASS | Approval/token/package bindings verified without exposing plaintext token |
| Fresh V2 execution attempt | TERMINAL ABORT | Dispatcher start `20:00:19 ICT`; `REMOTE_PREFLIGHT_FAILED_e3b0c44298fc1c14`; zero claim/stage/mutation |
| Handoff governance | PASS trên nhánh docs | Root `HANDOFF.md`, `handoff.json`, receipt protocol và tài liệu này |

## 3. Hạng mục chưa hoàn thành và blocker

### P0 — Khôi phục đường production pilot

1. RCA read-only cho `REMOTE_PREFLIGHT_FAILED_e3b0c44298fc1c14`.
2. Xác định remote command thực sự chạy hay transport kết thúc non-zero trước
   khi runtime trả JSON; evidence hiện chỉ biết stderr rỗng.
3. Sửa tối thiểu source/package ở candidate mới nếu RCA chứng minh cần sửa.
4. Chạy lại non-production regression và strict-SSH handshake.
5. Tạo fresh operation/token/package/window/Owner Gate; tuyệt đối không reuse
   operation ngày 11/09.
6. Chạy one-subject pilot và authenticated browser UAT cho Owner/Operator/Viewer.

### P1 — Đóng Phase 9 business acceptance

- Xác minh Sales Hub completeness/SLA evidence thật. Hiện pilot chỉ được phép
  ghi `NOT_AVAILABLE`/`NOT_EVALUABLE`, không được suy diễn `BREACHED`.
- Đánh giá Journey, Lead Score và NBA v2 trên cohort pseudonymous được duyệt.
- Xác minh đúng một review, persistence/history, desktop và mobile 390×844.
- Xác nhận external action count bằng 0 và không có service ngoài Agent Hub bị
  mutate.
- Owner chốt internal-use acceptance; limited pilot PASS không tự động là full
  Phase 9 acceptance.

### P1 — Recovery/custody

- Tạo protected backup Copy 2 trên storage độc lập.
- Xác minh checksum và restore path.
- Thiết lập portable recovery custody tách khỏi DPAPI CurrentUser và backup
  payload.
- Giữ retention ít nhất 90 ngày sau final V1 disable, kéo dài nếu còn blocker.

### P1 — AH-T01B legacy telemetry

- Production deployment API + Renderer chưa PASS; 14-day observation vẫn
  `NOT_STARTED`.
- Cần fresh gate, successful telemetry-only deployment, identity-safe log/counter
  verification và đủ 14 ngày không gap/unexplained caller.
- Worker, Agent Hub, Redis, Caddy, ports, networks và business data phải bất biến.

### P1 — AH-R01 Redis independence

- M1: provision target Redis rỗng riêng cho Agent Hub.
- M2: encrypted DB1 export và isolated restore/rehearsal/parity.
- M3: writer-quiesced cutover, chỉ đổi Agent Hub Redis binding, verification và
  rollback window.
- Không được stop V1 Redis như shortcut; mỗi mốc cần owner gate riêng.

### P2 — V1 deprecation/retirement

- Chỉ lập fresh pre-AH-03 snapshot sau khi telemetry, Redis independence,
  backup/custody và publication actions hoàn tất.
- AH-03 mới được đề xuất để block new V1 jobs, bật deprecation telemetry và
  compatibility bridge; chưa xóa V1.
- Port/Caddy/traffic switch/storage deletion/V1 shutdown cần các stage và owner
  gates riêng. Hiện `V1 DECOMMISSION = NO-GO`.

## 4. Roadmap theo thứ tự an toàn

| Stage | Mục tiêu | Điều kiện đầu vào | Điểm dừng/gate |
| --- | --- | --- | --- |
| A0 | RCA remote preflight failure | Terminal abort evidence bất biến | Báo RCA; không tạo retry gate |
| A1 | Candidate retry readiness | RCA closed, local regression và transport proof PASS | Owner review source/package |
| A2 | Fresh limited pilot | Fresh snapshot, operation, token, window và Owner Gate | Dừng với PASS/PARTIAL/FAILED/ROLLED_BACK/ABORTED |
| A3 | Phase 9 closure | Pilot evidence + Sales SLA path + Copy 2/custody | Owner Phase 9 internal-use acceptance |
| I1 | AH-T01B telemetry deployment | Fresh telemetry action gate | Start 14-day clock chỉ từ receipt PASS |
| I2 | AH-R01 M1→M2→M3 | Ba gate riêng, backup/restore/parity | Agent Hub Redis independence PASS |
| I3 | Pre-AH-03 readiness | 14-day PASS, no unexplained caller, independent Redis, custody PASS | Fresh snapshot + new Owner Gate |
| I4 | AH-03 deprecation | I3 accepted | Compatibility/deprecation only; no deletion |
| P10 | Controlled channel execution | Phase 9 accepted và capability-specific design | Owner gate từng channel; không mở hàng loạt |
| P11 | Creative/CRO optimization | Controlled channels proven | Experiment/rollback gates |
| P12 | Revenue control tower | Data lineage và cost governance accepted | Executive acceptance |

Các nhánh A (product acceptance) và I (legacy infrastructure) có thể chuẩn bị
song song bằng source/offline evidence, nhưng production action của mỗi nhánh
vẫn cần gate độc lập.

## 5. Trạng thái không được suy diễn

- Source merged không đồng nghĩa production deployed.
- Fixture/CI PASS không đồng nghĩa browser UAT hoặc business acceptance PASS.
- `UNKNOWN=0` không đồng nghĩa V1 có thể shutdown.
- Limited pilot PASS, nếu có trong tương lai, không mở Phase 10.
- Không dùng phần trăm hoàn thành dựa trên số PR/test; mỗi acceptance axis phải
  có evidence riêng.

## 6. Next safe action

Chờ owner giao task **read-only RCA** cho remote preflight failure. Không tự
retry operation, không tạo package/window/approval mới và không truy cập
production từ tài liệu này.
