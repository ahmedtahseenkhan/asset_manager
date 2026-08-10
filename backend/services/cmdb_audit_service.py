"""
CMDB health audit: cross-references discovery against the asset register to
surface drift, gaps, and duplicates — the periodic reconciliation check that
keeps a CMDB trustworthy.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.asset import Asset
from backend.models.device import Device
from backend.models.device_source import DeviceSource


class CMDBAuditService:
    @staticmethod
    async def run(db: AsyncSession, stale_days: int = 30) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        stale_cutoff = now - timedelta(days=stale_days)

        total_devices = (await db.scalar(select(func.count(Device.id)))) or 0
        total_assets = (await db.scalar(select(func.count(Asset.id)))) or 0
        linked = (await db.scalar(
            select(func.count(Asset.id)).where(Asset.device_id.isnot(None))
        )) or 0

        # 1. Unmanaged devices — active, discovered, but no asset record.
        linked_ids = select(Asset.device_id).where(Asset.device_id.isnot(None))
        unmanaged = (await db.execute(
            select(Device).where(Device.id.notin_(linked_ids), Device.status == "active")
        )).scalars().all()

        # 2. Devices with an agent source (deepest data) vs scan-only.
        agent_devices = (await db.scalar(
            select(func.count(func.distinct(DeviceSource.device_id)))
            .where(DeviceSource.source_name == "agent")
        )) or 0

        # 3. Duplicate hostnames (same non-null hostname on >1 device).
        dup_rows = (await db.execute(
            select(Device.hostname, func.count(Device.id))
            .where(Device.hostname.isnot(None))
            .group_by(Device.hostname).having(func.count(Device.id) > 1)
        )).all()
        duplicates = [{"hostname": h, "count": c} for h, c in dup_rows]

        # 4. Stale assets — linked device not seen within the window.
        stale = (await db.execute(
            select(Asset).join(Device, Asset.device_id == Device.id)
            .where(Device.last_seen < stale_cutoff)
        )).scalars().all()

        coverage_pct = round(100 * linked / total_devices, 1) if total_devices else 0.0
        agent_pct = round(100 * agent_devices / total_devices, 1) if total_devices else 0.0

        return {
            "generated_at": now.isoformat(),
            "totals": {
                "devices": total_devices,
                "assets": total_assets,
                "managed_devices": linked,
                "coverage_pct": coverage_pct,
                "agent_covered_devices": agent_devices,
                "agent_coverage_pct": agent_pct,
            },
            "unmanaged_devices": [
                {"id": d.id, "hostname": d.hostname, "ip": (d.ip_addresses or [None])[0],
                 "os_name": d.os_name, "last_seen": d.last_seen}
                for d in unmanaged[:200]
            ],
            "unmanaged_count": len(unmanaged),
            "duplicate_hostnames": duplicates,
            "stale_assets": [
                {"asset_tag": a.asset_tag, "name": a.name,
                 "last_seen": a.device.last_seen if a.device else None}
                for a in stale[:200]
            ],
            "stale_count": len(stale),
        }
