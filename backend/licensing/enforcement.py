"""
License enforcement: ASGI middleware for graceful degradation + FastAPI
dependencies for module gating and seat/asset limits.

Degradation model
-----------------
- VALID / GRACE  -> everything works (GRACE adds an X-License-Warning header)
- EXPIRED / INVALID / MISSING:
    * reads (GET/HEAD/OPTIONS) still work, so admins can see data and status
    * writes are blocked with 403, EXCEPT auth (login) and license upload,
      so an admin can always sign in and install a fresh license — even air-gapped.
"""
from __future__ import annotations

from typing import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from backend.database import get_db
from backend.licensing.state import license_manager
from backend.licensing.verifier import LicenseStatus

# Writes to these prefixes must always work, or a customer could never recover.
_EXEMPT_PREFIXES = ("/api/auth", "/api/license", "/api/health")
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class LicenseEnforcementMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):
        info = license_manager.current
        if not info.is_operational:
            path = request.url.path
            if (
                path.startswith("/api")
                and request.method not in _SAFE_METHODS
                and not path.startswith(_EXEMPT_PREFIXES)
            ):
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={
                        "data": None,
                        "message": f"License {info.status.value}: {info.reason}. "
                                   "Write operations are disabled until a valid license is installed.",
                        "status": 403,
                    },
                )
        response = await call_next(request)
        if license_manager.current.status is LicenseStatus.GRACE:
            response.headers["X-License-Warning"] = license_manager.current.reason
        return response


def require_module(module: str):
    """Router-level dependency: gate an entire feature module by license."""
    def _check() -> None:
        info = license_manager.current
        # When the license is non-operational the middleware already blocks all
        # writes; reads stay available (degradation model), so don't gate here.
        if info.is_operational and module not in info.claims.get("modules", []):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"The '{module}' module is not enabled in your license",
            )
    return Depends(_check)


async def check_asset_limit(db: AsyncSession) -> None:
    """Call before creating an asset; raises 403 when the licensed cap is reached."""
    from backend.models.asset import Asset  # local import to avoid cycles

    info = license_manager.current
    max_assets = int(info.claims.get("max_assets", 0)) if info.is_operational else 0
    count = (await db.scalar(select(func.count(Asset.id)))) or 0
    if count >= max_assets:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"License limit reached: max_assets={max_assets}. "
            "Contact your vendor to upgrade the license.",
        )


async def check_user_limit(db: AsyncSession) -> None:
    """Call before creating a user; raises 403 when the licensed cap is reached."""
    from backend.models.user import User

    info = license_manager.current
    max_users = int(info.claims.get("max_users", 0)) if info.is_operational else 0
    count = (await db.scalar(select(func.count(User.id)))) or 0
    if count >= max_users:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"License limit reached: max_users={max_users}. "
            "Contact your vendor to upgrade the license.",
        )
