# Warming spec v1.0 — trạng thái triển khai

Mục tiêu: đưa tài khoản ACTIVE về trust cao nhất trước D+30.

## Đã có trong code

| Hạng mục | Vị trí |
|---|---|
| Trust score 0–100 (age/profile/consistency/diversity/content/risk) | `src/core/trust.py` |
| Gate hành động theo score (<40 browse, 40 save, 60 vote/follow, ≥75 review) | `trust.allowed_kinds` |
| Review eligibility (score, age ≥11d, ≥6 session/7d, không filter 7d) | `trust.review_eligible` |
| Rating mix theo pha, ảnh 40%, 5-gram ≤ 40%, cấm link/giá | `src/flows/review_policy.py` |
| Business eligibility (≥5 review, rating 3.5–4.8, không chain) | `review_policy.business_eligible` |
| Weekly cap (P3: 2, P4: 3), cùng business cooldown 90 ngày | `review_policy.decide` |
| Action log + warming session + trust snapshot | bảng `action_log`, `warming_sessions`, `trust_scores`, `review_attempts` |
| Session rhythm: 90 phút giãn cách, nghỉ ngày thứ 7, 07:00–22:30 local | `core/scheduler.py` |
| 1 account / proxy tại một thời điểm | `scheduler.due_sessions` (dedupe theo `proxy_ip`) |
| 1 proxy ↔ 1–2 account | mỗi account có sessid riêng (`adapters/proxysession.py`), cấu hình `proxy.max_accounts` |
| Avatar phong cảnh/chó mèo/meme | `flows/identity.py` + `flows/avatar_sources.py` (pool scrape: Pinterest → Reddit → Wikimedia → IG/FB og:image → stock picsum/cataas) |
| CLI kiểm tra | `yf trust --account <id>` |

## Phone

Yelp để **Phone Number Optional** ở bước hoàn thiện profile; flow bỏ trống. HupSMS chỉ bán số VN
nên không dùng để verify US. Nếu sau này có SMS US, điền vào `_enter_onboarded` và cộng 2 điểm trust.

## KPI cần theo dõi

`yf report --since 24h` hiện có account state; trust/action query:

```sql
SELECT a.email, t.score, t.components
FROM accounts a JOIN LATERAL (
  SELECT score, components FROM trust_scores WHERE account_id = a.id ORDER BY id DESC LIMIT 1
) t ON true
WHERE a.state IN ('ACTIVE','WARMING');
```

## Việc còn lại (chưa làm)

- Review published detection (đọc lại trang business sau 48h/7 ngày) — hiện chỉ ghi `submitted`.
- Ảnh review (upload photo) — cần pool ảnh tự chụp.
- Báo cáo KPI tự động ra sheet/email.
- Canary 14 ngày để tinh chỉnh ngưỡng trust.

## Avatar pool (scrape)

`flows/avatar_sources.py` gom ?nh t?: Pinterest (ideas + search, HTML scrape), Reddit public JSON,
Wikimedia Commons API, Instagram/Facebook `og:image`, v� stock fallback (picsum, cataas).
?nh h?p l? (image/*, 15 KB�6 MB, sha256 chua c�) du?c luu v�o `data/avatar_pool` + `index.json`,
`fetch_avatar()` l?y t? pool tru?c khi g?i m?ng.

T? IP hi?n t?i: **Pinterest, picsum, cataas tr? ?nh**; Reddit/Wikimedia/Unsplash/Pexels tr? 403,
Instagram/Facebook tr? login wall � scraper t? b? qua v� d�ng ngu?n c�n l?i.

L�m d?y pool:

```powershell
.\.venv\Scripts\python.exe -c "import asyncio; from flows.avatar_sources import refill_pool; print(asyncio.run(refill_pool(wanted=10)))"
```
