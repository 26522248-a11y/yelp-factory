"""Minimal admin API. Binds 127.0.0.1 and requires a bearer token (section 14)."""

from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from api.schemas import HealthResponse, PoolImportRequest, ReportResponse, SignupRequest
from core.config import get_settings
from core.governor import Governor
from core.report import build_report, recent_events
from db.session import session_scope
from obs.log import get_logger
from obs.metrics import active_profiles

log = get_logger("api.admin")


def _auth(request: Request) -> None:
    expected = get_settings().admin_token
    if not expected:
        raise HTTPException(status_code=503, detail="admin token not configured")
    header = request.headers.get("authorization", "")
    if header != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="unauthorized")


def create_app() -> FastAPI:
    app = FastAPI(title="Yelp Factory Admin", version="0.1.0", docs_url=None, redoc_url=None)
    governor = Governor(
        max_profiles=get_settings().concurrency.max_profiles,
        ram_guard_pct=get_settings().concurrency.ram_guard_pct,
        workers=get_settings().concurrency.workers,
    )

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        ok_db = True
        try:
            with session_scope():
                pass
        except Exception:  # noqa: BLE001
            ok_db = False
        return HealthResponse(status="ok" if ok_db else "degraded", db=ok_db, active_profiles=governor.active)

    @app.get("/report", response_model=ReportResponse, dependencies=[Depends(_auth)])
    def report(since: str = "24h") -> ReportResponse:
        return ReportResponse(**build_report(since))

    @app.get("/events", dependencies=[Depends(_auth)])
    def events(limit: int = 100, code: str | None = None):
        return recent_events(limit=limit, code=code)

    @app.post("/signup", dependencies=[Depends(_auth)])
    def signup(payload: SignupRequest):
        # Actual execution is done by workers; this only records intent.
        log.info("signup_requested", count=payload.count, city=payload.city, dry_run=payload.dry_run)
        return {"accepted": payload.count, "city": payload.city, "dry_run": payload.dry_run}

    @app.get("/metrics")
    def metrics():
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    # ------------------------------------------------------------------ pools (spec v1.1)

    @app.get("/api/pool", dependencies=[Depends(_auth)])
    def pool_stats():
        from core.pool import stats

        return stats()

    @app.post("/api/pool/import", dependencies=[Depends(_auth)])
    def pool_import(payload: PoolImportRequest):
        from core.importers import parse_emails, parse_proxies
        from core.pool import import_emails, import_proxies
        from db.models import EmailPool, ProxyPool
        from db.session import session_scope

        settings = get_settings()
        with session_scope() as session:
            if payload.kind == "emails":
                existing = {row.mailbox_email for row in session.query(EmailPool).all()} | {
                    row.alias for row in session.query(EmailPool).all()
                }
            elif payload.kind == "proxies":
                existing = {row.raw for row in session.query(ProxyPool).all()}
            else:
                raise HTTPException(status_code=400, detail="kind must be emails|proxies")

        if payload.kind == "emails":
            report = parse_emails(
                payload.text,
                default_client_id=settings.email.graph_client_id,
                default_domain=settings.email.domains[0],
                existing=existing,
            )
            if not payload.dry_run and report.rows:
                import_emails(report.rows, source_file="api")
        else:
            report = parse_proxies(payload.text, existing=existing)
            if not payload.dry_run and report.rows:
                import_proxies(report.rows, source_file="api")

        return {
            "kind": payload.kind,
            "total": report.total,
            "valid": len(report.rows),
            "duplicates": report.duplicates,
            "invalid": len(report.errors),
            "errors": [
                {"line": error.line, "reason": error.reason, "row": error.raw} for error in report.errors
            ],
            "dry_run": payload.dry_run,
        }

    return app


app = create_app()
