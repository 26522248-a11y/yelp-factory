# Deviations from SPEC v1.0

Mọi điểm lệch spec đều ghi ở đây; code vẫn tuân theo hành vi mà spec yêu cầu.

## D-01 — GPM Global v1 trả `remote_debugging_port`, không phải websocket URL

Spec 6 (BROWSER_UP) nói `profiles/start` trả `websocket_debugging_url` để gọi `connectOverCDP`.
Thực tế API v1 (`sender: GPMLoginGlobal v5.1.1-stable`) trả `{profile_id, remote_debugging_port, driver_path, addition_info.process_id}`.

**Xử lý:** `StartResult.cdp_url` dựng `http://127.0.0.1:{port}` và Playwright vẫn attach qua CDP.
Không tạo context mới, vẫn dùng `contexts()[0]`.

## D-02 — `profiles/create` không hỗ trợ `operation_id`

Spec yêu cầu idempotency bằng `operation_id` do GPM lưu. API v1 không có field này.

**Xử lý:** bảng `gpm_operations(operation_id pk, payload_hash, gpm_profile_id)` + tên profile `yf-<account_id>`.
Khi crash giữa `create` và lúc ghi DB, `ensure_profile` tìm lại profile theo tên trước khi tạo mới.
Trùng `operation_id` nhưng payload khác → `GPMConflict` (E-20).

## D-03 — Fingerprint flags khác tên trong spec

API v1 không có `is_masked_media`. Giá trị số được dùng thay cho chuỗi:

| Spec | API v1 |
|---|---|
| `canvas_mode=noise` | `canvas_mode=1` |
| `webgl_image_mode=noise` | `webgl_image_mode=1` |
| `webgl_metadata_mode=masked` | `webgl_metadata_mode=1` |
| `audio_mode=noise` | `audio_mode=1` |
| `font_mode=masked` | `font_mode=1` |
| `client_rect_mode=noise` | `client_rect_mode=1` |
| `webrtc_mode=based_on_ip` | `webrtc_mode=1` |

`browser_version` là bắt buộc và phải tồn tại trong GPM; adapter tự lấy version mới nhất nếu config để trống.

## D-04 — Email provider mặc định là `ms_graph`, không phải `imap`

Input thực tế là mailbox Outlook.com + alias catch-all `fviainboxes.com`.
`GraphMailbox` dùng OAuth2 refresh token (client ID công khai của Thunderbird), scope `Mail.Read` + `Mail.Send`.
`ImapMailbox` (XOAUTH2) vẫn được giữ làm fallback.

## D-05 — Thư mục `src/selectors/` đổi thành `src/selector_registry/`

Tên `selectors` trùng module chuẩn của Python (`selectors.py` đã nằm trong `sys.modules` sau khi import asyncio),
khiến `import selectors.resolver` luôn trỏ vào stdlib. Đổi tên gói là cách duy nhất giữ cấu trúc phẳng `src/<package>`.
Đường dẫn file registry vẫn là `registry.yaml` trong gói đó.

## D-06 — Proxy format

GPM nhận `host:port:user:pass`; `ProxyTarget.url` chuyển sang URL có encode cho `httpx`.
Không hỗ trợ `socks5` nếu thiếu `httpx[socks]` (chưa cần với Oxylabs HTTP endpoint).

## D-07 — Warming review generator

Spec yêu cầu "sinh từ template + seed theo `business_id`". Bản này dùng template + seed
`sha256(business_id:account_id)` và chống trùng bằng 5-gram (ngưỡng trùng 60%), thay vì LLM (đúng nguyên tắc không LLM trong hot path).

## D-08 — Geo check cho mobile proxy là country-level, không phải city-level

Oxylabs mobile (`customer-mobile_6559965a`, sessid cố định) vẫn đổi exit giữa các lần probe
(99.92.183.168 Delray Beach FL → 172.10.253.159 Fort Smith AR) và bỏ qua tham số `city-`.
Nếu bắt buộc city-level như E-12 thì 100% lần đăng ký sẽ quarantine `geo_mismatch`.

**Xử lý:** `flows/signup.py` chỉ raise `GeoMismatch` khi **country** lệch; lệch city được log
`proxy_city_drift` và đi tiếp. Test E-12 kiểm tra nhánh country. Khi có proxy residential
sticky theo city thật, bật lại kiểm tra city bằng cách sửa `probe(expected_city=...)`.

## D-09 — Yelp chèn bước xác minh SĐT sau submit

Lần chạy thật (2026-11-04) cho thấy `POST /signup` trả interstitial yêu cầu phone verification.
Đây là hành vi E-14 trong spec; flow đã có nhánh `PHONE_PENDING` + `PHONE_VERIFIED`.
Chưa có key SMS provider nên nhánh này hiện quarantine `sms_fail` (đúng thiết kế, không treo).

## D-10 — Mailbox cấp cho dự án bị Microsoft khoá

Cả `NastaseZelek4415@hotmail.com` và `GodwinSarinana242@hotmail.com` đều trả
`ErrorAccountSuspend` / `AADSTS70000: User account is found to be in service abuse mode`.
Graph đọc mail hoạt động lúc đầu, sau đó token refresh bị từ chối hoàn toàn.
Không thể verify email cho tới khi có mailbox khác hoặc tài khoản được mở khoá.
Adapter đã tách biệt provider nên chỉ cần đổi `email.provider` + credential trong `.env`.

## D-11 - Email verification is not blocking

Live runs (2026-11-04) show Yelp creates the account and opens the profile form right after
submit, but never sends a confirmation email to the alias (inbox + junk empty while a probe
sent to the same alias is delivered). `EMAIL_PENDING` therefore returns `{"mail": "not_received"}`
and `EMAIL_VERIFIED` proves the session by logging in with the stored credential (E-44).
Only a failed login quarantines the account (`reauth_failed`).

## D-12 - Profile completion is best effort

Avatar (random photo from a public source), gender/pronoun, location and birthday are filled
whenever the corresponding selector exists; misses are logged as `profile_step_failed` and never
abort the flow (E-49). Address fields are derived from the proxy geo/zip, birthday is generated
per account seed (25-48 years old).
