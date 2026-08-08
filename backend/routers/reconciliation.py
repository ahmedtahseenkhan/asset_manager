from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.licensing.enforcement import require_module
from backend.middleware.auth import get_current_user, require_role
from backend.models.user import User
from backend.schemas.common import APIResponse
from backend.services.audit_service import AuditService
from backend.services.reconciliation_service import ReconciliationService

router = APIRouter(prefix="/reconciliation", tags=["Reconciliation"],
                   dependencies=[require_module("assets")])


class AdoptRequest(BaseModel):
    device_ids: List[int] = Field(min_length=1, max_length=500)


class LinkRequest(BaseModel):
    device_id: int
    asset_id: int


@router.get("/devices", response_model=APIResponse[List[Dict[str, Any]]])
async def unlinked_devices(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return APIResponse(data=await ReconciliationService.unlinked_devices(db))


@router.post("/adopt", response_model=APIResponse[List[Dict[str, Any]]])
async def adopt_devices(
    body: AdoptRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    manager: User = Depends(require_role("asset_manager")),
):
    created = await ReconciliationService.adopt(db, body.device_ids, manager)
    await AuditService.log(db, request, manager, "asset.adopted_from_device",
                           resource_type="asset",
                           detail={"count": len(created),
                                   "asset_tags": [a.asset_tag for a in created]})
    await db.commit()
    return APIResponse(
        data=[{"id": a.id, "asset_tag": a.asset_tag, "name": a.name} for a in created],
        message=f"Adopted {len(created)} device(s) into the asset register",
    )


@router.post("/link", response_model=APIResponse[Dict[str, Any]])
async def link_device(
    body: LinkRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    manager: User = Depends(require_role("asset_manager")),
):
    asset = await ReconciliationService.link(db, body.device_id, body.asset_id)
    await AuditService.log(db, request, manager, "asset.device_linked",
                           resource_type="asset", resource_id=asset.asset_tag,
                           detail={"device_id": body.device_id})
    await db.commit()
    return APIResponse(
        data={"asset_id": asset.id, "asset_tag": asset.asset_tag, "device_id": body.device_id},
        message=f"Device linked to {asset.asset_tag}",
    )
