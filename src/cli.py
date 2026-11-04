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

    from core.orchestrator import run_warm

    settings = get_settings()
    deps = _deps(settings)
    result = asyncio.run(run_warm(_uuid.UUID(args.account), deps, sessions=args.sessions, max_seconds=args.minutes * 60))
    _print(result)
    return 0


def cmd_resume(args) -> int:
    import uuid as _uuid

    from core.orchestrator import resume_account

    settings = get_settings()
    deps = _deps(settings)
    state = asyncio.run(resume_account(_uuid.UUID(args.account), deps, raw_proxy=args.proxy))
    _print({"account": args.account, "state": state.value})
    return 0 if state == __import__("db.models", fromlist=["AccountState"]).AccountState.ACTIVE else 1


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

    settings = get_settings()
    city = args.city or settings.target.cities[0]
    domain = args.domain or settings.email.domains[0]
    deps = _deps(settings)
    account_ids = [create_account(city, domain) for _ in range(args.count)]
    log.info("signup_batch_started", count=len(account_ids), city=city, dry_run=args.dry_run)
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

    signup = sub.add_parser("signup", help="create accounts and run the signup flow")
    signup.add_argument("--count", type=int, default=1)
    signup.add_argument("--city", default=None)
    signup.add_argument("--domain", default=None)
    signup.add_argument("--proxy", default=None)
    signup.add_argument("--concurrency", type=int, default=1)
    signup.add_argument("--dry-run", action="store_true")
    signup.set_defaults(func=cmd_signup)

    resume = sub.add_parser("resume", help="resume a crashed account from its last checkpoint")
    resume.add_argument("--account", required=True)
    resume.add_argument("--proxy", default=None)
    resume.set_defaults(func=cmd_resume)

    warm = sub.add_parser("warm", help="run warming sessions for an ACTIVE account")
    warm.add_argument("--account", required=True)
    warm.add_argument("--sessions", type=int, default=1)
    warm.add_argument("--minutes", type=int, default=12)
    warm.set_defaults(func=cmd_warm)

    schedule = sub.add_parser("schedule", help="plan and run due warming sessions")
    schedule.add_argument("--once", action="store_true", help="single pass, then exit")
    schedule.add_argument("--interval", type=int, default=300, help="seconds between passes")
    schedule.add_argument("--limit", type=int, default=8)
    schedule.add_argument("--minutes", type=int, default=8)
    schedule.set_defaults(func=cmd_schedule)

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
