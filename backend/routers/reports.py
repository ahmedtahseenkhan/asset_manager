import csv
import io
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware.auth import get_current_user, require_role
from backend.models.asset import Asset, AssetLifecycleEvent
from backend.models.user import User
from backend.schemas.common import APIResponse
from backend.services.audit_service import AuditService
from backend.services.reports_service import ReportsService

router = APIRouter(tags=["Reports"])


# ── Reports ────────────────────────────────────────────────────────────────
@router.get("/reports/cost", response_model=APIResponse[Dict[str, Any]])
async def cost_report(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return APIResponse(data=await ReportsService.cost_summary(db))


@router.get("/reports/eol", response_model=APIResponse[Dict[str, Any]])
async def eol_report(horizon_days: int = 365, db: AsyncSession = Depends(get_db),
                     user: User = Depends(get_current_user)):
    return APIResponse(data=await ReportsService.eol_forecast(db, horizon_days))


@router.get("/reports/compliance", response_model=APIResponse[Dict[str, Any]])
async def compliance_report(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return APIResponse(data=await ReportsService.compliance_summary(db))


# ── Bulk edit ────────────────────────────────────────────────────────────
class BulkUpdate(BaseModel):
    asset_ids: List[int] = Field(min_length=1, max_length=1000)
    fields: Dict[str, Any]

_BULK_ALLOWED = {
    "criticality", "data_classification", "log_source_status", "monitoring_status",
    "backup_status", "department", "location", "network_zone", "point_of_contact",
    "compliance", "reviewer",
}


@router.post("/assets/bulk-update", response_model=APIResponse[Dict[str, int]])
async def bulk_update(
    body: BulkUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    manager: User = Depends(require_role("asset_manager")),
):
    bad = set(body.fields) - _BULK_ALLOWED
    if bad:
        raise HTTPException(400, f"Fields not allowed in bulk update: {sorted(bad)}. "
                                 f"Allowed: {sorted(_BULK_ALLOWED)}")
    assets = (await db.execute(select(Asset).where(Asset.id.in_(body.asset_ids)))).scalars().all()
    for a in assets:
        for k, v in body.fields.items():
            setattr(a, k, v or None)
    await AuditService.log(db, request, manager, "asset.bulk_updated",
                           resource_type="asset",
                           detail={"count": len(assets), "fields": sorted(body.fields)})
    await db.commit()
    return APIResponse(data={"updated": len(assets)}, message=f"Updated {len(assets)} assets")


# ── CSV asset import ──────────────────────────────────────────────────────
@router.post("/assets/import", response_model=APIResponse[Dict[str, int]])
async def import_assets(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    manager: User = Depends(require_role("asset_manager")),
):
    """Import assets from CSV. Required column: name. Optional: category, asset_type,
    serial_number, vendor, model, ip_address, os_name, criticality, department, location…"""
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(400, "File too large")
    try:
        reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
        rows = list(reader)
    except Exception as exc:
        raise HTTPException(400, f"Could not parse CSV: {exc}")

    _COLS = {"name", "category", "asset_type", "serial_number", "vendor", "model",
             "firmware_version", "ip_address", "mac_address", "os_name", "os_version",
             "network_zone", "location", "department", "point_of_contact", "criticality",
             "data_classification", "compliance", "log_source_status", "log_source_type",
             "monitoring_status", "backup_status", "reviewer", "notes"}
    created = skipped = 0
    for row in rows:
        clean = {k.strip().lower(): (v.strip() if isinstance(v, str) else v)
                 for k, v in row.items() if k}
        name = clean.get("name")
        if not name:
            skipped += 1
            continue
        vals = {k: (clean.get(k) or None) for k in _COLS if k in clean}
        vals["name"] = name
        vals.setdefault("category", clean.get("category") or "hardware")
        vals["lifecycle_state"] = "deployed"
        asset = Asset(**{k: v for k, v in vals.items()}, asset_tag="", custom_fields={},
                      created_by=manager.id)
        db.add(asset)
        await db.flush()
        asset.asset_tag = f"AST-{asset.id:05d}"
        db.add(AssetLifecycleEvent(asset_id=asset.id, from_state=None, to_state="deployed",
                                   actor_id=manager.id, note="Imported from CSV"))
        created += 1
    await AuditService.log(db, request, manager, "asset.csv_imported",
                           resource_type="asset", detail={"created": created, "skipped": skipped})
    await db.commit()
    return APIResponse(data={"created": created, "skipped": skipped},
                       message=f"Imported {created} assets ({skipped} skipped)")
