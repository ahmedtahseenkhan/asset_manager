"""
Report builder API (licence module: reporting).

Any signed-in user can run reports and save their own; saved reports are
private unless shared. Only the owner or an admin may change or delete one.
Scheduled email delivery sends data to arbitrary addresses, so it is admin-only.
"""
import re
from typing import Any, Dict, List, Literal, Optional

from apscheduler.triggers.cron import CronTrigger
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.licensing.enforcement import require_module
from backend.licensing.state import license_manager
from backend.middleware.auth import get_current_user
from backend.models.saved_report import SavedReport
from backend.models.user import User
from backend.reporting import engine
from backend.reporting.engine import ReportDefinition, ReportError
from backend.reporting.entities import ENTITIES, catalog
from backend.reporting.library import LIBRARY
from backend.reporting.service import build_file, describe, send_report
from backend.schemas.common import APIResponse
from backend.services.audit_service import AuditService
from backend.services.scheduler_service import scheduler

router = APIRouter(prefix="/reports", tags=["Report builder"], dependencies=[require_module("reporting")])

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _modules() -> Optional[List[str]]:
    info = license_manager.current
    return info.claims.get("modules", []) if info.is_operational else None


def _checked(defn: ReportDefinition) -> ReportDefinition:
    """Validate a definition fully (compile it) and enforce entity licensing."""
    try:
        engine.check_licence(defn, _modules())
        if defn.group_by:
            engine.compile_groups(defn)
        else:
            engine.compile_rows(defn)
        engine.compile_count(defn)
    except ReportError as exc:
        raise HTTPException(400, str(exc))
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    return defn


def _is_admin(user: User) -> bool:
    return user.role == "admin"


# ── catalog & library ──────────────────────────────────────────────────────
@router.get("/catalog", response_model=APIResponse[Dict[str, Any]])
async def report_catalog(user: User = Depends(get_current_user)):
    return APIResponse(data={"entities": catalog(_modules()), "operators": engine.operator_catalog()})


@router.get("/library", response_model=APIResponse[List[Dict[str, Any]]])
async def report_library(user: User = Depends(get_current_user)):
    modules = _modules()
    out = []
    for r in LIBRARY:
        e = ENTITIES[r["definition"]["entity"]]
        out.append({**r, "licensed": e.module is None or modules is None or e.module in modules})
    return APIResponse(data=out)


# ── ad-hoc run / export ────────────────────────────────────────────────────
class RunIn(BaseModel):
    definition: ReportDefinition
    page: int = Field(default=1, ge=1)
    size: int = Field(default=100, ge=1, le=engine.MAX_PAGE_SIZE)


class ExportIn(BaseModel):
    definition: ReportDefinition
    name: str = Field(default="Report", max_length=255)
    format: Literal["xlsx", "csv"] = "xlsx"


def _file_response(fname: str, content: bytes, mime: str) -> Response:
    return Response(content, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.post("/run", response_model=APIResponse[Dict[str, Any]])
async def run_report(body: RunIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    defn = _checked(body.definition)
    return APIResponse(data={**await engine.run(db, defn, body.page, body.size), "summary": describe(defn)})


@router.post("/export")
async def export_report(body: ExportIn, request: Request, db: AsyncSession = Depends(get_db),
                        user: User = Depends(get_current_user)):
    defn = _checked(body.definition)
    fname, content, mime, count = await build_file(db, body.name, defn, body.format)
    await AuditService.log(db, request, user, "report.exported", resource_type="report",
                           detail={"name": body.name, "entity": defn.entity, "rows": count, "format": body.format})
    await db.commit()
    return _file_response(fname, content, mime)


# ── saved reports ──────────────────────────────────────────────────────────
class SavedIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)
    definition: ReportDefinition
    shared: bool = False
    pinned: bool = False


class SavedUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)
    definition: Optional[ReportDefinition] = None
    shared: Optional[bool] = None
    pinned: Optional[bool] = None
    # scheduling (admin only)
    schedule_cron: Optional[str] = None
    clear_schedule: bool = False
    recipients: Optional[List[str]] = None
    export_format: Optional[Literal["xlsx", "csv"]] = None


def _view(r: SavedReport, user: User) -> Dict[str, Any]:
    return {
        "id": r.id, "name": r.name, "description": r.description, "definition": r.definition,
        "owner_id": r.owner_id, "shared": r.shared, "pinned": r.pinned,
        "can_edit": r.owner_id == user.id or _is_admin(user),
        "schedule_cron": r.schedule_cron, "recipients": r.recipients or [], "export_format": r.export_format,
        "last_sent_at": r.last_sent_at, "last_status": r.last_status,
        "created_at": r.created_at, "updated_at": r.updated_at,
    }


def _visible(user: User):
    """Own and shared reports; administrators see all (they manage schedules)."""
    if _is_admin(user):
        return true()
    return or_(SavedReport.owner_id == user.id, SavedReport.shared.is_(True))


async def _get_visible(db: AsyncSession, report_id: int, user: User) -> SavedReport:
    r = (await db.execute(select(SavedReport).where(SavedReport.id == report_id, _visible(user)))).scalars().first()
    if r is None:
        raise HTTPException(404, "Report not found")
    return r


async def _get_editable(db: AsyncSession, report_id: int, user: User) -> SavedReport:
    r = await _get_visible(db, report_id, user)
    if r.owner_id != user.id and not _is_admin(user):
        raise HTTPException(403, "Only the report's owner or an administrator can change it")
    return r


def _definition_of(r: SavedReport) -> ReportDefinition:
    try:
        return _checked(ReportDefinition.model_validate(r.definition))
    except ValidationError as exc:
        raise HTTPException(400, f"Saved definition is invalid: {exc.errors()[0]['msg']}")


@router.get("/saved", response_model=APIResponse[List[Dict[str, Any]]])
async def list_saved(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (await db.execute(select(SavedReport).where(_visible(user)).order_by(SavedReport.name))).scalars().all()
    return APIResponse(data=[_view(r, user) for r in rows])


@router.post("/saved", response_model=APIResponse[Dict[str, Any]])
async def create_saved(body: SavedIn, request: Request, db: AsyncSession = Depends(get_db),
                       user: User = Depends(get_current_user)):
    defn = _checked(body.definition)
    r = SavedReport(name=body.name.strip(), description=body.description, definition=defn.model_dump(),
                    owner_id=user.id, shared=body.shared, pinned=body.pinned, recipients=[])
    db.add(r)
    await db.flush()
    await AuditService.log(db, request, user, "report.saved", resource_type="saved_report", resource_id=str(r.id),
                           detail={"name": r.name, "entity": defn.entity, "shared": r.shared})
    await db.commit()
    await db.refresh(r)
    return APIResponse(data=_view(r, user), message="Report saved")


@router.get("/saved/{report_id}", response_model=APIResponse[Dict[str, Any]])
async def get_saved(report_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return APIResponse(data=_view(await _get_visible(db, report_id, user), user))


@router.patch("/saved/{report_id}", response_model=APIResponse[Dict[str, Any]])
async def update_saved(report_id: int, body: SavedUpdate, request: Request, db: AsyncSession = Depends(get_db),
                       user: User = Depends(get_current_user)):
    r = await _get_editable(db, report_id, user)
    scheduling = body.clear_schedule or any(v is not None for v in (body.schedule_cron, body.recipients,
                                                                     body.export_format))
    if scheduling and not _is_admin(user):
        raise HTTPException(403, "Only administrators can schedule report emails")
    if body.definition is not None:
        r.definition = _checked(body.definition).model_dump()
    for f in ("name", "description", "shared", "pinned", "export_format"):
        v = getattr(body, f)
        if v is not None:
            setattr(r, f, v.strip() if isinstance(v, str) and f == "name" else v)
    if body.recipients is not None:
        bad = [a for a in body.recipients if not _EMAIL.match(a.strip())]
        if bad:
            raise HTTPException(400, f"Not an email address: {', '.join(bad[:3])}")
        if len(body.recipients) > 50:
            raise HTTPException(400, "At most 50 recipients")
        r.recipients = sorted({a.strip() for a in body.recipients})
    if body.clear_schedule:
        r.schedule_cron = None
    elif body.schedule_cron is not None:
        cron = body.schedule_cron.strip()
        try:
            CronTrigger.from_crontab(cron)
        except ValueError as exc:
            raise HTTPException(400, f"Invalid schedule {cron!r}: {exc}")
        if not (r.recipients or []):
            raise HTTPException(400, "Add at least one recipient before scheduling")
        r.schedule_cron = cron
    await AuditService.log(db, request, user, "report.updated", resource_type="saved_report", resource_id=str(r.id),
                           detail=body.model_dump(exclude_none=True, exclude={"definition", "clear_schedule"}))
    await db.commit()
    await db.refresh(r)
    if scheduling:
        await scheduler.reload_jobs(db)
    return APIResponse(data=_view(r, user), message="Report updated")


@router.delete("/saved/{report_id}", response_model=APIResponse[bool])
async def delete_saved(report_id: int, request: Request, db: AsyncSession = Depends(get_db),
                       user: User = Depends(get_current_user)):
    r = await _get_editable(db, report_id, user)
    scheduled = r.schedule_cron is not None
    await db.delete(r)
    await AuditService.log(db, request, user, "report.deleted", resource_type="saved_report",
                           resource_id=str(report_id), detail={"name": r.name})
    await db.commit()
    if scheduled:
        await scheduler.reload_jobs(db)
    return APIResponse(data=True, message="Report deleted")


@router.post("/saved/{report_id}/run", response_model=APIResponse[Dict[str, Any]])
async def run_saved(report_id: int, page: int = 1, size: int = 100, db: AsyncSession = Depends(get_db),
                    user: User = Depends(get_current_user)):
    r = await _get_visible(db, report_id, user)
    defn = _definition_of(r)
    return APIResponse(data={**await engine.run(db, defn, page, min(size, engine.MAX_PAGE_SIZE)),
                             "summary": describe(defn)})


@router.get("/saved/{report_id}/export")
async def export_saved(report_id: int, request: Request, format: Literal["xlsx", "csv"] = "xlsx",
                       db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    r = await _get_visible(db, report_id, user)
    fname, content, mime, count = await build_file(db, r.name, _definition_of(r), format)
    await AuditService.log(db, request, user, "report.exported", resource_type="saved_report",
                           resource_id=str(r.id), detail={"name": r.name, "rows": count, "format": format})
    await db.commit()
    return _file_response(fname, content, mime)


@router.post("/saved/{report_id}/send", response_model=APIResponse[str])
async def send_saved_now(report_id: int, request: Request, db: AsyncSession = Depends(get_db),
                         user: User = Depends(get_current_user)):
    if not _is_admin(user):
        raise HTTPException(403, "Only administrators can email reports")
    r = await _get_visible(db, report_id, user)
    _definition_of(r)
    if not r.recipients:
        raise HTTPException(400, "Add at least one recipient first")
    line = await send_report(db, r)
    await AuditService.log(db, request, user, "report.sent", resource_type="saved_report", resource_id=str(r.id),
                           detail={"name": r.name, "result": line})
    await db.commit()
    return APIResponse(data=line, message=line)


@router.get("/pinned", response_model=APIResponse[List[Dict[str, Any]]])
async def pinned_reports(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Pinned reports with a small result each, for the dashboard."""
    rows = (await db.execute(select(SavedReport).where(_visible(user), SavedReport.pinned.is_(True))
                             .order_by(SavedReport.name).limit(12))).scalars().all()
    out = []
    for r in rows:
        try:
            defn = _definition_of(r)
            result = await engine.run(db, defn, 1, 5)
            if result["kind"] == "groups":
                result["groups"] = result["groups"][:8]
        except HTTPException as exc:
            result = {"kind": "error", "message": exc.detail}
        out.append({"id": r.id, "name": r.name, "chart": (r.definition or {}).get("chart", "none"), "result": result})
    return APIResponse(data=out)

