"""
Endpoint-health conditions over device_inventory, shared by the dashboard
tiles and the device-list filter so counts and drill-down lists always agree.
"""
from datetime import datetime, timedelta, timezone
from typing import Dict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.device import Device
from backend.models.inventory import DeviceChange, DeviceInventory

ADMIN_SPRAWL_THRESHOLD = 3     # local admin group members; Administrator + Domain Admins is normal
STALE_INVENTORY_DAYS = 7

HEALTH_LABELS = {
    "no_antivirus": "No working antivirus",
    "firewall_off": "Firewall off",
    "not_encrypted": "Disk not encrypted",
    "pending_reboot": "Reboot pending",
    "admin_sprawl": f"{ADMIN_SPRAWL_THRESHOLD}+ local admins",
    "stale_inventory": f"No inventory for {STALE_INVENTORY_DAYS}+ days",
}


def health_conditions() -> Dict[str, object]:
    stale_cutoff = datetime.now(timezone.utc) - timedelta(days=STALE_INVENTORY_DAYS)
    return {
        "no_antivirus": DeviceInventory.antivirus_ok.is_(False),
        "firewall_off": DeviceInventory.firewall_ok.is_(False),
        "not_encrypted": DeviceInventory.disk_encrypted.is_(False),
        "pending_reboot": DeviceInventory.pending_reboot.is_(True),
        "admin_sprawl": DeviceInventory.local_admin_count >= ADMIN_SPRAWL_THRESHOLD,
        "stale_inventory": DeviceInventory.collected_at < stale_cutoff,
    }


async def endpoint_health(db: AsyncSession) -> Dict[str, object]:
    base = (select(func.count(Device.id))
            .join(DeviceInventory, DeviceInventory.device_id == Device.id)
            .where(Device.status == "active"))
    counts = {key: (await db.scalar(base.where(cond))) or 0 for key, cond in health_conditions().items()}
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    warnings = await db.scalar(select(func.count(DeviceChange.id)).where(
        DeviceChange.severity == "warning", DeviceChange.detected_at >= week_ago))
    return {
        "inventoried": (await db.scalar(base)) or 0,
        "counts": counts,
        "labels": HEALTH_LABELS,
        "warnings_7d": warnings or 0,
    }
