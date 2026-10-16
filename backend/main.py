import asyncio
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from backend.utils.rate_limit import limiter
from backend.utils.logging import configure_json_logging

from backend.config import settings
from backend.database import async_session, engine
from backend.scanning.runner import scan_runner
from backend.migrations import run_migrations
from backend.connectors.registry import registry
from backend.services.scheduler_service import scheduler
from backend.licensing.state import license_manager
from backend.licensing.enforcement import LicenseEnforcementMiddleware

from backend.routers import auth, devices, connectors, dashboard, admin, license as license_router, assets, reconciliation, contracts, entitlements, notifications, agents, sam, posture, reports, scanning, inventory, report_builder

configure_json_logging(debug=settings.debug)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Applying database migrations...")
    await asyncio.to_thread(run_migrations)
    logger.info("Database schema is up to date.")

    license_manager.reload()

    registry.discover_and_register()
    scheduler.start()
    interrupted = await scan_runner.recover_interrupted()
    if interrupted:
        logger.warning("Marked %d scan run(s) interrupted by the restart as failed", interrupted)
    async with async_session() as db:
        await scheduler.reload_jobs(db)

    yield

    logger.info("Shutting down...")
    scheduler.stop()
    await engine.dispose()

app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json"
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Order matters: CORS must be added LAST so it wraps license enforcement and
# 403 degradation responses still carry CORS headers.
app.add_middleware(LicenseEnforcementMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(devices.router, prefix="/api")
app.include_router(connectors.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(license_router.router, prefix="/api")
app.include_router(assets.router, prefix="/api")
app.include_router(reconciliation.router, prefix="/api")
app.include_router(contracts.router, prefix="/api")
app.include_router(entitlements.router, prefix="/api")
app.include_router(notifications.router, prefix="/api")
app.include_router(agents.router, prefix="/api")
app.include_router(sam.router, prefix="/api")
app.include_router(posture.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
app.include_router(scanning.router, prefix="/api")
app.include_router(inventory.router, prefix="/api")
app.include_router(report_builder.router, prefix="/api")

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Global Exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"data": None, "message": str(exc), "status": 500}
    )

@app.get("/api/health")
async def health_check():
    return {"data": {"status": "ok"}, "message": "API is healthy", "status": 200}

