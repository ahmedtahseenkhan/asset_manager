"""End of life (OS & software), warranty import, and the catalogues behind them."""
import json
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.lifecycle import eol as eol_catalog
from backend.licensing.enforcement import require_module
from backend.middleware.auth import get_current_user, require_admin, require_role
from backend.models.device import Device
from backend.models.user import User
from backend.schemas.common import APIResponse
from backend.services.audit_service import AuditService
from backend.services.lifecycle_service import LifecycleService
from backend.services.software_normalizer import CATALOG_VERSION, CATEGORIES, HIDDEN_BY_DEFAULT
from backend.services.warranty_import import DATE_ORDERS, import_warranty_csv

router = APIRouter(tags=["Lifecycle"])

_MAX_UPLOAD = 10 * 1024 * 1024


@router.get("/lifecycle/summary", response_model=APIResponse[Dict[str, Any]])
async def lifecycle_summary(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return APIResponse(data=await LifecycleService.summary(db))


@router.get("/lifecycle/devices", response_model=APIResponse[List[Dict[str, Any]]])
async def lifecycle_devices(kind: str = Query(..., pattern="^(os|software)$"), product_id: str = Query(..., max_length=64),
                            cycle: str = Query(..., max_length=64), db: AsyncSession = Depends(get_db),
                            user: User = Depends(get_current_user)):
    return APIResponse(data=await LifecycleService.devices_for(db, kind, product_id, cycle))


@router.get("/devices/{device_id}/lifecycle", response_model=APIResponse[Dict[str, Any]])
async def device_lifecycle(device_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    if await db.get(Device, device_id) is None:
        raise HTTPException(404, "Device not found")
    return APIResponse(data=await LifecycleService.device(db, device_id))


@router.get("/lifecycle/catalog", response_model=APIResponse[Dict[str, Any]])
async def lifecycle_catalog(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    info = await LifecycleService.catalog_info(db)
    return APIResponse(data={**info, "catalog": eol_catalog.current().summary(),
                             "software": {"version": CATALOG_VERSION, "categories": CATEGORIES,
                                          "hidden_by_default": HIDDEN_BY_DEFAULT}})


@router.post("/lifecycle/catalog", response_model=APIResponse[Dict[str, Any]])
async def upload_lifecycle_catalog(request: Request, file: UploadFile = File(...),
                                   db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    data = await file.read()
    if len(data) > _MAX_UPLOAD:
        raise HTTPException(400, "File too large")
    try:
        content = json.loads(data.decode("utf-8-sig"))
        cat = await LifecycleService.upload_catalog(db, content, admin.id)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(400, "Not a JSON file")
    except ValueError as exc:
        raise HTTPException(400, f"Catalogue rejected: {exc}")
    await AuditService.log(db, request, admin, "lifecycle.catalog_uploaded", resource_type="lifecycle_catalog",
                           detail={"version": cat.version, "published": cat.published.isoformat()})
    await db.commit()
    in_use, origin = await LifecycleService.load_catalog(db)
    result = await LifecycleService.refresh_all(db)
    message = (f"Catalogue {cat.version} is now in use" if origin == "uploaded" and in_use.version == cat.version
               else f"Catalogue {cat.version} saved, but the bundled catalogue {in_use.version} is newer and stays in use")
    return APIResponse(data={**await LifecycleService.catalog_info(db), "refresh": result}, message=message)


@router.post("/lifecycle/refresh", response_model=APIResponse[Dict[str, Any]])
async def refresh_lifecycle(request: Request, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    await LifecycleService.load_catalog(db)
    result = await LifecycleService.refresh_all(db)
    await AuditService.log(db, request, admin, "lifecycle.refreshed", resource_type="lifecycle_catalog", detail=result)
    await db.commit()
    return APIResponse(data=result, message="End-of-life status recalculated")


@router.post("/lifecycle/warranty-import", response_model=APIResponse[Dict[str, Any]],
             dependencies=[require_module("assets")])
async def warranty_import(request: Request, file: UploadFile = File(...), date_order: str = Form("dmy"),
                          db: AsyncSession = Depends(get_db), manager: User = Depends(require_role("asset_manager"))):
    if date_order not in DATE_ORDERS:
        raise HTTPException(400, f"date_order must be one of {', '.join(DATE_ORDERS)}")
    data = await file.read()
    if len(data) > _MAX_UPLOAD:
        raise HTTPException(400, "File too large")
    try:
        result = await import_warranty_csv(db, data, date_order)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    await AuditService.log(db, request, manager, "asset.warranty_imported", resource_type="asset",
                           detail={k: result[k] for k in ("rows", "updated", "unchanged", "device_only_count",
                                                          "not_found_count")})
    await db.commit()
    return APIResponse(data=result, message=f"Updated {result['updated']} assets' warranty dates")
