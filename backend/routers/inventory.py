"""Device inventory sections, change history, and endpoint health (read-only)."""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware.auth import get_current_user
from backend.models.device import Device
from backend.models.inventory import (
    CHANGE_CATEGORIES, DeviceAntivirus, DeviceChange, DeviceInventory, DeviceLocalAccount,
    DeviceMonitor, DeviceNetworkAdapter, DevicePatch, DevicePrinter, DeviceService, DeviceVolume,
)
from backend.models.user import User
from backend.models.virtualization import VmPlacement
from backend.schemas.common import APIResponse
from backend.services.endpoint_health import endpoint_health

router = APIRouter(tags=["Inventory"])

_SUMMARY_FIELDS = (
    "source", "collector_version", "collected_at", "sections_collected",
    "manufacturer", "model", "chassis_type", "is_virtual", "cpu", "cpu_cores", "cpu_logical",
    "ram_gb", "disk_gb", "bios_vendor", "bios_version", "bios_date", "motherboard",
    "os_name", "os_version", "os_build", "architecture", "last_boot", "logged_in_user",
    "pending_reboot", "tpm_present", "tpm_ready", "secure_boot", "firewall_profiles",
    "firewall_ok", "antivirus_ok", "disk_encrypted", "local_admin_count",
)


def _row(obj, *fields) -> Dict[str, Any]:
    return {f: getattr(obj, f) for f in fields}


async def _rows(db: AsyncSession, model, device_id: int, order) -> list:
    return (await db.execute(select(model).where(model.device_id == device_id).order_by(order))).scalars().all()


@router.get("/devices/{device_id}/inventory", response_model=APIResponse[Dict[str, Any]])
async def device_inventory(device_id: int, db: AsyncSession = Depends(get_db),
                           user: User = Depends(get_current_user)):
    if await db.get(Device, device_id) is None:
        raise HTTPException(404, "Device not found")
    inv = (await db.execute(
        select(DeviceInventory).where(DeviceInventory.device_id == device_id))).scalars().first()
    if inv is None:
        return APIResponse(data={"summary": None})
    return APIResponse(data={
        "summary": _row(inv, *_SUMMARY_FIELDS),
        "patches": [_row(r, "patch_id", "description", "installed_on", "first_seen")
                    for r in await _rows(db, DevicePatch, device_id, DevicePatch.installed_on.desc().nullslast())],
        "services": [_row(r, "name", "display_name", "state", "start_mode", "account")
                     for r in await _rows(db, DeviceService, device_id, DeviceService.name)],
        "local_accounts": [_row(r, "name", "enabled", "is_admin", "last_logon")
                           for r in await _rows(db, DeviceLocalAccount, device_id, DeviceLocalAccount.name)],
        "antivirus": [_row(r, "name", "enabled", "up_to_date", "definitions_date")
                      for r in await _rows(db, DeviceAntivirus, device_id, DeviceAntivirus.name)],
        "volumes": [_row(r, "name", "filesystem", "size_gb", "free_gb", "encryption_method", "encrypted",
                         "encryption_status")
                    for r in await _rows(db, DeviceVolume, device_id, DeviceVolume.name)],
        "network_adapters": [_row(r, "name", "mac", "ip_addresses", "speed_mbps", "dhcp", "gateway", "dns_servers")
                             for r in await _rows(db, DeviceNetworkAdapter, device_id, DeviceNetworkAdapter.name)],
        "monitors": [_row(r, "manufacturer", "model", "serial_number")
                     for r in await _rows(db, DeviceMonitor, device_id, DeviceMonitor.id)],
        "printers": [_row(r, "name", "driver", "port", "is_network", "is_default")
                     for r in await _rows(db, DevicePrinter, device_id, DevicePrinter.name)],
    })


_PLACEMENT_FIELDS = ("vm_name", "platform", "instance_id", "power_state", "guest_os", "vcpus", "memory_gb",
                     "disk_gb", "tools_status", "cluster", "datacenter", "last_seen")


@router.get("/devices/{device_id}/virtualization", response_model=APIResponse[Dict[str, Any]])
async def device_virtualization(device_id: int, db: AsyncSession = Depends(get_db),
                                user: User = Depends(get_current_user)):
    """The host this device runs on (if it is a VM), and the guests it runs (if it is a host)."""
    if await db.get(Device, device_id) is None:
        raise HTTPException(404, "Device not found")
    host = None
    row = (await db.execute(
        select(VmPlacement, Device.hostname).join(Device, Device.id == VmPlacement.host_device_id)
        .where(VmPlacement.vm_device_id == device_id))).first()
    if row:
        host = {"device_id": row[0].host_device_id, "hostname": row[1], **_row(row[0], *_PLACEMENT_FIELDS)}
    rows = (await db.execute(
        select(VmPlacement, Device.hostname, Device.ip_addresses, DeviceInventory.sections_collected)
        .join(Device, Device.id == VmPlacement.vm_device_id)
        .outerjoin(DeviceInventory, DeviceInventory.device_id == VmPlacement.vm_device_id)
        .where(VmPlacement.host_device_id == device_id).order_by(VmPlacement.vm_name))).all()
    guests = [{"device_id": p.vm_device_id, "hostname": hostname, "ip": (ips or [None])[0],
               "inventoried": bool(sections), **_row(p, *_PLACEMENT_FIELDS)}
              for p, hostname, ips, sections in rows]
    running = [g for g in guests if g["power_state"] == "on"]
    return APIResponse(data={
        "host": host,
        "guests": guests,
        "totals": {"guests": len(guests), "running": len(running),
                   "vcpus_running": sum(g["vcpus"] or 0 for g in running),
                   "memory_gb_running": round(sum(g["memory_gb"] or 0 for g in running), 1)},
    })


def _change_view(c: DeviceChange, hostname: Optional[str] = None) -> Dict[str, Any]:
    out = _row(c, "id", "device_id", "category", "change_type", "item", "field", "old_value", "new_value",
               "severity", "source", "detected_at")
    if hostname is not None:
        out["hostname"] = hostname
    return out


def _change_filters(q, category: Optional[str], severity: Optional[str]):
    if category:
        if category not in CHANGE_CATEGORIES:
            raise HTTPException(400, f"category must be one of {', '.join(CHANGE_CATEGORIES)}")
        q = q.where(DeviceChange.category == category)
    if severity:
        q = q.where(DeviceChange.severity == severity)
    return q


@router.get("/devices/{device_id}/changes", response_model=APIResponse[Dict[str, Any]])
async def device_changes(device_id: int, category: Optional[str] = None, severity: Optional[str] = None,
                         limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
                         db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    q = _change_filters(select(DeviceChange).where(DeviceChange.device_id == device_id), category, severity)
    total = await db.scalar(select(func.count()).select_from(q.subquery()))
    rows = (await db.execute(
        q.order_by(DeviceChange.detected_at.desc(), DeviceChange.id.desc()).offset(offset).limit(limit)
    )).scalars().all()
    return APIResponse(data={"total": total or 0, "items": [_change_view(c) for c in rows]})


@router.get("/changes", response_model=APIResponse[List[Dict[str, Any]]])
async def recent_changes(category: Optional[str] = None, severity: Optional[str] = None,
                         days: int = Query(7, ge=1, le=365), limit: int = Query(50, ge=1, le=500),
                         db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    q = _change_filters(
        select(DeviceChange, Device.hostname).join(Device, Device.id == DeviceChange.device_id)
        .where(DeviceChange.detected_at >= since), category, severity)
    rows = (await db.execute(q.order_by(DeviceChange.detected_at.desc(), DeviceChange.id.desc()).limit(limit))).all()
    return APIResponse(data=[_change_view(c, hostname or "") for c, hostname in rows])


@router.get("/dashboard/endpoint-health", response_model=APIResponse[Dict[str, Any]])
async def dashboard_endpoint_health(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return APIResponse(data=await endpoint_health(db))
