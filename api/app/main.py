from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select

from .audit import record_audit
from .config import settings
from .database import Base, runtime
from .models import SourceScanRun, SystemSetting
from .routers import admin, audit, auth, documents, system, training
from .routers.documents import activate_due_versions
from .seed import seed_database
from .services.source_discovery import run_source_scan
from .services.training import reconcile_active_role_assignments, reconcile_assignment_sources


async def document_activation_worker() -> None:
    while True:
        await asyncio.sleep(60)
        try:
            with runtime.session() as db:
                activate_due_versions(db)
                created = reconcile_active_role_assignments(db)
                closed = reconcile_assignment_sources(db)
                if created or closed:
                    record_audit(
                        db,
                        event_type="FUTURE_JOB_ROLES_ACTIVATED",
                        actor_username="SYSTEM",
                        entity_type="TRAINING_ASSIGNMENT",
                        reason="Effective-dated job roles were reconciled",
                        metadata={
                            "assignments_created": created,
                            "assignments_closed": closed,
                        },
                    )
                    db.commit()
        except Exception:
            # Failures are retried; domain-level activation failures are written to audit by the service.
            continue


def automatic_source_scan_if_due() -> None:
    with runtime.session() as db:
        setting = db.get(SystemSetting, "source_scan_interval_minutes")
        try:
            interval = max(5, min(1440, int(setting.value if setting else "60")))
        except ValueError:
            interval = 60
        latest = db.scalar(select(SourceScanRun).order_by(SourceScanRun.started_at.desc()).limit(1))
        now = datetime.now(timezone.utc)
        if latest:
            started = (
                latest.started_at.replace(tzinfo=timezone.utc)
                if latest.started_at.tzinfo is None
                else latest.started_at
            )
            if started + timedelta(minutes=interval) > now:
                return
        try:
            scan = run_source_scan(db, trigger="AUTOMATIC", requested_by=None)
        except Exception as exc:
            record_audit(
                db,
                event_type="CONTROLLED_SOURCE_SCAN_FAILED",
                actor_username="SYSTEM",
                entity_type="SOURCE_SCAN",
                success=False,
                reason="Scheduled recursive controlled-source discovery",
                metadata={"error": str(exc)},
            )
            db.commit()
            return
        record_audit(
            db,
            event_type="CONTROLLED_SOURCE_SCAN_COMPLETED",
            actor_username="SYSTEM",
            entity_type="SOURCE_SCAN",
            entity_id=scan.id,
            reason="Scheduled recursive controlled-source discovery",
            after={"status": scan.status, "counts": scan.counts_json},
        )
        db.commit()


async def source_scan_worker() -> None:
    await asyncio.sleep(60)
    while True:
        try:
            await asyncio.to_thread(automatic_source_scan_if_due)
        except Exception:
            pass
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.app_env.lower() != "production":
        Base.metadata.create_all(runtime.engine)
    with runtime.session() as db:
        seed_database(db)
    worker = asyncio.create_task(document_activation_worker())
    scan_worker = asyncio.create_task(source_scan_worker())
    yield
    worker.cancel()
    scan_worker.cancel()
    with suppress(asyncio.CancelledError):
        await worker
    with suppress(asyncio.CancelledError):
        await scan_worker


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    docs_url="/api/docs" if settings.app_env.lower() != "production" else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if settings.app_env.lower() != "production" else None,
    lifespan=lifespan,
)

if settings.app_env.lower() != "production":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.middleware("http")
async def request_controls(request: Request, call_next):
    request.state.request_id = request.headers.get("x-request-id", str(uuid.uuid4()))[:36]
    path = request.url.path
    if request.method not in {"GET", "HEAD", "OPTIONS"} and not (
        path.startswith("/api/auth/") or path.startswith("/api/admin/system/")
    ):
        try:
            with runtime.session() as db:
                maintenance = db.get(SystemSetting, "maintenance_mode")
                if maintenance and maintenance.value.lower() == "true":
                    return JSONResponse(
                        status_code=503,
                        content={"detail": "The system is in controlled maintenance mode; write operations are paused"},
                    )
        except Exception:
            return JSONResponse(
                status_code=503,
                content={"detail": "Unable to verify system operating mode; write operation was blocked"},
            )
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/health", tags=["Health"])
def health():
    try:
        with runtime.engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
        database = "ok"
    except Exception:
        database = "unavailable"
    status_code = 200 if database == "ok" else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ok" if database == "ok" else "degraded",
            "application": settings.app_name,
            "version": settings.app_version,
            "database": database,
        },
    )


app.include_router(auth.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(training.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(audit.router, prefix="/api")
app.include_router(system.router, prefix="/api")
