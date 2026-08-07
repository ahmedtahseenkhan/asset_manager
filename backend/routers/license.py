import hashlib
from typing import Any, Dict

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.licensing.state import license_manager
from backend.licensing.verifier import LicenseError, evaluate, verify_license_bytes
from backend.middleware.auth import get_current_user, require_admin
from backend.models.app_license import AppLicenseActivation
from backend.models.user import User
from backend.schemas.common import APIResponse
from backend.services.audit_service import AuditService

router = APIRouter(prefix="/license", tags=["License"])

_MAX_LICENSE_SIZE = 64 * 1024  # a license file is ~1 KB; anything big is not a license


@router.get("/status", response_model=APIResponse[Dict[str, Any]])
async def license_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    info = license_manager.current
    usage = {}
    if info.claims:
        user_count = (await db.scalar(select(func.count(User.id)))) or 0
        try:
            from backend.models.asset import Asset
            asset_count = (await db.scalar(select(func.count(Asset.id)))) or 0
        except ImportError:  # asset module not yet deployed
            asset_count = 0
        usage = {"users": user_count, "assets": asset_count}

    claims = info.claims or {}
    return APIResponse(data={
        "status": info.status.value,
        "operational": info.is_operational,
        "reason": info.reason,
        "customer": claims.get("customer"),
        "license_id": claims.get("license_id"),
        "issued_at": claims.get("issued_at"),
        "expires_at": claims.get("expires_at"),
        "grace_days": claims.get("grace_days"),
        "max_assets": claims.get("max_assets"),
        "max_users": claims.get("max_users"),
        "modules": claims.get("modules", []),
        "usage": usage,
    })


@router.post("/upload", response_model=APIResponse[Dict[str, Any]])
async def upload_license(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    data = await file.read()
    if len(data) > _MAX_LICENSE_SIZE:
        raise HTTPException(400, "File too large to be a license file")

    # Verify BEFORE writing anything to disk.
    try:
        claims = verify_license_bytes(data)
    except LicenseError as exc:
        await AuditService.log(db, request, admin, "license.upload_rejected",
                               resource_type="license", detail={"reason": str(exc)})
        raise HTTPException(400, f"License rejected: {exc}")

    info = evaluate(claims)
    if not info.is_operational:
        await AuditService.log(db, request, admin, "license.upload_rejected",
                               resource_type="license",
                               resource_id=claims.get("license_id"),
                               detail={"reason": info.reason})
        raise HTTPException(400, f"License rejected: {info.reason}")

    # Persist atomically: write sibling temp file, then replace.
    path = license_manager.path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".lic.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    license_manager.reload()

    db.add(AppLicenseActivation(
        license_id=claims["license_id"],
        payload=claims,
        file_sha256=hashlib.sha256(data).hexdigest(),
        activated_by=admin.id,
    ))
    await AuditService.log(db, request, admin, "license.activated",
                           resource_type="license", resource_id=claims["license_id"],
                           detail={"customer": claims["customer"],
                                   "expires_at": claims["expires_at"]})
    await db.commit()

    return APIResponse(
        data={"status": license_manager.current.status.value, "customer": claims["customer"],
              "expires_at": claims["expires_at"]},
        message="License activated",
    )
