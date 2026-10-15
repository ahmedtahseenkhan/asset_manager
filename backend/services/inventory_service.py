"""
The single ingestion path for host inventory. Every collector (agent, WinRM,
WMI, SSH, SNMP, hypervisor/cloud connectors) hands an InventoryReport to
InventoryService.ingest(), which:

1. merges the device through the correlator (source authority, identity),
2. upserts the collected sections — sections a collector did not collect
   (None) are left untouched,
3. pushes authoritative fields onto the linked asset.

Phase 1 adds per-section tables and change history here; until then the full
report is kept in the device source's raw_data, so nothing collected is lost.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.connectors.base import RawDeviceRecord
from backend.correlator.correlator import Correlator
from backend.models.asset import Asset
from backend.models.device import Device
from backend.models.software import InstalledSoftware
from backend.schemas.inventory import InventoryReport, SoftwareItem
from backend.services.software_normalizer import normalize_software

# Sources whose reports come from inside the machine and are authoritative for
# its hardware identity and OS on the linked asset.
HOST_SOURCES = {"agent", "winrm", "wmi", "ssh"}


def source_uid_for(source: str, report: InventoryReport) -> str:
    """Stable per-source identity. Prefers hardware identity over the hostname
    so a renamed machine stays the same DeviceSource."""
    hw = report.hardware
    uid = (hw and (hw.serial_number or hw.hardware_uuid)) or report.hostname or "unknown"
    return f"{source}-{uid}"


def _raw_record(source: str, report: InventoryReport, now: datetime) -> RawDeviceRecord:
    hw = report.hardware
    return {
        "source_uid": source_uid_for(source, report),
        "hostname": report.hostname,
        "fqdn": report.fqdn,
        "ip_addresses": report.ip_addresses,
        "mac_addresses": report.mac_addresses,
        "os_name": report.os_name,
        "os_version": report.os_version,
        "domain": report.domain,
        "ou": None,
        "last_seen": now,
        "extra": {
            "method": source,
            "serial_number": hw.serial_number if hw else None,
            "hardware_uuid": hw.hardware_uuid if hw else None,
            # Full report, so sections without their own table yet are retained.
            "inventory": report.model_dump(exclude_none=True),
        },
    }


async def _sync_software(db: AsyncSession, device_id: int, items: List[SoftwareItem],
                         now: datetime) -> Dict[str, int]:
    """Diff the reported list against what is stored: keep rows that are still
    installed (refreshing last_seen), add new ones, delete removed ones."""
    reported: Dict[tuple, SoftwareItem] = {}
    for item in items:
        name = item.name.strip()[:500]
        version = (item.version or "").strip()[:128] or None
        if name:
            reported.setdefault((name, version), item)

    existing = (await db.execute(
        select(InstalledSoftware).where(InstalledSoftware.device_id == device_id)
    )).scalars().all()
    stored = {(s.name, s.version): s for s in existing}

    removed = [s.id for key, s in stored.items() if key not in reported]
    if removed:
        await db.execute(delete(InstalledSoftware).where(InstalledSoftware.id.in_(removed)))

    added = 0
    for key, item in reported.items():
        row = stored.get(key)
        if row is not None:
            row.last_seen = now
            if item.publisher and not row.publisher:
                row.publisher = item.publisher[:255]
            continue
        name, version = key
        db.add(InstalledSoftware(
            device_id=device_id,
            name=name,
            normalized_name=normalize_software(name)[:500],
            version=version,
            publisher=(item.publisher or None) and item.publisher[:255],
            last_seen=now,
        ))
        added += 1

    return {"total": len(reported), "added": added, "removed": len(removed)}


async def _push_to_asset(db: AsyncSession, device: Device, report: InventoryReport) -> bool:
    asset = (await db.execute(select(Asset).where(Asset.device_id == device.id))).scalars().first()
    if asset is None:
        return False
    hw = report.hardware
    if hw:
        if hw.serial_number and device.serial_number:
            asset.serial_number = device.serial_number    # junk serials already filtered
        if hw.model:
            asset.model = hw.model
        if hw.manufacturer and not asset.vendor:
            asset.vendor = hw.manufacturer
    if report.os_name:
        asset.os_name = report.os_name
    if report.os_version:
        asset.os_version = report.os_version
    if report.ip_addresses:
        asset.ip_address = report.ip_addresses[0]
    if report.mac_addresses:
        asset.mac_address = report.mac_addresses[0]
    return True


class InventoryService:
    @staticmethod
    async def ingest(db: AsyncSession, source: str, report: InventoryReport) -> Dict[str, Any]:
        """Ingest one report. Flushes; the caller commits."""
        now = datetime.now(timezone.utc)
        device, created = await Correlator.upsert_device(db, source, _raw_record(source, report, now))

        software: Optional[Dict[str, int]] = None
        if report.software is not None:
            software = await _sync_software(db, device.id, report.software, now)

        asset_updated = False
        if source in HOST_SOURCES:
            asset_updated = await _push_to_asset(db, device, report)

        await db.flush()
        return {
            "device_id": device.id,
            "device_created": created,
            "hostname": device.hostname,
            "software": software,
            "asset_updated": asset_updated,
        }
