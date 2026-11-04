# yelp-factory

Tự động hoá vòng đời tài khoản Yelp (đăng ký → verify → onboarding → nuôi 30 ngày) trên
browser thật qua GPM Login Global, điều khiển bằng Playwright CDP.

Spec gốc: `SPEC` v1.0 (mục 1-19). Các điểm lệch spec: `docs/DEVIATIONS.md`.
Ma trận edge case: `docs/EDGE_CASES.md`. Vận hành: `docs/RUNBOOK.md`.
**Hướng dẫn sử dụng A–Z: [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md)**

## Trạng thái hiện tại

| Hạng mục | Trạng thái |
|---|---|
| Scaffold + config + logging + redact | ✅ |
| Schema Postgres (12 bảng + bảng phụ) + Alembic | ✅ |
| GPM HTTP adapter (envelope, port discovery, schema drift) | ✅ |
| GPM MCP adapter (streamable HTTP) + fallback | ✅ |
| Idempotent profile create (E-20, D-02) | ✅ |
| CDP attach (không tạo context mới) | ✅ |
| Proxy probe (geo/latency/ASN) | ✅ |
| Email: Graph OAuth2 + IMAP XOAUTH2 + fake | ✅ (mailbox đang bị Microsoft suspend) |
| Captcha: Capsolver + 2captcha + HITL + chain | ✅ |
| SMS: sms-activate + fake | ✅ |
| Selector registry + resolver + fallback | ✅ |
| State machine + checkpoint + lock + reaper + governor + budget | ✅ |
| Signup flow 12 state | ✅ (chưa chạy live Yelp) |
| Warming P0-P4 + review generator (5-gram dedupe) | ✅ |
| Warming scheduler (yf schedule) 1-3 session/ngày theo timezone | ✅ |
| Reauth flow | ✅ |
| CLI + admin API | ✅ |
| Test | 185 passed (55/55 edge case) |

## Cài đặt

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
copy .env.example .env    # điền secrets
.\.venv\Scripts\yf.exe db-init
```

## Dùng nhanh

```powershell
.\.venv\Scripts\yf.exe gpm-health
.\.venv\Scripts\yf.exe signup --count 1 --city "Austin, TX" --dry-run
.\.venv\Scripts\yf.exe report --since 24h
```

## Test

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m pytest tests -q --cov=src/core --cov=src/flows --cov-report=term-missing
```

## Cấu trúc

```
src/
  core/            state_machine, checkpoints, lock, backoff, budget, governor, reaper, orchestrator, report, crypto
  adapters/        gpm_http, gpm_mcp, gpm_ops, browser, proxy_probe, email, captcha, sms
  flows/           signup, onboarding, reauth, warmup, pools
  selector_registry/  registry.yaml + resolver (đổi tên từ selectors/, xem D-05)
  human/           typing, mouse, scroll, timing
  obs/             log, metrics, redact
  api/             admin, schemas
  db/              models, session
  cli.py
tests/
  unit/ integration/ e2e/ chaos/ cases/E-xx_*.py
```
