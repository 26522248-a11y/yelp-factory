# Yelp Factory — Agent Guide

> Đọc file này trước khi làm bất cứ việc gì với factory.
> Không đọc source code để trả lời vận hành — chỉ dùng các lệnh dưới đây.

Mọi lệnh chạy tại `C:\Users\Administrator\.paseo\hihicuti`.
Nếu `yf` không có trong PATH, dùng `.\.venv\Scripts\yf.exe`.

## 0. Bắt đầu mỗi phiên (30 giây)

```powershell
cd C:\Users\Administrator\.paseo\hihicuti
.\.venv\Scripts\yf.exe status --by-batch
Get-Content docs\STATE.md
Get-Content docs\JOURNAL.md -Tail 20
```

Ba lệnh này đủ để biết: mẻ nào đang ở đâu, việc gì đang chờ, việc gì đã làm.
Không query DB trước khi chạy chúng.

## 1. Ý định → Lệnh

| Người dùng nói | Chạy |
|---|---|
| Tạo N tài khoản (mẻ mới) | `yf signup --batch B4 --count 5 --source pool_proxy --city auto --concurrency 2` |
| Tạo acc từ email/proxy đã import | `yf signup --batch B5 --count 5 --source pool_both --max-per-proxy 2` |
| Xem tất cả mẻ | `yf batch list` |
| Xem chi tiết 1 mẻ | `yf batch show B2` |
| Việc cần làm của mẻ | `yf batch next B2` |
| Tạm dừng / chạy lại mẻ | `yf batch pause B2` · `yf batch resume B2` |
| Import email | `yf import-emails --file <path> --dry-run` rồi bỏ `--dry-run` |
| Import proxy | `yf import-proxies --file <path> --dry-run` rồi bỏ `--dry-run` |
| Xem kho | `yf pool --list` |
| Cập nhật avatar còn thiếu | `yf avatar --missing` |
| Cập nhật avatar cả mẻ | `yf avatar --batch B2` |
| Cập nhật avatar 1 acc | `yf avatar --account <uuid>` |
| Điền profile còn thiếu | `yf profile --all` |
| Điền profile 1 mẻ | `yf profile --batch B2` |
| Nuôi 1 acc | `yf warm --account <uuid> --minutes 6` |
| Nuôi cả mẻ | `yf warm --batch B2 --minutes 6` |
| Nuôi các acc đến hạn | `yf schedule --once --limit 4 --minutes 6` |
| Xem trust | `yf trust --account <uuid>` |
| Kiểm tra acc tồn tại | `yf verify-login --account <uuid>` |
| Cứu acc crash/kẹt | `yf resume --account <uuid>` |
| Dọn lock/rác | `yf reap` |
| Báo cáo tổng | `yf report --since 24h` |
| Xuất dữ liệu sheet | `python src\export_accounts.py` |

### Scripts tiện dụng (cùng việc, không cần nhớ tham số)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\create_accounts.ps1 -Count 5 -Batch B4
powershell -ExecutionPolicy Bypass -File scripts\update_avatars.ps1            # chỉ acc thiếu
powershell -ExecutionPolicy Bypass -File scripts\update_avatars.ps1 -Batch B2
powershell -ExecutionPolicy Bypass -File scripts\warm_accounts.ps1            # các acc đến hạn
powershell -ExecutionPolicy Bypass -File scripts\warm_accounts.ps1 -Batch B2
```

## 2. Quy tắc bắt buộc

1. **Không đọc source** cho câu hỏi vận hành.
2. **Không commit/push** trừ khi người dùng yêu cầu rõ.
3. **Không in password/token** ra chat. Chỉ ghi Google Sheet khi được yêu cầu.
4. **Không sửa DB trực tiếp**, trừ quy trình cứu acc ở §5.
5. Warming tự chạy qua Scheduled Task — không mở vòng lặp thứ hai.
6. Lệnh dài: `*> data\_<ten>.log`, chỉ đọc 10 dòng cuối.
7. Kết thúc việc: cập nhật `docs\STATE.md` + append `docs\JOURNAL.md`.

## 3. Mô hình trạng thái

- Đăng ký: `NEW → PROVISIONING → PROXY_BOUND → BROWSER_UP → PREWARMED → FORM_FILLED → CAPTCHA_SOLVED → SUBMITTED → ONBOARDED → EMAIL_PENDING → EMAIL_VERIFIED → ACTIVE`
- Nuôi: `ACTIVE → WARMING → P0 (ngày 1–2) → P1 (3–5) → P2 (6–10) → P3 (11–20) → P4 (21–30) → MATURE`
- Trust: `<40` chỉ browse · `40–59` + save · `60–74` + vote/follow · `>=75` mới review (kèm age ≥ 11 ngày)
- Lỗi: `QUARANTINED` (xử lý được), `RESTRICTED`, `SUSPENDED`, `DEAD`

## 4. Stage trong báo cáo mẻ

| Stage | Ý nghĩa |
|---|---|
| `REGISTERING` | đang chạy form đăng ký |
| `CREATED` | Yelp đã tạo acc, chưa ACTIVE |
| `READY` | ACTIVE, chưa có phiên nuôi nào |
| `WARM_P0..P4` | đang nuôi theo pha |
| `MATURE` | quá 30 ngày |
| `QUARANTINED`... | lỗi |

`yf batch next` chỉ trả các acc có việc: `avatar`, `profile`, `warm`, `recover`, `onboard`, `skip`.

## 5. Cứu acc kẹt profile (đã tạo thật trên Yelp)

Chỉ khi bước `SUBMITTED` = DONE và `ONBOARDED` lỗi:

```sql
update accounts set state='ONBOARDED', substate=null,
  quarantine_reason=null, last_error_code=null
where email='<email>';
```

Sau đó: `yf resume --account <uuid>`.

## 6. Cây quyết định

```
Acc lỗi?
├─ QUARANTINED + SUBMITTED DONE   -> yf resume
├─ QUARANTINED + chưa SUBMITTED   -> bỏ, tạo acc mới
├─ ERR_TUNNEL_CONNECTION_FAILED   -> proxy chết: retry sau / đổi proxy
└─ ACTIVE thiếu field
   ├─ thiếu avatar  -> yf avatar --missing
   └─ thiếu profile -> yf profile --all
```

## 7. Scheduled Tasks

| Task | Nhịp | Việc |
|---|---|---|
| `YelpFactoryWarming` | 30 phút | `schedule --once --limit 4 --minutes 6` |
| `YelpFactoryAvatarRetry` | 12:00 hằng ngày | `avatar --missing` |

Kiểm tra: `schtasks /query /tn "YelpFactoryWarming" /fo LIST`.

## 8. Kiểm tra sức khoẻ

```powershell
yf gpm-health        # GPM + số profile
yf pool --list       # email/proxy còn dùng được
yf status --by-batch # tổng quan
```

Kỳ vọng: GPM OK, proxy US available > 0, task `Ready`.

## 9. File & log

| Đường dẫn | Nội dung |
|---|---|
| `data\_*.log` | log từng lần chạy |
| `data\warming_task.log` | log warming tự động |
| `data\accounts_export\accounts.csv` | dữ liệu cho tab `acc reg` |
| `data\accounts_export\batches.csv` | dữ liệu cho tab `batches` |
| `data\avatar_pool\` | pool ảnh |
| `artifacts\avatar_<id>.jpg` | avatar từng acc |
| `docs\STATE.md`, `docs\JOURNAL.md` | trạng thái & lịch sử |
| `.env` | secret — không đọc/in |

## 10. Khi nào hỏi người

- Proxy chết > 30% pool
- Acc bị SUSPENDED/RESTRICTED
- Cần xoá dữ liệu / đổi cấu hình lớn
- Google Sheet lỗi quyền
