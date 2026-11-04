# Yelp Factory — Hướng dẫn sử dụng A–Z

Hướng dẫn này dành cho người vận hành: cài đặt, cấu hình, import dữ liệu, tạo tài khoản,
nuôi tài khoản và xử lý sự cố. Không cần biết code.

---

## 1. Giới thiệu

Yelp Factory tự động hoá vòng đời tài khoản Yelp trên browser thật qua GPM Login:

- Tạo tài khoản (email sinh tự động hoặc import sẵn)
- Hoàn thiện profile (avatar, tên, ngày sinh, địa chỉ theo IP)
- Nuôi tài khoản 30 ngày theo Trust Score (P0–P4)
- Viết review theo policy chống trùng/filter
- Theo dõi, quarantine, báo cáo, export Google Sheet

Có 2 cách dùng: **menu desktop** (khuyến nghị) hoặc **CLI**.

---

## 2. Yêu cầu hệ thống

| Thành phần | Yêu cầu |
|---|---|
| OS | Windows 10/11 (chính), macOS/Linux cho CLI/admin |
| Python | 3.12 |
| RAM | ≥ 8 GB (mỗi profile ~0.5–1 GB) |
| Disk | ≥ 10 GB |
| GPM Login | Đã cài, license còn hạn |
| Postgres | 16 (bản portable trong `data/pg` hoặc Docker) |
| Proxy | Residential/mobile US, sticky ≥ 30 phút |
| Mailbox | Outlook/Hotmail + alias catch-all (Graph refresh token) |
| Captcha | Capsolver hoặc 2captcha (nếu cần) |

---

## 3. Cài đặt từ đầu

```powershell
# 1. Clone
git clone <repo-url> yelp-factory
cd yelp-factory

# 2. Python env
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"

# 3. Tạo file cấu hình
copy .env.example .env
notepad .env          # điền secret (xem mục 5)

# 4. Database (nếu dùng Postgres portable có sẵn)
.\data\pg\pgsql\bin\pg_ctl.exe -D data\pgdata -o "-p 5433 -c listen_addresses=127.0.0.1" -l data\pg.log start

# 5. Khởi tạo schema
.\.venv\Scripts\yf.exe db-init

# 6. Kiểm tra
.\.venv\Scripts\yf.exe gpm-health
.\.venv\Scripts\yf.exe pool
```

---

## 4. Khởi động nhanh — menu desktop

Double-click **`Yelp Factory`** trên Desktop. Menu:

| Mục | Chức năng |
|---|---|
| 1 | Xem tình trạng tài khoản + kho dữ liệu |
| 2 | Tạo tài khoản mới (tự lấy city theo IP proxy) |
| 3 | Chạy phiên nuôi tài khoản |
| 4 | Import email/proxy từ file |
| 5 | Kiểm tra tài khoản + upload avatar |
| 6 | Mở admin API (cổng 8787) |
| 7 | Xem lỗi gần đây |
| 0 | Thoát |

Nếu chưa có icon, tạo lại shortcut trỏ tới `scripts\yf_launcher.ps1`.

---

## 5. Cấu hình

### 5.1 `.env` (secret, không commit)

```ini
YF_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5433/yelp_factory
YF_MASTER_KEY=<base64 32 byte>          # mã hoá password/token
YF_ADMIN_TOKEN=<token>                  # bearer cho admin API

YF_GPM__MCP_TOKEN=<token MCP GPM>
YF_GPM__LICENSE_KEY=SUB-XXXX

YF_CAPTCHA__CAPSOLVER_KEY=CAP-XXXX
YF_CAPTCHA__TWO_CAPTCHA_KEY=

YF_EMAIL__GRAPH_CLIENT_ID=9e5f94bc-...
YF_EMAIL__GRAPH_REFRESH_TOKEN=M.C524...

YF_PROXY__DEFAULT_RAW=host:port:user:pass
YF_SMS__API_KEY=hup_XXXX
```

Sinh master key:

```powershell
.\.venv\Scripts\python.exe -c "import base64;from cryptography.hazmat.primitives.ciphers.aead import AESGCM;print(base64.urlsafe_b64encode(AESGCM.generate_key(bit_length=256)).decode())"
```

### 5.2 `config.yaml` (không chứa secret)

```yaml
gpm: { flavor: global-v1, base_url: "http://127.0.0.1:9495", mcp_url: "http://127.0.0.1:9495/mcp" }
concurrency: { workers: 8, max_profiles: 8, ram_guard_pct: 85 }
target: { country: US, cities: ["Delray Beach, FL"] }
proxy: { kind: residential, sticky_minutes: 45, probe_timeout_s: 8 }
email: { provider: ms_graph, domains: ["fviainboxes.com"], poll_timeout_s: 90 }
captcha: { providers: [capsolver, 2captcha], timeout_s: 90, human_in_loop: true }
warming: { enabled: true, max_sessions_per_day: 3 }
```

Thứ tự ưu tiên: `config.yaml` → biến môi trường `YF_*` → mặc định trong code.

---

## 6. Chuẩn bị dữ liệu đầu vào

### 6.1 Proxy

Format mỗi dòng:

```
host:port:user:pass
pr.oxylabs.io:7777:customer-mobile_xxx:pass
```

Hỗ trợ `http://user:pass@host:port`. Mỗi proxy dùng tối đa **2 account**; mỗi account có
session sticky riêng 30 phút.

### 6.2 Email

Format mỗi dòng (5 trường):

```
mailbox|password|refresh_token|client_id|yelp_alias
JonhsonElders63@hotmail.com|VjJAGiuOkX|M.C524...|9e5f94bc-...|jonhsonelders63yl3@fviainboxes.com
```

- `mailbox` = email đăng nhập Hotmail (Graph/IMAP)
- `yelp_alias` = email dùng đăng ký Yelp (catch-all), trống thì tự sinh
- Trường 6, 7 tuỳ chọn: `full_name`, `zip`

### 6.3 Import

```powershell
yf import-emails  --file data\emails.txt --dry-run    # xem trước
yf import-emails  --file data\emails.txt
yf import-proxies --file data\proxies.txt --dry-run
yf import-proxies --file data\proxies.txt
yf pool --list
```

Quy tắc: dòng lỗi bị loại kèm số dòng + lý do, secret được che; email chỉ dùng 1 lần;
proxy không vượt 2 account.

---

## 7. Tạo tài khoản

### 7.1 Qua menu

Chọn **2** → nhập số lượng → chọn nguồn:

1. `auto` — sinh email mới
2. `pool_email` — dùng email đã import
3. `pool_both` — dùng cả email + proxy đã import (khuyến nghị)

Thành phố **tự lấy theo IP proxy**, không nhập tay.

### 7.2 Qua CLI

```powershell
yf signup --count 5 --source pool_both
yf signup --count 1 --dry-run --source auto     # chỉ tạo row, chưa chạy browser
yf signup --count 3 --city "Austin, TX" --concurrency 2   # ép city thủ công
```

Luồng trạng thái:

```
NEW → PROVISIONING → PROXY_BOUND → BROWSER_UP → PREWARMED
→ FORM_FILLED → CAPTCHA_SOLVED → SUBMITTED
→ ONBOARDED → EMAIL_PENDING → EMAIL_VERIFIED → ACTIVE
```

Nhánh phone chỉ chạy khi Yelp yêu cầu SMS.

---

## 8. Sau khi tạo — hoàn thiện & kiểm tra

```powershell
# Kiểm tra tài khoản tồn tại thật (dùng form signup, tránh DataDome)
yf verify-login --account <uuid> --probe

# Upload avatar đã gán
yf avatar --account <uuid>

# Xem trust score + điều kiện review
yf trust --account <uuid>
```

Kiểm tra qua menu: mục **5**.

---

## 9. Nuôi tài khoản

### 9.1 Tự động

```powershell
yf schedule --once --limit 4 --minutes 8      # một lượt
yf schedule --interval 300 --minutes 8        # chạy nền 5 phút/lượt
```

Điều kiện chạy: account ACTIVE/WARMING, trong khung 07:00–22:30 local, cách session trước
≥ 90 phút, không phải ngày nghỉ (mỗi 7 ngày), 1 account/proxy tại một thời điểm.

### 9.2 Thủ công

```powershell
yf warm --account <uuid> --sessions 2 --minutes 6
```

### 9.3 Trust Score (0–100)

| Điểm | Được làm |
|---|---|
| < 40 | chỉ xem, search, scroll |
| 40–59 | + save, xem ảnh/review |
| 60–74 | + vote, follow |
| ≥ 75 | + review (kèm age ≥ 11 ngày, ≥ 6 session/7 ngày, không filter 7 ngày) |

Thành phần: age 20 · profile 15 · consistency 15 · diversity 20 · content 20 · risk −20.

---

## 10. Review & nuôi nội dung

- 80–200 từ, 1 chi tiết trung tính, không link/giá/promo.
- Rating: P3 không 2★; P4 mix 5★ 50%, 4★ 30%, 3★ 15%, 2★ 5%.
- 40% review có ảnh; ảnh review chưa hỗ trợ upload tự động.
- Cap: P3 2 review/tuần, P4 3 review/tuần; cùng business cooldown 90 ngày.
- Review bị filter → nghỉ business đó 7 ngày, trust −8.

---

## 11. Báo cáo & export

```powershell
yf report --since 24h
yf quarantine --limit 20
yf reap                    # dọn lock, run treo, profile mồ côi, artifact cũ
```

Export Google Sheet: dùng `src/export_accounts.py` (chỉ account ACTIVE/WARMING/ONBOARDED)
rồi sync tay; API `POST /api/export/sheet` sẽ có ở bản UI.

---

## 12. Admin API

```powershell
yf serve          # http://127.0.0.1:8787
```

| Endpoint | Việc |
|---|---|
| `GET /health` | trạng thái |
| `GET /report?since=24h` | KPI |
| `GET /api/pool` | thống kê kho |
| `POST /api/pool/import` | import từ text |
| `POST /signup` | ghi nhận yêu cầu |

Tất cả (trừ `/health`, `/metrics`) cần header `Authorization: Bearer $YF_ADMIN_TOKEN`.

---

## 13. Xử lý sự cố

| Hiện tượng | Nguyên nhân | Cách xử lý |
|---|---|---|
| `gpm_down` | GPM tắt / port đổi | mở GPM, `yf gpm-health`; hệ thống tự scan 8000–10000 |
| Proxy 502 | session sticky hết hạn | hệ thống tự tạo sessid mới; kiểm tra `yf proxy-probe` |
| DataDome challenge ở `/login` | IP mobile bị gắn cờ | không retry dồn; đổi proxy/đợi, dùng `verify-login --probe` |
| `pool_exhausted` | hết email/proxy khả dụng | import thêm, kiểm tra `yf pool` |
| Mailbox `ErrorAccountSuspend` | tài khoản Microsoft bị khoá | mở khoá hoặc thay mailbox |
| `sms_fail` | Yelp đòi SĐT nhưng không có provider US | bổ sung SMS US hoặc bỏ qua (phone optional) |
| `selector_miss` / `dom_drift` | Yelp đổi DOM | cập nhật `src/selector_registry/registry.yaml`, chạy lại test E-30 |
| `review_rejected` | text trùng/không đạt policy | generator tự sinh lại; kiểm tra 5-gram |
| Trust thấp, không warm | chưa đủ ngày/session | kiểm tra `yf trust`, chạy schedule đều |
| Không thấy avatar | ONBOARDED bỏ qua upload | `yf avatar --account <uuid>` |

Log chi tiết: JSON trên console + `yf quarantine`; artifact lỗi trong `artifacts/`.

---

## 14. Checklist vận hành

**Hàng ngày**

- [ ] Menu 1: xem trạng thái, queue, lỗi
- [ ] Kiểm tra pool còn email/proxy
- [ ] Chạy `yf schedule --once` (hoặc để scheduler nền)
- [ ] Xem quarantine, xử lý lỗi mới

**Hàng tuần**

- [ ] `yf reap` dọn rác
- [ ] Kiểm tra trust tăng, review published
- [ ] Rotate proxy/mailbox nếu lỗi tăng
- [ ] Export sheet account mới

**Hàng tháng**

- [ ] Rà soát review bị filter theo business
- [ ] Cập nhật selector registry nếu DOM đổi
- [ ] Backup DB + `data/`

---

## 15. Bảo mật

- Không commit `.env`, `data/`, `artifacts/`.
- Password/token mã hoá AES-GCM (`YF_MASTER_KEY` ngoài DB).
- Admin API chỉ bind `127.0.0.1`.
- Log đã redact password/OTP/proxy credential.
- File import xoá khỏi temp sau khi xử lý.

---

## 16. Câu hỏi thường gặp

**Có cần điện thoại US không?** Không bắt buộc — Yelp để phone optional. Có SMS US thì trust +2.

**1 proxy dùng được mấy acc?** Tối đa 2, cấu hình `--max-per-proxy` / `proxy.max_accounts`.

**Tài khoản bao lâu thì review được?** Trust ≥ 75, age ≥ 11 ngày, ≥ 6 session/7 ngày.

**Chạy được trên macOS/Linux?** CLI/worker chạy được, nhưng GPM chỉ có Windows → phần browser
phải chạy trên máy Windows.

**Bao lâu phải đổi proxy?** Khi probe fail/slow liên tiếp hoặc Yelp chặn; mỗi account tự có
session riêng.

**Xem log ở đâu?** Console JSON, `yf quarantine`, `artifacts/` cho ảnh/DOM lỗi.

---

## 17. Cấu trúc thư mục

```
src/
  core/        state_machine, scheduler, trust, pool, importers, orchestrator
  adapters/    gpm_mcp, gpm_http, browser, email, captcha, sms, proxy_probe
  flows/       signup, onboarding, warmup, review_policy, identity, avatar_sources, geo
  selector_registry/  registry.yaml + resolver
  api/         admin, schemas
  db/          models, session
  cli.py
tests/         unit, integration, cases/E-xx, chaos
docs/          RUNBOOK, WARMING, EDGE_CASES, DEVIATIONS
scripts/       yf_launcher.ps1
```
