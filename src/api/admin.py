"""Minimal admin API. Binds 127.0.0.1 and requires a bearer token (section 14)."""

from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import Response

from api.schemas import HealthResponse, ReportResponse, SignupRequest
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

    return app


app = create_app()
