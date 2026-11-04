# RUNBOOK — Yelp Account Factory

## 0. Thành phần trên máy này

| Thành phần | Đường dẫn / cổng |
|---|---|
| GPM Login Global | `%APPDATA%\GPMLoginGlobal`, API `http://127.0.0.1:9495`, MCP `/mcp` |
| Postgres 16 (portable) | `data/pg/pgsql`, data dir `data/pgdata`, cổng **5433** |
| Python 3.12 venv | `.venv` |
| Artifacts | `artifacts/` (ảnh, DOM, HAR của bước lỗi) |

## 1. Khởi động

```powershell
# Postgres
.\data\pg\pgsql\bin\pg_ctl.exe -D data\pgdata -o "-p 5433 -c listen_addresses=127.0.0.1" -l data\pg.log start

# Schema
.\.venv\Scripts\yf.exe db-init

# Kiểm tra GPM + MCP
.\.venv\Scripts\yf.exe gpm-health
.\.venv\Scripts\yf.exe gpm-list
```

GPM app phải đang chạy (nếu tắt: `.\.venv\Scripts\yf.exe gpm-health` sẽ trả `gpm_down`;
`adapters.gpm_http.restart_gpm_app()` chỉ dùng khi có `GPMLoginGlobal.exe` trong data dir).

## 2. Chạy đăng ký

```powershell
# 1 tài khoản, in ra danh sách account id (không mở browser)
.\.venv\Scripts\yf.exe signup --count 1 --city "Austin, TX" --dry-run

# Chạy thật
.\.venv\Scripts\yf.exe signup --count 5 --city "Austin, TX" --concurrency 2
```

Kết quả cuối nằm trong `accounts.state`; tài khoản hỏng vào `QUARANTINED` kèm `quarantine_reason`.

## 3. Kiểm tra sức khoẻ

```powershell
.\.venv\Scripts\yf.exe report --since 24h
.\.venv\Scripts\yf.exe quarantine --limit 20
.\.venv\Scripts\yf.exe proxy-probe            # dùng proxy trong .env
.\.venv\Scripts\yf.exe mail-probe             # gửi probe tới alias ngẫu nhiên
.\.venv\Scripts\yf.exe serve                  # admin API 127.0.0.1:8787 + bearer token
.\.venv\Scripts\yf.exe reap                   # lock chết, run treo, profile mồ côi, artifact cũ
```

## 4. Quarantine

```sql
SELECT a.id, a.state, a.quarantine_reason, q.code, q.evidence, q.created_at
FROM accounts a JOIN quarantine q ON q.account_id = a.id
ORDER BY q.created_at DESC LIMIT 20;
```

Xử lý theo `code`:

| code | Việc cần làm |
|---|---|
| `gpm_down` | mở lại GPM app, chạy `yf gpm-health`, rồi reset account về `NEW` |
| `proxy_dead` / `proxy_slow` / `geo_mismatch` | kiểm tra `yf proxy-probe`, đổi proxy trong `.env` |
| `ip_blocked` | đổi proxy cùng country, xoá cookie profile GPM |
| `no_email` | kiểm tra mailbox (xem mục 6), chạy `yf mail-probe` |
| `captcha` | kiểm tra balance Capsolver (`getBalance`), tăng `captcha.timeout_s` |
| `form_drift` / `dom_drift` | cập nhật `src/selector_registry/registry.yaml`, chạy lại test E-30/E-42 |
| `api_drift` | GPM đổi schema → so `adapters/gpm_http.py` với `docs/DEVIATIONS.md` |

Reset account (chỉ sau khi đã sửa nguyên nhân):

```sql
UPDATE accounts SET state='NEW', substate=NULL, quarantine_reason=NULL, retry_count=retry_count+1
WHERE id = '<uuid>';
DELETE FROM quarantine WHERE account_id = '<uuid>';
```

## 5. Crash / resume

* Mỗi state ghi `steps` + `checkpoints`; resume luôn bắt đầu từ state kế tiếp đã hoàn thành.
* `yf reap` đưa run treo (>30 phút) về `FAILED` và xoá lock hết TTL.
* Không bao giờ chạy lại bước có side effect (`SUBMITTED`, gửi SMS) nếu `steps.status='DONE'`.

## 6. Mailbox

Mailbox hiện tại: `GodwinSarinana242@hotmail.com` (Graph refresh token trong `.env`).
Alias gửi đi: `<random>@fviainboxes.com` (MX `mail.fviadropinbox.com`).

> **Sự cố đang mở (D-10):** cả hai mailbox được cấp đều bị Microsoft khoá
> (`ErrorAccountSuspend` → `AADSTS70000: User account is found to be in service abuse mode`).
> Graph đọc mail hoạt động lúc đầu, sau đó token refresh bị từ chối hoàn toàn.
> Cần mailbox khác (hoặc mở khoá tài khoản) trước khi verify email chạy được.

> **Sự cố đang mở (D-09):** Yelp yêu cầu xác minh SĐT sau submit. Cần key SMS provider
> (`YF_SMS__API_KEY`, hiện adapter đọc `sms-activate` API) trước khi tài khoản lên ACTIVE.

Refresh token Microsoft sẽ rotate sau mỗi lần refresh; `GraphMailbox(on_token_refresh=...)`
được thiết kế để ghi lại token mới, hiện CLI chưa persist — cập nhật `.env` thủ công khi token hết hạn.

## 6.1 Trạng thái chạy thật (2026-11-04)

Đã chạy `yf signup --count 1` trên hạ tầng thật, kết quả từng bước:

| Bước | Kết quả |
|---|---|
| PROVISIONING → BROWSER_UP | ✅ profile tạo qua MCP, CDP attach OK, proxy US mobile |
| PREWARMED → FORM_FILLED | ✅ điền form thật (first/last/email/password/zip) |
| CAPTCHA_SOLVED | ✅ không có captcha ở lượt này |
| SUBMITTED | ✅ Yelp nhận form, trả interstitial yêu cầu phone |
| PHONE_PENDING | ⛔ quarantine `sms_fail` (chưa có SMS provider) |
| EMAIL_* | ⛔ không chạy được vì mailbox bị khoá |

Fingerprint kiểm chứng trong browser: `navigator.webdriver=false`, `tz=America/New_York`,
`screen=1280x800`, UA Chrome 153, `plugins=5`.

## 7. Soak / load

```powershell
# 500 job (dry-run tạo account rồi chạy tuần tự theo concurrency)
.\.venv\Scripts\yf.exe signup --count 500 --concurrency 8
# theo dõi
.\.venv\Scripts\yf.exe report --since 1h
```

## 7.1 Warming scheduler

```powershell
# Một lượt: tạo plan cho mọi account ACTIVE/WARMING rồi chạy các session tới hạn
.\.venv\Scripts\yf.exe schedule --once --limit 8 --minutes 8

# Chạy nền, mỗi 5 phút quét lại (giờ địa phương của từng city, 06:00-23:00)
.\.venv\Scripts\yf.exe schedule --interval 300 --minutes 8
```

Quy tắc: mỗi account tối đa 1–3 session/ngày (`MAX_SESSIONS_PER_DAY`), mỗi session 4–12 phút,
plan lưu ở `warming_plans`/`warming_tasks` nên restart không mất lịch. 5% session là "empty"
(chỉ mở trang) theo spec 9.

Chạy tay một account:

```powershell
.\.venv\Scripts\yf.exe warm --account <uuid> --sessions 2 --minutes 6
```

## 8. Test

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m pytest tests/cases -q     # 1 file / edge case
```
