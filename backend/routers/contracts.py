from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database import get_db
from backend.licensing.enforcement import require_module
from backend.middleware.auth import get_current_user, require_admin, require_role
from backend.models.asset import Asset
from backend.models.contract import Contract, contract_assets
from backend.models.user import User
from backend.schemas.common import APIResponse
from backend.schemas.contract import (
    AttachAssetRequest,
    ContractCreate,
    ContractDetailOut,
    ContractListOut,
    ContractOut,
    ContractUpdate,
)
from backend.services.audit_service import AuditService

router = APIRouter(prefix="/contracts", tags=["Contracts"],
                   dependencies=[require_module("contracts")])

_FIELDS = ("id", "name", "contract_type", "vendor", "reference_no", "start_date",
           "end_date", "notice_days", "cost", "currency", "auto_renews",
           "custom_fields", "created_at", "updated_at")


def _serialize(c: Contract) -> dict:
    return {**{f: getattr(c, f) for f in _FIELDS}, "asset_count": len(c.assets)}


def _serialize_detail(c: Contract) -> dict:
    return {
        **_serialize(c),
        "assets": [
            {"id": a.id, "asset_tag": a.asset_tag, "name": a.name,
             "category": a.category, "lifecycle_state": a.lifecycle_state}
            for a in c.assets
        ],
        "entitlements": [
            {"id": e.id, "product": e.product, "license_model": e.license_model,
             "seats_purchased": e.seats_purchased, "expires_on": e.expires_on}
            for e in c.entitlements
        ],
    }


async def _get_contract(db: AsyncSession, contract_id: int) -> Contract:
    contract = (await db.execute(
        select(Contract)
        .options(selectinload(Contract.entitlements))
        .where(Contract.id == contract_id)
        .execution_options(populate_existing=True)
    )).scalars().first()
    if not contract:
        raise HTTPException(404, "Contract not found")
    return contract


@router.get("", response_model=APIResponse[ContractListOut])
async def list_contracts(
    page: int = 1,
    size: int = 50,
    search: Optional[str] = None,
    contract_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    page, size = max(1, page), min(max(1, size), 200)
    query = select(Contract)
    if search:
        term = f"%{search}%"
        query = query.where(or_(
            Contract.name.ilike(term),
            Contract.vendor.ilike(term),
            Contract.reference_no.ilike(term),
        ))
    if contract_type:
        query = query.where(Contract.contract_type == contract_type)

    total = (await db.scalar(select(func.count()).select_from(query.subquery()))) or 0
    result = await db.execute(
        query.order_by(Contract.end_date.asc().nulls_last())
        .offset((page - 1) * size).limit(size)
    )
    items = [_serialize(c) for c in result.scalars().all()]
    return APIResponse(data={"items": items, "total": total, "page": page, "size": size})


@router.get("/{contract_id}", response_model=APIResponse[ContractDetailOut])
async def get_contract(
    contract_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    contract = await _get_contract(db, contract_id)
    return APIResponse(data=_serialize_detail(contract))


@router.post("", response_model=APIResponse[ContractDetailOut])
async def create_contract(
    body: ContractCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    manager: User = Depends(require_role("asset_manager")),
):
    contract = Contract(**body.model_dump())
    db.add(contract)
    await db.flush()
    await AuditService.log(db, request, manager, "contract.created",
                           resource_type="contract", resource_id=str(contract.id),
                           detail={"name": contract.name, "type": contract.contract_type})
    await db.commit()
    contract = await _get_contract(db, contract.id)
    return APIResponse(data=_serialize_detail(contract), message="Contract created")


@router.patch("/{contract_id}", response_model=APIResponse[ContractDetailOut])
async def update_contract(
    contract_id: int,
    body: ContractUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    manager: User = Depends(require_role("asset_manager")),
):
    contract = await _get_contract(db, contract_id)
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(contract, field, value)
    await AuditService.log(db, request, manager, "contract.updated",
                           resource_type="contract", resource_id=str(contract.id),
                           detail={"changed_fields": sorted(changes.keys())})
    await db.commit()
    contract = await _get_contract(db, contract_id)
    return APIResponse(data=_serialize_detail(contract), message="Contract updated")


@router.delete("/{contract_id}", response_model=APIResponse[bool])
async def delete_contract(
    contract_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    contract = await _get_contract(db, contract_id)
    name = contract.name
    await db.delete(contract)
    await AuditService.log(db, request, admin, "contract.deleted",
                           resource_type="contract", resource_id=str(contract_id),
                           detail={"name": name})
    await db.commit()
    return APIResponse(data=True, message="Contract deleted")


@router.post("/{contract_id}/assets", response_model=APIResponse[ContractDetailOut])
async def attach_asset(
    contract_id: int,
    body: AttachAssetRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    manager: User = Depends(require_role("asset_manager")),
):
    contract = await _get_contract(db, contract_id)
    asset = (await db.execute(
        select(Asset).where(Asset.id == body.asset_id)
    )).scalars().first()
    if not asset:
        raise HTTPException(404, "Asset not found")
    if any(a.id == asset.id for a in contract.assets):
        raise HTTPException(400, "Asset is already attached to this contract")

    await db.execute(contract_assets.insert().values(
        contract_id=contract_id, asset_id=asset.id))
    await AuditService.log(db, request, manager, "contract.asset_attached",
                           resource_type="contract", resource_id=str(contract_id),
                           detail={"asset_tag": asset.asset_tag})
    await db.commit()
    contract = await _get_contract(db, contract_id)
    return APIResponse(data=_serialize_detail(contract), message="Asset attached")


@router.delete("/{contract_id}/assets/{asset_id}", response_model=APIResponse[ContractDetailOut])
async def detach_asset(
    contract_id: int,
    asset_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    manager: User = Depends(require_role("asset_manager")),
):
    contract = await _get_contract(db, contract_id)
    if not any(a.id == asset_id for a in contract.assets):
        raise HTTPException(404, "Asset is not attached to this contract")

    await db.execute(contract_assets.delete().where(
        (contract_assets.c.contract_id == contract_id)
        & (contract_assets.c.asset_id == asset_id)))
    await AuditService.log(db, request, manager, "contract.asset_detached",
                           resource_type="contract", resource_id=str(contract_id),
                           detail={"asset_id": asset_id})
    await db.commit()
    contract = await _get_contract(db, contract_id)
    return APIResponse(data=_serialize_detail(contract), message="Asset detached")
