import csv
import io
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware.auth import get_current_user, require_role
from backend.models.user import User
from backend.models.vulnerability import Vulnerability
from backend.schemas.common import APIResponse
from backend.services.audit_service import AuditService
from backend.services.cmdb_audit_service import CMDBAuditService
from backend.services.posture_service import PostureService

router = APIRouter(tags=["Posture / CAASM"])


# ── CMDB health audit (Phase 3) ───────────────────────────────────────────
@router.get("/cmdb/audit", response_model=APIResponse[Dict[str, Any]])
async def cmdb_audit(
    stale_days: int = 30,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return APIResponse(data=await CMDBAuditService.run(db, stale_days=stale_days))


# ── Vulnerabilities (Phase 4) ─────────────────────────────────────────────
@router.post("/vulnerabilities/import", response_model=APIResponse[Dict[str, int]])
async def import_vulns(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    manager: User = Depends(require_role("asset_manager")),
):
    """Import a scanner CSV. Columns: cve, title, severity, cvss, asset_tag|ip, detected_on."""
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(400, "File too large")
    try:
        reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
        rows = [{k.strip().lower(): v for k, v in r.items()} for r in reader]
    except Exception as exc:
        raise HTTPException(400, f"Could not parse CSV: {exc}")
    if not rows:
        raise HTTPException(400, "No rows found in file")
    result = await PostureService.import_vulnerabilities(db, rows)
    await AuditService.log(db, request, manager, "vulnerability.imported",
                           resource_type="vulnerability", detail=result)
    await db.commit()
    return APIResponse(data=result, message=f"Imported {result['imported']} findings")


@router.get("/vulnerabilities/summary", response_model=APIResponse[Dict[str, Any]])
async def vuln_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return APIResponse(data=await PostureService.vulnerability_summary(db))


@router.get("/assets/{asset_id}/vulnerabilities", response_model=APIResponse[List[Dict[str, Any]]])
async def asset_vulns(
    asset_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (await db.execute(
        select(Vulnerability).where(Vulnerability.asset_id == asset_id)
        .order_by(Vulnerability.severity)
    )).scalars().all()
    return APIResponse(data=[
        {"id": v.id, "cve_id": v.cve_id, "title": v.title, "severity": v.severity,
         "cvss": v.cvss, "status": v.status, "detected_on": v.detected_on}
        for v in rows
    ])


# ── Posture summary + log-source coverage (Phase 4) ───────────────────────
@router.get("/posture/summary", response_model=APIResponse[Dict[str, Any]])
async def posture_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return APIResponse(data=await PostureService.summary(db))


@router.get("/posture/log-coverage", response_model=APIResponse[Dict[str, Any]])
async def log_coverage(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return APIResponse(data=await PostureService.log_source_coverage(db))
