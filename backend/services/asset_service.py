from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models.asset import ALLOWED_TRANSITIONS, Asset, AssetLifecycleEvent
from backend.models.user import User
from backend.schemas.asset import AssetCreate, AssetUpdate


def _serialize(asset: Asset) -> dict:
    """Flatten ORM row + joined names into an AssetOut-shaped dict."""
    return {
        **{c: getattr(asset, c) for c in (
            "id", "asset_tag", "name", "category", "asset_type", "lifecycle_state",
            "serial_number", "vendor", "model", "location", "department", "assigned_to",
            "purchase_date", "purchase_cost", "currency", "warranty_end",
            "custom_fields", "notes", "device_id", "created_at", "updated_at",
        )},
        "assignee_username": asset.assignee.username if asset.assignee else None,
        "device_hostname": asset.device.hostname if asset.device else None,
    }


class AssetService:
    @staticmethod
    async def list_assets(
        db: AsyncSession,
        page: int = 1,
        size: int = 50,
        search: Optional[str] = None,
        category: Optional[str] = None,
        lifecycle_state: Optional[str] = None,
    ) -> tuple[int, list[dict]]:
        query = select(Asset)
        if search:
            term = f"%{search}%"
            query = query.where(or_(
                Asset.name.ilike(term),
                Asset.asset_tag.ilike(term),
                Asset.serial_number.ilike(term),
                Asset.vendor.ilike(term),
                Asset.model.ilike(term),
            ))
        if category:
            query = query.where(Asset.category == category)
        if lifecycle_state:
            query = query.where(Asset.lifecycle_state == lifecycle_state)

        total = (await db.scalar(
            select(func.count()).select_from(query.subquery())
        )) or 0
        result = await db.execute(
            query.order_by(Asset.id.desc()).offset((page - 1) * size).limit(size)
        )
        return total, [_serialize(a) for a in result.scalars().all()]

    @staticmethod
    async def get_asset(db: AsyncSession, asset_id: int) -> Asset:
        result = await db.execute(
            select(Asset)
            .options(selectinload(Asset.lifecycle_events))
            .where(Asset.id == asset_id)
        )
        asset = result.scalars().first()
        if not asset:
            raise HTTPException(404, "Asset not found")
        return asset

    @staticmethod
    def serialize_detail(asset: Asset) -> dict:
        return {
            **_serialize(asset),
            "lifecycle_events": [
                {
                    "id": e.id,
                    "from_state": e.from_state,
                    "to_state": e.to_state,
                    "actor": e.actor.username if e.actor else None,
                    "note": e.note,
                    "occurred_at": e.occurred_at,
                }
                for e in asset.lifecycle_events
            ],
            "allowed_transitions": ALLOWED_TRANSITIONS[asset.lifecycle_state],
        }

    @staticmethod
    async def create_asset(db: AsyncSession, asset_in: AssetCreate, actor: User) -> Asset:
        data = asset_in.model_dump(exclude={"asset_tag"})
        asset = Asset(**data, asset_tag=asset_in.asset_tag or "", created_by=actor.id)
        db.add(asset)
        await db.flush()  # obtain asset.id for tag generation
        if not asset.asset_tag:
            asset.asset_tag = f"AST-{asset.id:05d}"

        db.add(AssetLifecycleEvent(
            asset_id=asset.id, from_state=None, to_state=asset.lifecycle_state,
            actor_id=actor.id, note="Asset created",
        ))
        await db.commit()
        return await AssetService.get_asset(db, asset.id)

    @staticmethod
    async def update_asset(db: AsyncSession, asset_id: int, asset_in: AssetUpdate) -> Asset:
        asset = await AssetService.get_asset(db, asset_id)
        for field, value in asset_in.model_dump(exclude_unset=True).items():
            setattr(asset, field, value)
        await db.commit()
        return await AssetService.get_asset(db, asset_id)

    @staticmethod
    async def transition(
        db: AsyncSession, asset_id: int, to_state: str, actor: User, note: Optional[str],
    ) -> Asset:
        asset = await AssetService.get_asset(db, asset_id)
        allowed = ALLOWED_TRANSITIONS[asset.lifecycle_state]
        if to_state not in allowed:
            raise HTTPException(
                400,
                f"Invalid transition {asset.lifecycle_state!r} -> {to_state!r}. "
                f"Allowed: {allowed or 'none (terminal state)'}",
            )
        db.add(AssetLifecycleEvent(
            asset_id=asset.id, from_state=asset.lifecycle_state, to_state=to_state,
            actor_id=actor.id, note=note,
        ))
        asset.lifecycle_state = to_state
        await db.commit()
        return await AssetService.get_asset(db, asset_id)

    @staticmethod
    async def delete_asset(db: AsyncSession, asset_id: int) -> None:
        asset = await AssetService.get_asset(db, asset_id)
        await db.delete(asset)
        await db.commit()
