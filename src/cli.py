"""``yf`` command line entry point."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

from core.config import get_settings
from obs.log import configure_logging, get_logger

log = get_logger("cli")


def _print(payload) -> None:
    print(json.dumps(payload, indent=2, default=str, ensure_ascii=False))


def _deps(settings):
    from adapters.captcha import build_chain
    from adapters.email import build_provider
    from adapters.gpm_mcp import HybridGPM
    from adapters.gpm_http import GPMHttpClient
    from core.orchestrator import SignupDeps
    from selector_registry.resolver import SelectorRegistry

    http = GPMHttpClient(base_url=settings.gpm.base_url, flavor=settings.gpm.flavor, timeout=settings.gpm.connect_timeout_s)
    gpm = HybridGPM(settings.gpm.mcp_url, settings.gpm.mcp_token, http)
    email_provider = build_provider(settings)
    captcha = build_chain(settings.captcha)
    registry = SelectorRegistry.from_yaml()
    sms_provider = None
    if settings.sms.api_key:
        from adapters.sms import HupSmsProvider, SmsActivateProvider

        if settings.sms.provider == "hup":
            sms_provider = HupSmsProvider(
                settings.sms.api_key,
                service_id=settings.sms.service_id,
                timeout_s=settings.sms.timeout_s,
            )
        else:
            sms_provider = SmsActivateProvider(settings.sms.api_key, country=settings.sms.country)
    return SignupDeps(
        settings=settings, gpm=gpm, registry=registry, email=email_provider, captcha=captcha, sms=sms_provider
    )


def cmd_avatar(args) -> int:
    import uuid as _uuid

    from sqlalchemy import select

    from core.orchestrator import upload_avatar
    from db.models import Account, AccountState
    from db.session import session_scope

    settings = get_settings()
    deps = _deps(settings)
    if getattr(args, "batch", None):
        from core.batches import batch_account_ids

        ids = batch_account_ids(args.batch)
    elif args.all or args.missing:
        statement = select(Account.id).where(
            Account.state.in_(
                (AccountState.ACTIVE.value, AccountState.WARMING.value, AccountState.ONBOARDED.value)
            )
        )
        if args.missing:
            statement = statement.where(Account.substate.is_distinct_from("avatar_uploaded"))
        with session_scope() as session:
            ids = list(session.scalars(statement.order_by(Account.created_at)))
    else:
        if not args.account:
            _print({"error": "account_required"})
            return 2
        ids = [_uuid.UUID(args.account)]

    async def run_all():
        semaphore = asyncio.Semaphore(max(1, args.concurrency))

        async def one(account_id):
            async with semaphore:
                try:
                    return await upload_avatar(account_id, deps, avatar_path=args.file)
                except Exception as exc:  # noqa: BLE001
                    return {"account": str(account_id), "ok": False, "error": str(exc)[:200]}

        return await asyncio.gather(*(one(account_id) for account_id in ids))

    results = list(asyncio.run(run_all())) if ids else []
    ok = sum(1 for item in results if item.get("ok"))
    _print({"count": len(results), "ok": ok, "results": results})
    return 0 if ok == len(results) else 1


def cmd_status(args) -> int:
    from core.batches import list_batches, status_snapshot

    snapshot = status_snapshot()
    print("accounts: " + " ".join(f"{key}={value}" for key, value in sorted(snapshot["states"].items())))
    print(
        f"warming : sessions_today={snapshot['sessions_today']} "
        f"actions_today={snapshot['actions_today']} "
        f"pending_tasks={snapshot['pending_tasks']} done_today={snapshot['done_today']}"
    )
    print(f"next_due: {snapshot['next_due'] or '-'}")
    rows = list_batches()
    if args.by_batch:
        for item in rows:
            phases = ", ".join(f"{key}:{value}" for key, value in (item["phases"] or {}).items()) or "-"
            trust = (
                f"{item['trust_min']}-{item['trust_max']}"
                if item["trust_min"] is not None
                else "-"
            )
            actions = ", ".join(f"{key}:{value}" for key, value in item["next_actions"].items()) or "-"
            print(
                f"{item['name']:<4} {item['accounts']:>3} acc  {item['status']:<8} "
                f"{phases:<26} sessions={item['sessions_today']:<3} actions={item['actions_today']:<4} "
                f"trust={trust:<7} next={actions}"
            )
    else:
        print(f"batches : {len(rows)}")
    return 0


def cmd_batch(args) -> int:
    import json

    from core import batches as store

    action = args.batch_action
    name = args.name or getattr(args, "name_opt", None)
    if action not in ("list", "backfill") and not name:
        print("batch name required")
        return 2
    try:
        if action == "create":
            print(json.dumps(store.create_batch(name, source=args.source, target_count=args.target, notes=args.notes), default=str))
        elif action == "list":
            for item in store.list_batches():
                phases = ", ".join(f"{key}:{value}" for key, value in (item["phases"] or {}).items()) or "-"
                print(
                    f"{item['name']:<4} {item['accounts']:>3} acc  {item['status']:<8} {phases:<26} "
                    f"sessions={item['sessions_today']} actions={item['actions_today']} "
                    f"next={item['next_actions']}"
                )
        elif action == "show":
            print(json.dumps(store.batch_summary(name), default=str, ensure_ascii=False, indent=2))
        elif action == "next":
            print(json.dumps(store.batch_next(name), default=str, ensure_ascii=False, indent=2))
        elif action == "backfill":
            print(json.dumps(store.backfill_legacy()))
        elif action == "pause":
            print(json.dumps(store.set_status(name, "paused")))
        elif action == "resume":
            print(json.dumps(store.set_status(name, "warming")))
        elif action == "close":
            print(json.dumps(store.set_status(name, "closed")))
        else:
            print(f"unknown action: {action}")
            return 2
    except ValueError as exc:
        print(str(exc))
        return 2
    return 0


def cmd_trust(args) -> int:
    import uuid as _uuid

    from core.trust import compute_trust, review_eligible

    account_id = _uuid.UUID(args.account)
    breakdown = compute_trust(account_id)
    ok, reason = review_eligible(account_id)
    _print({"account": args.account, "score": breakdown.score, "components": breakdown.as_dict(), "review_eligible": ok, "review_reason": reason})
    return 0


def cmd_verify(args) -> int:
    import uuid as _uuid

    from core.orchestrator import probe_account, verify_login

    settings = get_settings()
    deps = _deps(settings)
    if args.all:
        from db.models import Account
        from db.session import session_scope

        with session_scope() as session:
            ids = [a.id for a in session.query(Account).order_by(Account.created_at).all()]
        results = {}
        for account_id in ids:
            try:
                if args.probe:
                    results[str(account_id)] = asyncio.run(probe_account(account_id, deps))
                else:
                    results[str(account_id)] = asyncio.run(verify_login(account_id, deps))
            except Exception as exc:  # noqa: BLE001
                results[str(account_id)] = {"exists": None, "reason": f"error: {str(exc)[:120]}"}
        _print(results)
        return 0
    if args.probe:
        result = asyncio.run(probe_account(_uuid.UUID(args.account), deps))
        _print(result)
        return 0 if result.get("exists") else 1
    result = asyncio.run(verify_login(_uuid.UUID(args.account), deps))
    _print(result)
    return 0 if result.get("ok") else 1


def cmd_schedule(args) -> int:
    from core.scheduler import bootstrap, run_due, scheduler_loop

    settings = get_settings()
    deps = _deps(settings)
    if args.once:
        _print(bootstrap())
        _print(asyncio.run(run_due(deps, limit=args.limit, max_seconds=args.minutes * 60)))
        return 0
    asyncio.run(scheduler_loop(deps, interval_s=args.interval, max_seconds=args.minutes * 60))
    return 0


def cmd_warm(args) -> int:
    import uuid as _uuid

    from core.batches import batch_account_ids
    from core.orchestrator import run_warm

    settings = get_settings()
    deps = _deps(settings)
    if getattr(args, "batch", None):
        ids = batch_account_ids(args.batch)
    elif args.account:
        ids = [_uuid.UUID(args.account)]
    else:
        _print({"error": "account_or_batch_required"})
        return 2
    results = [
        asyncio.run(run_warm(account_id, deps, sessions=args.sessions, max_seconds=args.minutes * 60))
        for account_id in ids
    ]
    _print({"count": len(results), "results": results})
    return 0


def cmd_profile(args) -> int:
    import uuid as _uuid

    from sqlalchemy import select

    from core.orchestrator import run_profile_completion
    from db.models import Account, AccountState
    from db.session import session_scope

    settings = get_settings()
    deps = _deps(settings)
    if getattr(args, "batch", None):
        from core.batches import batch_account_ids

        ids = batch_account_ids(args.batch)
    elif args.all:
        with session_scope() as session:
            ids = list(
                session.scalars(
                    select(Account.id)
                    .where(
                        Account.state.in_(
                            (AccountState.ACTIVE.value, AccountState.WARMING.value, AccountState.ONBOARDED.value)
                        ),
                        Account.substate.is_distinct_from("profile_completed"),
                    )
                    .order_by(Account.created_at)
                )
            )
    else:
        if not args.account:
            _print({"error": "account_or_batch_required"})
            return 2
        ids = [_uuid.UUID(args.account)]

    async def run_all():
        semaphore = asyncio.Semaphore(max(1, args.concurrency))

        async def one(account_id):
            async with semaphore:
                try:
                    return await run_profile_completion(account_id, deps)
                except Exception as exc:  # noqa: BLE001
                    return {"account": str(account_id), "error": str(exc)[:200]}

        return await asyncio.gather(*(one(account_id) for account_id in ids))

    results = list(asyncio.run(run_all())) if ids else []
    _print({"count": len(results), "results": results})
    return 0


def cmd_resume(args) -> int:
    import uuid as _uuid

    from core.orchestrator import resume_account

    settings = get_settings()
    deps = _deps(settings)
    state = asyncio.run(resume_account(_uuid.UUID(args.account), deps, raw_proxy=args.proxy))
    _print({"account": args.account, "state": state.value})
    return 0 if state == __import__("db.models", fromlist=["AccountState"]).AccountState.ACTIVE else 1


def cmd_import_emails(args) -> int:
    from core.importers import parse_emails, read_file
    from core.pool import import_emails
    from db.models import EmailPool
    from db.session import session_scope

    settings = get_settings()
    text = read_file(args.file)
    with session_scope() as session:
        existing = {row.mailbox_email for row in session.query(EmailPool).all()} | {row.alias for row in session.query(EmailPool).all()}
    report = parse_emails(
        text,
        default_client_id=args.client_id or settings.email.graph_client_id,
        default_domain=args.domain or settings.email.domains[0],
        existing=existing,
    )
    result = {"total": report.total, "valid": len(report.rows), "duplicates": report.duplicates, "invalid": len(report.errors)}
    if report.errors:
        result["errors"] = [{"line": e.line, "reason": e.reason, "row": e.raw} for e in report.errors]
    if args.dry_run:
        _print({**result, "dry_run": True})
        return 0
    if report.rows:
        result.update(import_emails(report.rows, source_file=str(args.file)))
    _print(result)
    return 0 if report.rows else 1


def cmd_import_proxies(args) -> int:
    from core.importers import parse_proxies, read_file
    from core.pool import import_proxies
    from db.models import ProxyPool
    from db.session import session_scope

    text = read_file(args.file)
    with session_scope() as session:
        existing = {row.raw for row in session.query(ProxyPool).all()}
    report = parse_proxies(text, existing=existing)
    result = {"total": report.total, "valid": len(report.rows), "duplicates": report.duplicates, "invalid": len(report.errors)}
    if report.errors:
        result["errors"] = [{"line": e.line, "reason": e.reason, "row": e.raw} for e in report.errors]
    if args.dry_run:
        _print({**result, "dry_run": True})
        return 0
    if report.rows:
        result.update(import_proxies(report.rows, source_file=str(args.file)))
    _print(result)
    return 0 if report.rows else 1


def cmd_pool(args) -> int:
    from core.pool import stats
    from db.models import EmailPool, ProxyPool
    from db.session import session_scope

    payload = stats()
    if args.list:
        with session_scope() as session:
            payload["email_rows"] = [
                {"alias": row.alias, "mailbox": row.mailbox_email, "status": row.status}
                for row in session.query(EmailPool).order_by(EmailPool.imported_at.desc()).limit(args.limit).all()
            ]
            payload["proxy_rows"] = [
                {
                    "raw": f"{row.host}:{row.port}:{row.username}:***",
                    "status": row.status,
                    "accounts": row.accounts_count,
                    "ip": row.ip,
                }
                for row in session.query(ProxyPool).order_by(ProxyPool.imported_at.desc()).limit(args.limit).all()
            ]
    _print(payload)
    return 0


def cmd_gpm_health(args) -> int:
    settings = get_settings()
    client = _deps(settings).gpm
    try:
        health = client.health()
        profiles = client.list_profiles()
        _print({"health": health, "profiles": len(profiles), "transport": client.last_transport})
        return 0
    finally:
        client.close()


def cmd_gpm_list(args) -> int:
    settings = get_settings()
    client = _deps(settings).gpm
    try:
        rows = [
            {"id": p.id, "name": p.name, "browser": p.browser_version, "proxy": bool(p.raw_proxy)}
            for p in client.list_profiles()
        ]
        _print(rows)
        return 0
    finally:
        client.close()


def cmd_signup(args) -> int:
    from core.orchestrator import create_account, run_batch
    from flows.geo import resolve_target_city

    settings = get_settings()
    city = args.city
    probe_result = None
    auto_city = not city or city.lower() == "auto"
    pool_proxy_source = args.source in ("pool_proxy", "pool_both")
    if auto_city:
        if pool_proxy_source:
            # Every account probes its own pool proxy right before it is created.
            city = settings.target.cities[0]
        else:
            # City is derived from the proxy IP, not typed by the operator.
            city, probe_result = asyncio.run(
                resolve_target_city(
                    settings.proxy.default_raw,
                    fallback=settings.target.cities[0],
                    country=settings.target.country,
                )
            )
    domain = args.domain or settings.email.domains[0]
    deps = _deps(settings)

    batch_id = None
    if getattr(args, "batch", None):
        from core.batches import create_batch, get_batch

        batch = get_batch(args.batch)
        if batch is None:
            create_batch(args.batch, source=args.source, target_count=args.count)
            batch = get_batch(args.batch)
        batch_id = batch.id

    account_ids = []
    try:
        for _ in range(args.count):
            account_ids.append(
                create_account(
                    city,
                    domain,
                    source=args.source,
                    max_per_proxy=args.max_per_proxy,
                    probe_city=auto_city and pool_proxy_source,
                    batch_id=batch_id,
                )
            )
    except RuntimeError as exc:
        _print({"error": str(exc), "created": [str(a) for a in account_ids]})
        return 2
    log.info("signup_batch_started", count=len(account_ids), city=city, dry_run=args.dry_run, source=args.source)
    if args.dry_run:
        _print({"created": [str(a) for a in account_ids], "dry_run": True})
        return 0
    results = asyncio.run(run_batch(account_ids, deps, concurrency=args.concurrency, proxy=args.proxy))
    ok = sum(1 for state in results.values() if state == "ACTIVE")
    _print({"results": results, "active": ok, "total": len(results)})
    return 0 if ok == len(results) else 1


def cmd_report(args) -> int:
    from core.report import build_report

    _print(build_report(args.since))
    return 0


def cmd_reap(args) -> int:
    from core.reaper import run_reaper

    settings = get_settings()
    gpm = _deps(settings).gpm
    report = run_reaper(gpm, artifacts_root=Path(settings.artifacts_dir), artifacts_days=settings.retention.artifacts_days)
    _print(report)
    return 0


def cmd_quarantine(args) -> int:
    from core.report import recent_events

    _print(recent_events(limit=args.limit, code=args.code))
    return 0


def cmd_db_init(args) -> int:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(cfg, "head")
    print("database upgraded to head")
    return 0


def cmd_serve(args) -> int:
    import uvicorn

    settings = get_settings()
    uvicorn.run("api.admin:app", host=settings.admin_host, port=args.port or settings.admin_port, log_level="info")
    return 0


def cmd_probe_profile(args) -> int:
    """Attach to an existing GPM profile and report what the browser shows."""

    async def run():
        from adapters.browser import attach

        settings = get_settings()
        client = _deps(settings).gpm
        started = client.start_profile(args.profile_id, window_size="1280,800")
        browser = await attach(started.cdp_url, timeout_s=settings.gpm.connect_timeout_s)
        page = browser.page
        await page.goto("https://www.yelp.com/?locale=en_US", wait_until="domcontentloaded", timeout=60_000)
        title = await page.title()
        url = page.url
        await browser.close()
        client.stop_profile(args.profile_id)
        _print({"cdp": started.cdp_url, "process_id": started.process_id, "title": title, "url": url})

    asyncio.run(run())
    return 0


def cmd_proxy_probe(args) -> int:
    from adapters.proxy_probe import ProxyTarget, probe

    settings = get_settings()
    raw = args.raw or settings.proxy.default_raw
    result = asyncio.run(probe(ProxyTarget(raw=raw, country=settings.target.country), timeout_s=settings.proxy.probe_timeout_s))
    from dataclasses import asdict

    _print(asdict(result))
    return 0 if result.ok else 1


def cmd_mail_probe(args) -> int:
    from adapters.email import build_provider

    settings = get_settings()
    provider = build_provider(settings)
    alias = args.alias or f"yfprobe{__import__('random').randint(1000, 9999)}@{settings.email.domains[0]}"
    ok = asyncio.run(provider.probe(alias))
    _print({"alias": alias, "delivered": ok})
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="yf", description="Yelp account factory")
    parser.add_argument("--log-level", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("gpm-health", help="check GPM app + count profiles").set_defaults(func=cmd_gpm_health)
    sub.add_parser("gpm-list", help="list GPM profiles").set_defaults(func=cmd_gpm_list)

    import_emails = sub.add_parser("import-emails", help="import email|password|token|client_id|alias lines")
    import_emails.add_argument("--file", required=True)
    import_emails.add_argument("--client-id", default=None)
    import_emails.add_argument("--domain", default=None)
    import_emails.add_argument("--dry-run", action="store_true")
    import_emails.set_defaults(func=cmd_import_emails)

    import_proxies = sub.add_parser("import-proxies", help="import host:port:user:pass lines")
    import_proxies.add_argument("--file", required=True)
    import_proxies.add_argument("--dry-run", action="store_true")
    import_proxies.set_defaults(func=cmd_import_proxies)

    pool = sub.add_parser("pool", help="email/proxy pool statistics")
    pool.add_argument("--list", action="store_true")
    pool.add_argument("--limit", type=int, default=20)
    pool.set_defaults(func=cmd_pool)

    signup = sub.add_parser("signup", help="create accounts and run the signup flow")
    signup.add_argument("--count", type=int, default=1)
    signup.add_argument("--city", default=None, help="auto (default) = derive from proxy IP")
    signup.add_argument("--domain", default=None)
    signup.add_argument("--proxy", default=None)
    signup.add_argument("--concurrency", type=int, default=1)
    signup.add_argument("--source", choices=["auto", "pool_email", "pool_proxy", "pool_both"], default="auto")
    signup.add_argument("--batch", default=None, help="batch name (created if missing)")
    signup.add_argument("--max-per-proxy", type=int, default=2)
    signup.add_argument("--dry-run", action="store_true")
    signup.set_defaults(func=cmd_signup)

    resume = sub.add_parser("resume", help="resume a crashed account from its last checkpoint")
    resume.add_argument("--account", required=True)
    resume.add_argument("--proxy", default=None)
    resume.set_defaults(func=cmd_resume)

    warm = sub.add_parser("warm", help="run warming sessions for an ACTIVE account or batch")
    warm.add_argument("--account", default=None)
    warm.add_argument("--batch", default=None)
    warm.add_argument("--sessions", type=int, default=1)
    warm.add_argument("--minutes", type=int, default=12)
    warm.set_defaults(func=cmd_warm)

    status = sub.add_parser("status", help="compact factory status")
    status.add_argument("--by-batch", action="store_true")
    status.set_defaults(func=cmd_status)

    batch = sub.add_parser("batch", help="batch tracking")
    batch.add_argument("batch_action", choices=["create", "list", "show", "next", "backfill", "pause", "resume", "close"])
    batch.add_argument("name", nargs="?", default=None)
    batch.add_argument("--name", dest="name_opt", default=None)
    batch.add_argument("--source", default="auto")
    batch.add_argument("--target", type=int, default=0)
    batch.add_argument("--notes", default=None)
    batch.set_defaults(func=cmd_batch)

    profile = sub.add_parser("profile", help="fill every optional Yelp profile field")
    profile.add_argument("--account", default=None)
    profile.add_argument("--batch", default=None)
    profile.add_argument("--all", action="store_true")
    profile.add_argument("--concurrency", type=int, default=2)
    profile.set_defaults(func=cmd_profile)

    schedule = sub.add_parser("schedule", help="plan and run due warming sessions")
    schedule.add_argument("--once", action="store_true", help="single pass, then exit")
    schedule.add_argument("--interval", type=int, default=300, help="seconds between passes")
    schedule.add_argument("--limit", type=int, default=8)
    schedule.add_argument("--minutes", type=int, default=8)
    schedule.set_defaults(func=cmd_schedule)

    avatar = sub.add_parser("avatar", help="upload the stored avatar to an account profile")
    avatar.add_argument("--account", default=None)
    avatar.add_argument("--batch", default=None)
    avatar.add_argument("--all", action="store_true")
    avatar.add_argument("--missing", action="store_true")
    avatar.add_argument("--file", default=None)
    avatar.add_argument("--concurrency", type=int, default=2)
    avatar.set_defaults(func=cmd_avatar)

    trust = sub.add_parser("trust", help="show the trust score of an account")
    trust.add_argument("--account", required=True)
    trust.set_defaults(func=cmd_trust)

    verify = sub.add_parser("verify-login", help="prove an account really exists by logging in")
    verify.add_argument("--account", default=None)
    verify.add_argument("--all", action="store_true")
    verify.add_argument("--probe", action="store_true", help="use the signup page to test if the email exists")
    verify.set_defaults(func=cmd_verify)

    report = sub.add_parser("report", help="aggregate numbers for a time window")
    report.add_argument("--since", default="24h")
    report.set_defaults(func=cmd_report)

    sub.add_parser("reap", help="clean locks, stuck runs, orphan profiles, old artifacts").set_defaults(func=cmd_reap)

    quarantine = sub.add_parser("quarantine", help="recent quarantine events")
    quarantine.add_argument("--limit", type=int, default=50)
    quarantine.add_argument("--code", default=None)
    quarantine.set_defaults(func=cmd_quarantine)

    sub.add_parser("db-init", help="run alembic migrations").set_defaults(func=cmd_db_init)

    serve = sub.add_parser("serve", help="run the admin API")
    serve.add_argument("--port", type=int, default=None)
    serve.set_defaults(func=cmd_serve)

    probe = sub.add_parser("probe-profile", help="attach CDP to a GPM profile and print the page title")
    probe.add_argument("--profile-id", required=True)
    probe.set_defaults(func=cmd_probe_profile)

    proxy = sub.add_parser("proxy-probe", help="check a proxy geo/latency")
    proxy.add_argument("--raw", default=None)
    proxy.set_defaults(func=cmd_proxy_probe)

    mail = sub.add_parser("mail-probe", help="prove an email alias is routable")
    mail.add_argument("--alias", default=None)
    mail.set_defaults(func=cmd_mail_probe)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(args.log_level or settings.log_level, json_output=True)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
