from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.licensing.enforcement import require_module
from backend.middleware.auth import get_current_user, require_admin, require_role
from backend.models.asset import Asset
from backend.models.contract import Contract
from backend.models.entitlement import Entitlement, EntitlementAssignment
from backend.models.user import User
from backend.schemas.common import APIResponse
from backend.schemas.entitlement import (
    AssignRequest,
    EntitlementCreate,
    EntitlementDetailOut,
    EntitlementListOut,
    EntitlementOut,
    EntitlementUpdate,
)
from backend.services.audit_service import AuditService

router = APIRouter(prefix="/entitlements", tags=["Entitlements"],
                   dependencies=[require_module("entitlements")])

_FIELDS = ("id", "product", "vendor", "license_model", "seats_purchased",
           "contract_id", "expires_on", "custom_fields", "created_at", "updated_at")

# Which assignment target consumes a seat for each license model
_SEAT_COUNTED = {"per_seat", "per_device"}


def _serialize(e: Entitlement) -> dict:
    key = e.license_key
    return {
        **{f: getattr(e, f) for f in _FIELDS},
        "seats_used": len(e.assignments),
        "has_key": key is not None,
        "key_hint": f"…{key[-4:]}" if key and len(key) >= 4 else None,
        "contract_name": e.contract.name if e.contract else None,
    }


def _serialize_detail(e: Entitlement, include_key: bool) -> dict:
    return {
        **_serialize(e),
        "license_key": e.license_key if include_key else None,
        "assignments": [
            {
                "id": a.id,
                "asset_id": a.asset_id,
                "asset_tag": a.asset.asset_tag if a.asset else None,
                "asset_name": a.asset.name if a.asset else None,
                "user_id": a.user_id,
                "username": a.user.username if a.user else None,
                "assigned_at": a.assigned_at,
            }
            for a in e.assignments
        ],
    }


async def _get_entitlement(db: AsyncSession, entitlement_id: int) -> Entitlement:
    ent = (await db.execute(
        select(Entitlement).where(Entitlement.id == entitlement_id)
        .execution_options(populate_existing=True)
    )).scalars().first()
    if not ent:
        raise HTTPException(404, "Entitlement not found")
    return ent


@router.get("", response_model=APIResponse[EntitlementListOut])
async def list_entitlements(
    page: int = 1,
    size: int = 50,
    search: Optional[str] = None,
    license_model: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    page, size = max(1, page), min(max(1, size), 200)
    query = select(Entitlement)
    if search:
        term = f"%{search}%"
        query = query.where(or_(
            Entitlement.product.ilike(term),
            Entitlement.vendor.ilike(term),
        ))
    if license_model:
        query = query.where(Entitlement.license_model == license_model)

    total = (await db.scalar(select(func.count()).select_from(query.subquery()))) or 0
    result = await db.execute(
        query.order_by(Entitlement.expires_on.asc().nulls_last())
        .offset((page - 1) * size).limit(size)
    )
    items = [_serialize(e) for e in result.scalars().all()]
    return APIResponse(data={"items": items, "total": total, "page": page, "size": size})


@router.get("/{entitlement_id}", response_model=APIResponse[EntitlementDetailOut])
async def get_entitlement(
    entitlement_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ent = await _get_entitlement(db, entitlement_id)
    # Full key is admin-only; managers/viewers get the hint.
    return APIResponse(data=_serialize_detail(ent, include_key=current_user.role == "admin"))


@router.post("", response_model=APIResponse[EntitlementDetailOut])
async def create_entitlement(
    body: EntitlementCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    manager: User = Depends(require_role("asset_manager")),
):
    if body.contract_id is not None:
        if not (await db.execute(
            select(Contract.id).where(Contract.id == body.contract_id)
        )).first():
            raise HTTPException(404, "Contract not found")

    ent = Entitlement(**body.model_dump())
    db.add(ent)
    await db.flush()
    await AuditService.log(db, request, manager, "entitlement.created",
                           resource_type="entitlement", resource_id=str(ent.id),
                           detail={"product": ent.product, "model": ent.license_model})
    await db.commit()
    ent = await _get_entitlement(db, ent.id)
    return APIResponse(data=_serialize_detail(ent, include_key=manager.role == "admin"),
                       message="Entitlement created")


@router.patch("/{entitlement_id}", response_model=APIResponse[EntitlementDetailOut])
async def update_entitlement(
    entitlement_id: int,
    body: EntitlementUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    manager: User = Depends(require_role("asset_manager")),
):
    ent = await _get_entitlement(db, entitlement_id)
    changes = body.model_dump(exclude_unset=True)
    if "contract_id" in changes and changes["contract_id"] is not None:
        if not (await db.execute(
            select(Contract.id).where(Contract.id == changes["contract_id"])
        )).first():
            raise HTTPException(404, "Contract not found")
    for field, value in changes.items():
        setattr(ent, field, value)
    await AuditService.log(db, request, manager, "entitlement.updated",
                           resource_type="entitlement", resource_id=str(ent.id),
                           # never log the key itself
                           detail={"changed_fields": sorted(changes.keys())})
    await db.commit()
    ent = await _get_entitlement(db, entitlement_id)
    return APIResponse(data=_serialize_detail(ent, include_key=manager.role == "admin"),
                       message="Entitlement updated")


@router.delete("/{entitlement_id}", response_model=APIResponse[bool])
async def delete_entitlement(
    entitlement_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    ent = await _get_entitlement(db, entitlement_id)
    product = ent.product
    await db.delete(ent)
    await AuditService.log(db, request, admin, "entitlement.deleted",
                           resource_type="entitlement", resource_id=str(entitlement_id),
                           detail={"product": product})
    await db.commit()
    return APIResponse(data=True, message="Entitlement deleted")


@router.post("/{entitlement_id}/assign", response_model=APIResponse[EntitlementDetailOut])
async def assign_seat(
    entitlement_id: int,
    body: AssignRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    manager: User = Depends(require_role("asset_manager")),
):
    ent = await _get_entitlement(db, entitlement_id)

    if body.asset_id is not None:
        if not (await db.execute(select(Asset.id).where(Asset.id == body.asset_id))).first():
            raise HTTPException(404, "Asset not found")
    if body.user_id is not None:
        if not (await db.execute(select(User.id).where(User.id == body.user_id))).first():
            raise HTTPException(404, "User not found")

    duplicate = any(
        a.asset_id == body.asset_id and a.user_id == body.user_id
        for a in ent.assignments
    )
    if duplicate:
        raise HTTPException(400, "This assignment already exists")

    # Seat enforcement for counted models (site/subscription are unlimited)
    if ent.license_model in _SEAT_COUNTED and ent.seats_purchased is not None:
        if len(ent.assignments) >= ent.seats_purchased:
            raise HTTPException(
                400,
                f"All {ent.seats_purchased} purchased seat(s) are in use. "
                "Unassign one or increase seats_purchased.",
            )

    db.add(EntitlementAssignment(
        entitlement_id=entitlement_id, asset_id=body.asset_id, user_id=body.user_id,
    ))
    await AuditService.log(db, request, manager, "entitlement.assigned",
                           resource_type="entitlement", resource_id=str(entitlement_id),
                           detail={"asset_id": body.asset_id, "user_id": body.user_id})
    await db.commit()
    ent = await _get_entitlement(db, entitlement_id)
    return APIResponse(data=_serialize_detail(ent, include_key=manager.role == "admin"),
                       message="Seat assigned")


@router.delete("/{entitlement_id}/assign/{assignment_id}",
               response_model=APIResponse[EntitlementDetailOut])
async def unassign_seat(
    entitlement_id: int,
    assignment_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    manager: User = Depends(require_role("asset_manager")),
):
    assignment = (await db.execute(
        select(EntitlementAssignment).where(
            EntitlementAssignment.id == assignment_id,
            EntitlementAssignment.entitlement_id == entitlement_id,
        )
    )).scalars().first()
    if not assignment:
        raise HTTPException(404, "Assignment not found")

    await db.delete(assignment)
    await AuditService.log(db, request, manager, "entitlement.unassigned",
                           resource_type="entitlement", resource_id=str(entitlement_id),
                           detail={"assignment_id": assignment_id})
    await db.commit()
    ent = await _get_entitlement(db, entitlement_id)
    return APIResponse(data=_serialize_detail(ent, include_key=manager.role == "admin"),
                       message="Seat unassigned")
