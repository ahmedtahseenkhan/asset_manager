import secrets
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware.auth import get_current_user, require_admin
from backend.models.agent import AgentToken
from backend.models.software import InstalledSoftware
from backend.models.user import User
from backend.schemas.common import APIResponse
from backend.models.device import Device
from backend.models.device_source import DeviceSource
from backend.models.inventory import DeviceInventory
from backend.services.agent_service import (
    AGENT_SOURCE, LATEST_AGENT_VERSION, AgentService, is_outdated, parse_agent_report,
)
from backend.services.audit_service import AuditService

router = APIRouter(tags=["Agents"])


# ── Agent report ingestion (token-authenticated, not JWT) ─────────────────
@router.post("/ingest/agent", response_model=APIResponse[Dict[str, Any]])
async def ingest_agent(
    payload: Dict[str, Any] = Body(...),
    x_agent_token: str = Header(default=""),
    db: AsyncSession = Depends(get_db),
):
    token_row = await AgentService.validate_token(db, x_agent_token)
    if not token_row:
        raise HTTPException(401, "Invalid or inactive agent token")
    try:
        report = parse_agent_report(payload)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_url=False, include_input=False))
    result = await AgentService.ingest(db, token_row, report)
    return APIResponse(data=result, message="Inventory received")


# ── Token management (admin) ──────────────────────────────────────────────
class TokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


@router.get("/agents/tokens", response_model=APIResponse[List[Dict[str, Any]]])
async def list_tokens(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    rows = (await db.execute(select(AgentToken).order_by(AgentToken.id.desc()))).scalars().all()
    return APIResponse(data=[
        {"id": t.id, "name": t.name, "active": t.active,
         "token_hint": f"…{t.token[-6:]}", "reports_count": t.reports_count,
         "last_used_at": t.last_used_at, "created_at": t.created_at}
        for t in rows
    ])


@router.post("/agents/tokens", response_model=APIResponse[Dict[str, Any]])
async def create_token(
    body: TokenCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    token = secrets.token_urlsafe(32)
    row = AgentToken(token=token, name=body.name, created_by=admin.id)
    db.add(row)
    await AuditService.log(db, request, admin, "agent.token_created",
                           resource_type="agent_token", detail={"name": body.name})
    await db.commit()
    # Full token returned once, at creation time only.
    return APIResponse(data={"id": row.id, "name": row.name, "token": token},
                       message="Token created — copy it now, it won't be shown again")


@router.patch("/agents/tokens/{token_id}", response_model=APIResponse[bool])
async def toggle_token(
    token_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    row = (await db.execute(select(AgentToken).where(AgentToken.id == token_id))).scalars().first()
    if not row:
        raise HTTPException(404, "Token not found")
    row.active = not row.active
    await AuditService.log(db, request, admin, "agent.token_toggled",
                           resource_type="agent_token", resource_id=str(token_id),
                           detail={"active": row.active})
    await db.commit()
    return APIResponse(data=row.active, message="Token updated")


# ── Software inventory (read) ─────────────────────────────────────────────
@router.get("/devices/{device_id}/software", response_model=APIResponse[List[Dict[str, Any]]])
async def device_software(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (await db.execute(
        select(InstalledSoftware).where(InstalledSoftware.device_id == device_id)
        .order_by(InstalledSoftware.name)
    )).scalars().all()
    return APIResponse(data=[
        {"id": s.id, "name": s.name, "normalized_name": s.normalized_name,
         "version": s.version, "publisher": s.publisher}
        for s in rows
    ])


# ── Fleet view (admin) ────────────────────────────────────────────────────
@router.get("/agents/fleet", response_model=APIResponse[Dict[str, Any]])
async def agent_fleet(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    rows = (await db.execute(
        select(Device, DeviceSource.last_synced, DeviceInventory.collector_version, DeviceInventory.os_name)
        .join(DeviceSource, (DeviceSource.device_id == Device.id) & (DeviceSource.source_name == AGENT_SOURCE))
        .outerjoin(DeviceInventory, DeviceInventory.device_id == Device.id)
        .order_by(DeviceSource.last_synced.desc())
    )).all()
    return APIResponse(data={
        "latest_version": LATEST_AGENT_VERSION,
        "agents": [{
            "device_id": d.id, "hostname": d.hostname, "status": d.status,
            "os_name": os_name or d.os_name, "version": version, "outdated": is_outdated(version),
            "last_report": last,
        } for d, last, version, os_name in rows],
    })


# ── Agent script downloads (unauthenticated: endpoints fetch these while
#    installing; the scripts hold no secrets) ──────────────────────────────
_AGENT_DIR = Path(__file__).resolve().parents[2] / "agent"
_DOWNLOADS = {"itam_agent.ps1", "itam_agent.py", "install_agent.ps1", "install_agent.sh"}


@router.get("/agents/download/{filename}", response_class=PlainTextResponse)
async def download_agent_file(filename: str):
    path = _AGENT_DIR / filename
    if filename not in _DOWNLOADS or not path.is_file():
        raise HTTPException(404, "No such agent file")
    return PlainTextResponse(path.read_text(encoding="utf-8"),
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})
