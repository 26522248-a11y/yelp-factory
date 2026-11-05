# Factory state

updated: 2026-11-05 00:25
phase: ngày 2/30 — tất cả đang P0 (chỉ browse)

## Mẻ

| Mẻ | Acc | Thành công | Ghi chú |
|---|---|---|---|
| B0 | 1 | 0 | legacy 03/11 |
| B1 | 6 | 2 | 4 quarantine lúc setup SMS |
| B2 | 20 | 18 | 1 quarantine GPM, 1 profile thiếu |
| B3 | 3 | 3 | code mới, profile đầy đủ |

## Tổng

- accounts: 23 WARMING + 1 ONBOARDED + 6 QUARANTINED = 30
- profile: 23/24 success
- avatar: 22/24 uploaded (2 lỗi proxy tunnel)
- warming 04/11: 48 session, 485 action, 0 failed
- trust: 37–40 (5 acc đã 40, mở save ở phiên tới)

## Tiếp theo

1. Warming tự động: task `YelpFactoryWarming`, phiên đầu 08:00 05/11
2. Avatar retry: task `YelpFactoryAvatarRetry` lúc 12:00
3. 06/11: lên P1 (save business) — review mở khi trust ≥ 75 + ngày 11
4. Batch mới: dùng `yf signup --batch B4 ...`

## Blockers

- 2 acc proxy chết: `rrxlvnsyphg6m8@…`, `iemrozlhixkpcl@…`
- 1 acc quarantine GPM: `vxkuxnchgu36il@…` (chưa từng tạo trên Yelp)
