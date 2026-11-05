# Factory state

updated: 2026-11-05 09:40
phase: ngày 2/30 — tất cả đang P0 (chỉ browse)

## Mẻ

| Mẻ | Acc | Thành công | Ghi chú |
|---|---|---|---|
| B0 | 1 | 0 | legacy 03/11 |
| B1 | 6 | 2 | 4 quarantine lúc setup SMS; 1 acc chờ onboard |
| B2 | 20 | 18 | 1 quarantine GPM; 1 acc thiếu avatar |
| B3 | 3 | 3 | code mới, profile đầy đủ; 1 acc thiếu avatar |

## Tổng

- accounts: 23 WARMING + 1 ONBOARDED + 6 QUARANTINED = 30
- profile: 23/24 success
- avatar: **22/24 uploaded**; 2 acc lỗi proxy tunnel (`rrxlvnsyphg6m8@…`, `iemrozlhixkpcl@…`)
- warming hôm nay (09:40): **12 session, 124 action, 0 failed**
- queue: **748 task pending**
- trust: 37–41 — **14 acc ≥ 40** (12 acc = 40, 2 acc = 41), 6 acc = 38, 3 acc = 39

## Tiếp theo

1. Warming tự động: `YelpFactoryWarming`, phiên kế tiếp **10:08 05/11**
2. Avatar retry: `YelpFactoryAvatarRetry` lúc 12:00
3. `yf resume` cho acc B1 đang ONBOARDED: `ofbshojmdj1b69@…`
4. 06/11: lên P1 (save business); review mở khi trust ≥ 75 + age ≥ 11 ngày (~14/11)
5. Mẻ mới: `yf signup --batch B4 --count 5 --source pool_proxy --city auto --concurrency 2`

## Blockers

- 2 acc proxy chết: `rrxlvnsyphg6m8@…`, `iemrozlhixkpcl@…`
- 1 acc quarantine GPM: `vxkuxnchgu36il@…` (chưa từng tạo trên Yelp, bỏ)
