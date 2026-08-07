from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.licensing.enforcement import check_asset_limit, require_module
from backend.middleware.auth import get_current_user, require_admin, require_role
from backend.models.user import User
from backend.schemas.asset import (
    AssetCreate,
    AssetDetailOut,
    AssetListOut,
    AssetOut,
    AssetUpdate,
    LifecycleTransition,
)
from backend.schemas.common import APIResponse
from backend.services.asset_service import AssetService
from backend.services.audit_service import AuditService

router = APIRouter(prefix="/assets", tags=["Assets"], dependencies=[require_module("assets")])


@router.get("", response_model=APIResponse[AssetListOut])
async def list_assets(
    page: int = 1,
    size: int = 50,
    search: Optional[str] = None,
    category: Optional[str] = None,
    lifecycle_state: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    page, size = max(1, page), min(max(1, size), 200)
    total, items = await AssetService.list_assets(
        db, page=page, size=size, search=search,
        category=category, lifecycle_state=lifecycle_state,
    )
    return APIResponse(data={"items": items, "total": total, "page": page, "size": size})


@router.get("/{asset_id}", response_model=APIResponse[AssetDetailOut])
async def get_asset(
    asset_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    asset = await AssetService.get_asset(db, asset_id)
    return APIResponse(data=AssetService.serialize_detail(asset))


@router.post("", response_model=APIResponse[AssetOut])
async def create_asset(
    asset_in: AssetCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    manager: User = Depends(require_role("asset_manager")),
):
    await check_asset_limit(db)
    asset = await AssetService.create_asset(db, asset_in, manager)
    await AuditService.log(db, request, manager, "asset.created",
                           resource_type="asset", resource_id=asset.asset_tag,
                           detail={"name": asset.name, "category": asset.category})
    await db.commit()
    return APIResponse(data=AssetService.serialize_detail(asset), message="Asset created")


@router.patch("/{asset_id}", response_model=APIResponse[AssetOut])
async def update_asset(
    asset_id: int,
    asset_in: AssetUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    manager: User = Depends(require_role("asset_manager")),
):
    changes = asset_in.model_dump(exclude_unset=True)
    asset = await AssetService.update_asset(db, asset_id, asset_in)
    await AuditService.log(db, request, manager, "asset.updated",
                           resource_type="asset", resource_id=asset.asset_tag,
                           detail={"changed_fields": sorted(changes.keys())})
    await db.commit()
    return APIResponse(data=AssetService.serialize_detail(asset), message="Asset updated")


@router.post("/{asset_id}/transition", response_model=APIResponse[AssetDetailOut])
async def transition_asset(
    asset_id: int,
    body: LifecycleTransition,
    request: Request,
    db: AsyncSession = Depends(get_db),
    manager: User = Depends(require_role("asset_manager")),
):
    asset = await AssetService.transition(db, asset_id, body.to_state, manager, body.note)
    await AuditService.log(db, request, manager, "asset.lifecycle_transition",
                           resource_type="asset", resource_id=asset.asset_tag,
                           detail={"to_state": body.to_state, "note": body.note})
    await db.commit()
    return APIResponse(data=AssetService.serialize_detail(asset), message="State updated")


@router.delete("/{asset_id}", response_model=APIResponse[bool])
async def delete_asset(
    asset_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    asset = await AssetService.get_asset(db, asset_id)
    tag, name = asset.asset_tag, asset.name
    await AssetService.delete_asset(db, asset_id)
    await AuditService.log(db, request, admin, "asset.deleted",
                           resource_type="asset", resource_id=tag,
                           detail={"name": name})
    await db.commit()
    return APIResponse(data=True, message="Asset deleted")
