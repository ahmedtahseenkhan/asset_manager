"""
Device ↔ asset reconciliation.

Discovered devices (connector sync) are telemetry; assets are the managed
register. This service surfaces discovered devices with no asset record and
lets managers adopt them (create an asset per device) or link them to an
existing unlinked asset.
"""
from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.licensing.state import license_manager
from backend.models.asset import Asset, AssetLifecycleEvent
from backend.models.device import Device
from backend.models.user import User


class ReconciliationService:
    @staticmethod
    async def unlinked_devices(db: AsyncSession) -> List[dict]:
        """Active discovered devices that have no asset record, with link suggestions."""
        linked = select(Asset.device_id).where(Asset.device_id.isnot(None))
        result = await db.execute(
            select(Device)
            .where(Device.id.notin_(linked), Device.status == "active")
            .order_by(Device.hostname)
        )
        devices = result.scalars().all()

        # Suggest existing UNLINKED assets whose name matches the hostname.
        hostnames = [d.hostname.lower() for d in devices if d.hostname]
        suggestions: dict[str, dict] = {}
        if hostnames:
            res = await db.execute(
                select(Asset).where(
                    Asset.device_id.is_(None),
                    func.lower(Asset.name).in_(hostnames),
                )
            )
            for a in res.scalars().all():
                suggestions[a.name.lower()] = {
                    "id": a.id, "asset_tag": a.asset_tag, "name": a.name,
                }

        return [
            {
                "id": d.id,
                "hostname": d.hostname,
                "fqdn": d.fqdn,
                "ip_addresses": d.ip_addresses,
                "os_name": d.os_name,
                "os_version": d.os_version,
                "last_seen": d.last_seen,
                "suggested_asset": suggestions.get((d.hostname or "").lower()),
            }
            for d in devices
        ]

    @staticmethod
    async def adopt(db: AsyncSession, device_ids: List[int], actor: User) -> List[Asset]:
        """Create one hardware asset per discovered device. Enforces the license cap."""
        linked = select(Asset.device_id).where(Asset.device_id.isnot(None))
        result = await db.execute(
            select(Device).where(Device.id.in_(device_ids), Device.id.notin_(linked))
        )
        devices = result.scalars().all()
        if not devices:
            raise HTTPException(400, "No adoptable devices in selection (already linked or unknown)")

        info = license_manager.current
        max_assets = int(info.claims.get("max_assets", 0)) if info.is_operational else 0
        current = (await db.scalar(select(func.count(Asset.id)))) or 0
        if current + len(devices) > max_assets:
            raise HTTPException(
                403,
                f"Adopting {len(devices)} device(s) would exceed the license limit "
                f"(max_assets={max_assets}, current={current}).",
            )

        created: List[Asset] = []
        for d in devices:
            asset = Asset(
                name=d.hostname or d.fqdn or f"device-{d.id}",
                category="hardware",
                asset_type="computer",
                lifecycle_state="deployed",   # it is live on the network
                device_id=d.id,
                created_by=actor.id,
                asset_tag="",
                custom_fields={},
                notes=f"Adopted from discovered device (os: {d.os_name or 'unknown'})",
            )
            db.add(asset)
            await db.flush()
            asset.asset_tag = f"AST-{asset.id:05d}"
            db.add(AssetLifecycleEvent(
                asset_id=asset.id, from_state=None, to_state="deployed",
                actor_id=actor.id, note="Adopted from discovered device",
            ))
            created.append(asset)
        await db.commit()
        return created

    @staticmethod
    async def link(db: AsyncSession, device_id: int, asset_id: int) -> Asset:
        """Link an existing asset to a discovered device (both must be unlinked)."""
        device: Optional[Device] = (
            await db.execute(select(Device).where(Device.id == device_id))
        ).scalars().first()
        if not device:
            raise HTTPException(404, "Device not found")

        already = (
            await db.execute(select(Asset).where(Asset.device_id == device_id))
        ).scalars().first()
        if already:
            raise HTTPException(400, f"Device is already linked to asset {already.asset_tag}")

        asset: Optional[Asset] = (
            await db.execute(select(Asset).where(Asset.id == asset_id))
        ).scalars().first()
        if not asset:
            raise HTTPException(404, "Asset not found")
        if asset.device_id is not None:
            raise HTTPException(400, f"Asset {asset.asset_tag} is already linked to another device")

        asset.device_id = device_id
        await db.commit()
        return asset
