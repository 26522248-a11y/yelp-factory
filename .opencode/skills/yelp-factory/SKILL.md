---
name: yelp-factory
description: Vận hành Yelp Account Factory — tạo tài khoản, nuôi (warming), cập nhật avatar/profile, import proxy/email, kiểm tra trust, báo cáo theo mẻ, xuất Google Sheet. Dùng khi người dùng nói tạo acc Yelp, nuôi acc, cập nhật avatar, import proxy, kiểm tra tài khoản, đồng bộ sheet, xem mẻ nào tới đâu.
---

# Yelp Factory

Project: `C:\Users\Administrator\.paseo\hihicuti`
Guide đầy đủ: `docs/AGENT_GUIDE.md` — đọc file đó, không đọc source.

## Bắt đầu mỗi phiên

```powershell
cd C:\Users\Administrator\.paseo\hihicuti
.\.venv\Scripts\yf.exe status --by-batch
Get-Content docs\STATE.md
Get-Content docs\JOURNAL.md -Tail 20
```

## Lệnh nhanh

| Việc | Lệnh |
|---|---|
| Tạo acc mẻ mới | `yf signup --batch B4 --count 5 --source pool_proxy --city auto --concurrency 2` |
| Tạo từ email/proxy import | `yf signup --batch B5 --count 5 --source pool_both --max-per-proxy 2` |
| Xem mẻ | `yf batch list` · `yf batch show B2` · `yf batch next B2` |
| Pause/resume mẻ | `yf batch pause B2` · `yf batch resume B2` |
| Avatar | `yf avatar --missing` · `yf avatar --batch B2` · `yf avatar --account <uuid>` |
| Profile | `yf profile --all` · `yf profile --batch B2` |
| Warm | `yf warm --account <uuid> --minutes 6` · `yf warm --batch B2 --minutes 6` |
| Warm đến hạn | `yf schedule --once --limit 4 --minutes 6` |
| Import | `yf import-emails --file <path> --dry-run` · `yf import-proxies --file <path> --dry-run` |
| Kho | `yf pool --list` |
| Trust | `yf trust --account <uuid>` |
| Verify | `yf verify-login --account <uuid>` |
| Cứu acc | `yf resume --account <uuid>` |
| Báo cáo | `yf report --since 24h` |
| Xuất sheet | `python src\export_accounts.py` |

### Scripts có sẵn

```powershell
powershell -ExecutionPolicy Bypass -File scripts\create_accounts.ps1 -Count 5 -Batch B4
powershell -ExecutionPolicy Bypass -File scripts\update_avatars.ps1          # acc thiếu avatar
powershell -ExecutionPolicy Bypass -File scripts\warm_accounts.ps1           # acc đến hạn
```

## Trạng thái → hành động

- `QUARANTINED` + bước `SUBMITTED` DONE → `yf resume`
- `ERR_TUNNEL_CONNECTION_FAILED` → proxy chết, retry/đổi proxy
- ACTIVE thiếu avatar → `yf avatar --missing`
- ACTIVE thiếu profile → `yf profile --all`
- Warming tự chạy qua task `YelpFactoryWarming` mỗi 30 phút

## Không làm

- Không query DB trước khi chạy `yf status`
- Không in password/token
- Không commit/push nếu chưa được yêu cầu
- Không sửa code/DB khi chỉ cần vận hành (ngoại lệ: quy trình cứu acc trong AGENT_GUIDE §5)
