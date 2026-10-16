"""
The single ingestion path for host inventory. Every collector (agent, WinRM,
WMI, SSH, SNMP, hypervisor/cloud connectors) hands an InventoryReport to
InventoryService.ingest(), which:

1. merges the device through the correlator (source authority, identity),
2. upserts each collected section — sections a collector did not collect
   (None) are left untouched,
3. records what changed since the previous report (device_changes),
4. pushes authoritative fields onto the linked asset.

A section's first report for a device is a baseline: stored, but not turned
into "added" changes, so enrolling a machine doesn't log 300 installs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, Type

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.connectors.base import RawDeviceRecord
from backend.correlator.correlator import Correlator
from backend.models.asset import Asset
from backend.models.device import Device
from backend.models.inventory import (
    DeviceAntivirus, DeviceChange, DeviceInventory, DeviceLocalAccount, DeviceMonitor,
    DeviceNetworkAdapter, DevicePatch, DevicePrinter, DeviceService, DeviceVolume,
)
from backend.models.software import InstalledSoftware
from backend.schemas.inventory import InventoryReport, SoftwareItem
from backend.services.software_normalizer import classify_software

# Sources whose reports come from inside the machine and are authoritative for
# its hardware identity and OS on the linked asset.
HOST_SOURCES = {"agent", "winrm", "wmi", "ssh"}


# ── parsing helpers ─────────────────────────────────────────────────────────
def parse_date(value: Optional[str]) -> Optional[date]:
    """ISO dates/datetimes, 20240115, and WMI's US-style 1/15/2024."""
    if not value:
        return None
    v = str(value).strip()
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", v)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return None
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})(?:\s.*)?", v)
    if m:
        try:
            return date(int(m[3]), int(m[1]), int(m[2]))
        except ValueError:
            return None
    return None


def parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        d = parse_date(value)
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc) if d else None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _clip(value: Any, n: int) -> Any:
    return value[:n] if isinstance(value, str) else value


def _volume_key(name: str) -> str:
    """'C:\\' and 'c:' are the same Windows volume; Unix mount points are kept."""
    n = name.strip()
    if re.fullmatch(r"[A-Za-z]:\\?", n):
        return n[0].upper() + ":"
    return n


# ── change recording ────────────────────────────────────────────────────────
@dataclass
class Change:
    category: str
    change_type: str             # added | removed | changed
    item: str
    field: Optional[str] = None
    old: Any = None
    new: Any = None
    severity: str = "info"


def _fmt(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def describe_change(c: DeviceChange) -> str:
    """One-line human summary (alert emails)."""
    if c.category == "account":
        if c.change_type == "added":
            return f"new local {'admin' if c.new_value == 'admin' else 'account'} {c.item}"
        if c.field == "admin":
            return f"{c.item} {'became' if c.new_value == 'yes' else 'is no longer'} a local admin"
    if c.change_type == "changed" and c.field in ("enabled", "encrypted"):
        state = {("enabled", "no"): "disabled", ("enabled", "yes"): "enabled",
                 ("encrypted", "no"): "no longer encrypted", ("encrypted", "yes"): "encrypted"}
        return f"{c.item} {state.get((c.field, c.new_value), c.new_value)}"
    if c.change_type == "changed":
        return f"{c.item}: {c.field} {c.old_value or '-'} -> {c.new_value or '-'}"
    return f"{c.item} {c.change_type}"


# ── generic keyed list sync ─────────────────────────────────────────────────
async def _sync_keyed(
    db: AsyncSession, model: Type, device_id: int, key_of: Callable[[Any], Any],
    reported: Dict[Any, Dict[str, Any]], now: datetime, remove_missing: bool = True,
) -> Tuple[List[Any], List[Any], List[Tuple[Any, str, Any, Any]]]:
    """Upsert `reported` (key -> column values) against stored rows.
    Returns (added_keys, removed_rows, changed[(key, field, old, new)]). Only
    the columns present in each reported dict are written."""
    rows = (await db.execute(select(model).where(model.device_id == device_id))).scalars().all()
    stored = {key_of(r): r for r in rows}
    added, changed = [], []
    for key, values in reported.items():
        row = stored.get(key)
        if row is None:
            db.add(model(device_id=device_id, last_seen=now, **values))
            added.append(key)
            continue
        for col, new in values.items():
            old = getattr(row, col)
            if old != new:
                changed.append((key, col, old, new))
                setattr(row, col, new)
        row.last_seen = now
    removed = [r for k, r in stored.items() if k not in reported] if remove_missing else []
    if removed:
        await db.execute(delete(model).where(model.id.in_([r.id for r in removed])))
    return added, removed, changed


# ── sections ────────────────────────────────────────────────────────────────
async def _sync_software(db: AsyncSession, device_id: int, items: List[SoftwareItem],
                         now: datetime, changes: List[Change]) -> Dict[str, int]:
    """Diff the reported list against what is stored. A title whose single
    version was replaced by another single version is an upgrade, updated in
    place, not a remove + add."""
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

    new_keys = [k for k in reported if k not in stored]
    gone = [s for k, s in stored.items() if k not in reported]

    # Upgrades: exactly one version disappeared and one appeared for a title.
    new_by_name: Dict[str, List[tuple]] = {}
    for k in new_keys:
        new_by_name.setdefault(k[0], []).append(k)
    gone_by_name: Dict[str, List[InstalledSoftware]] = {}
    for s in gone:
        gone_by_name.setdefault(s.name, []).append(s)
    upgraded = 0
    for name, olds in gone_by_name.items():
        news = new_by_name.get(name, [])
        if len(olds) == 1 and len(news) == 1:
            row, key = olds[0], news[0]
            changes.append(Change("software", "changed", name, "version", row.version, key[1]))
            row.version = key[1]
            row.last_seen = now
            if reported[key].publisher:
                row.publisher = reported[key].publisher[:255]
            stored[key] = row
            new_keys.remove(key)
            gone.remove(row)
            upgraded += 1

    if gone:
        await db.execute(delete(InstalledSoftware).where(InstalledSoftware.id.in_([s.id for s in gone])))
        changes.extend(Change("software", "removed", s.name, old=s.version) for s in gone)

    for key, row in stored.items():
        if key in reported and row not in gone:
            row.last_seen = now
            item = reported[key]
            if item.publisher and not row.publisher:
                row.publisher = item.publisher[:255]

    for key in new_keys:
        name, version = key
        item = reported[key]
        publisher = _clip(item.publisher, 255) or None
        cls = classify_software(name, publisher)
        db.add(InstalledSoftware(
            device_id=device_id, name=name, normalized_name=cls.product[:500], vendor=_clip(cls.publisher, 255),
            category=cls.category, version=version, publisher=publisher, last_seen=now,
        ))
        changes.append(Change("software", "added", name, new=version))

    return {"total": len(reported), "added": len(new_keys), "removed": len(gone), "upgraded": upgraded}


async def _sync_patches(db, device_id, report, now, changes):
    reported = {}
    for p in report.patches:
        pid = p.id.strip().upper()[:128]
        reported.setdefault(pid, {
            "patch_id": pid,
            "description": _clip(p.description, 255),
            "installed_on": parse_date(p.installed_on),
        })
    added, removed, _ = await _sync_keyed(db, DevicePatch, device_id, lambda r: r.patch_id, reported, now)
    changes.extend(Change("patch", "added", k) for k in added)
    changes.extend(Change("patch", "removed", r.patch_id) for r in removed)


async def _sync_services(db, device_id, report, now, changes):
    reported = {}
    for s in report.services:
        reported.setdefault(s.name[:255], {
            "name": s.name[:255], "display_name": _clip(s.display_name, 255),
            "state": _clip(s.state, 32), "start_mode": _clip(s.start_mode, 32),
            "account": _clip(s.account, 255),
        })
    added, removed, changed = await _sync_keyed(db, DeviceService, device_id, lambda r: r.name, reported, now)
    changes.extend(Change("service", "added", k) for k in added)
    changes.extend(Change("service", "removed", r.name) for r in removed)
    # Running/stopped flips constantly; only start-mode changes are worth a record.
    changes.extend(Change("service", "changed", k, f, o, n) for k, f, o, n in changed if f == "start_mode")


async def _sync_accounts(db, device_id, report, now, changes) -> int:
    reported = {}
    for a in report.local_accounts:
        reported.setdefault(a.name[:255], {
            "name": a.name[:255], "enabled": a.enabled, "is_admin": a.is_admin,
            "last_logon": parse_datetime(a.last_logon),
        })
    added, removed, changed = await _sync_keyed(db, DeviceLocalAccount, device_id, lambda r: r.name, reported, now)
    for k in added:
        admin = reported[k]["is_admin"]
        changes.append(Change("account", "added", k, new="admin" if admin else None,
                              severity="warning" if admin else "info"))
    changes.extend(Change("account", "removed", r.name) for r in removed)
    for k, f, o, n in changed:
        if f == "is_admin" and o is not None and n is not None:
            changes.append(Change("account", "changed", k, "admin", o, n, "warning" if n else "info"))
        elif f == "enabled" and o is not None and n is not None:
            changes.append(Change("account", "changed", k, "enabled", o, n))
    return sum(1 for v in reported.values() if v["is_admin"])


async def _sync_antivirus(db, device_id, products, now, changes) -> Optional[bool]:
    reported = {}
    for p in products:
        reported.setdefault(p.name[:255], {
            "name": p.name[:255], "enabled": p.enabled, "up_to_date": p.up_to_date,
            "definitions_date": parse_date(p.definitions_date),
        })
    added, removed, changed = await _sync_keyed(db, DeviceAntivirus, device_id, lambda r: r.name, reported, now)
    changes.extend(Change("security", "added", f"Antivirus {k}") for k in added)
    changes.extend(Change("security", "removed", f"Antivirus {r.name}", severity="warning") for r in removed)
    for k, f, o, n in changed:
        if f == "enabled" and o is not None and n is not None:
            changes.append(Change("security", "changed", f"Antivirus {k}", "enabled", o, n,
                                  "warning" if not n else "info"))
    vals = list(reported.values())
    if any(v["enabled"] and v["up_to_date"] is not False for v in vals):
        return True
    if any(v["enabled"] is None for v in vals):
        return None
    return False


async def _sync_volumes(db, device_id, report, now, changes) -> None:
    disks = report.disks
    enc = report.security.encryption if report.security else None
    enc_by_key = {_volume_key(e.volume): e for e in (enc or [])}
    reported: Dict[str, Dict[str, Any]] = {}
    for d in disks or []:
        values = {"name": _volume_key(d.name)[:255], "filesystem": _clip(d.filesystem, 32),
                  "size_gb": d.size_gb, "free_gb": d.free_gb}
        reported.setdefault(values["name"], values)
    for key, e in enc_by_key.items():
        values = reported.setdefault(key[:255], {"name": key[:255]})
        values.update({"encryption_method": _clip(e.method, 64), "encrypted": e.protected,
                       "encryption_status": _clip(e.status, 64)})
    # Volume membership is only authoritative when the disks section was collected.
    added, removed, changed = await _sync_keyed(
        db, DeviceVolume, device_id, lambda r: r.name, reported, now, remove_missing=disks is not None)
    for k, f, o, n in changed:
        if f == "encrypted" and o is not None and n is not None:
            changes.append(Change("security", "changed", f"Volume {k}", "encrypted", o, n,
                                  "warning" if not n else "info"))


async def _sync_nics(db, device_id, report, now, _changes):
    reported = {}
    for n in report.network_adapters:
        reported.setdefault(n.name[:255], {
            "name": n.name[:255], "mac": _clip((n.mac or "").upper() or None, 32),
            "ip_addresses": n.ip_addresses, "speed_mbps": n.speed_mbps, "dhcp": n.dhcp,
            "gateway": _clip(n.gateway, 64), "dns_servers": n.dns_servers,
        })
    # Addresses change with DHCP and Wi-Fi; stored, not logged as changes.
    await _sync_keyed(db, DeviceNetworkAdapter, device_id, lambda r: r.name, reported, now)


async def _sync_monitors(db, device_id, report, now, changes):
    reported = {}
    for m in report.monitors:
        key = (_clip(m.manufacturer, 255), _clip(m.model, 255), _clip(m.serial_number, 255))
        reported.setdefault(key, {"manufacturer": key[0], "model": key[1], "serial_number": key[2]})
    label = lambda k: " ".join(x for x in k if x) or "Monitor"  # noqa: E731
    added, removed, _ = await _sync_keyed(
        db, DeviceMonitor, device_id, lambda r: (r.manufacturer, r.model, r.serial_number), reported, now)
    changes.extend(Change("monitor", "added", label(k)) for k in added)
    changes.extend(Change("monitor", "removed", label((r.manufacturer, r.model, r.serial_number)))
                   for r in removed)


async def _sync_printers(db, device_id, report, now, _changes):
    reported = {}
    for p in report.printers:
        reported.setdefault(p.name[:255], {
            "name": p.name[:255], "driver": _clip(p.driver, 255), "port": _clip(p.port, 255),
            "is_network": p.is_network, "is_default": p.is_default,
        })
    await _sync_keyed(db, DevicePrinter, device_id, lambda r: r.name, reported, now)


# Summary columns whose change is recorded, by category, with display labels.
_TRACKED = {
    "hardware": {"manufacturer": "Manufacturer", "model": "Model", "cpu": "CPU", "cpu_cores": "CPU cores",
                 "ram_gb": "RAM (GB)", "disk_gb": "Disk capacity (GB)", "bios_version": "BIOS version"},
    "os": {"os_name": "Operating system", "os_version": "OS version", "os_build": "OS build"},
}


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        try:
            return round(float(a), 1) == round(float(b), 1)
        except (TypeError, ValueError):
            return False
    return a == b


def _apply_summary(inv: DeviceInventory, values: Dict[str, Any], category: Optional[str],
                   record: bool, changes: List[Change], fill_only: bool = False) -> None:
    for col, new in values.items():
        if new is None:
            continue   # unknown this time: keep what we had
        old = getattr(inv, col)
        if fill_only and old is not None:
            continue   # a non-authoritative source never overwrites what another source reported
        if old is not None and _same(old, new):
            continue   # rounding noise: keep the stored value so drift still adds up to a change
        if old is not None and record and category and col in _TRACKED[category]:
            changes.append(Change(category, "changed", _TRACKED[category][col], col, _fmt(old), _fmt(new)))
        setattr(inv, col, new)


def _firewall_ok(profiles) -> Optional[bool]:
    known = [p.enabled for p in profiles if p.enabled is not None]
    if not known:
        return None
    return all(known)


def _disk_encrypted(volumes: Iterable[DeviceVolume]) -> Optional[bool]:
    known = [v.encrypted for v in volumes if v.encrypted is not None]
    if not known:
        return None
    return all(known)


# ── virtual machines (reported by their hypervisor host) ───────────────────
_VM_VENDOR = {"vmware": ("VMware, Inc.", "VMware Virtual Platform"),
              "hyperv": ("Microsoft Corporation", "Virtual Machine")}


async def _sync_virtual_machines(db: AsyncSession, host: Device, vms, now: datetime) -> Dict[str, int]:
    """Create/merge each guest's device (non-authoritative), record which host
    it runs on, and keep automatic CMDB "hosts" edges between linked assets."""
    from backend.models.asset_relationship import AssetRelationship
    from backend.models.virtualization import VmPlacement

    vm_ids = []
    for vm in vms:
        vendor, model = _VM_VENDOR.get(vm.platform, (None, None))
        guest = (vm.guest_hostname or "").strip().rstrip(".")
        hostname, fqdn = (guest.split(".", 1)[0], guest) if "." in guest else (guest or vm.name, None)
        vm_report = InventoryReport(
            hostname=hostname, fqdn=fqdn, os_name=vm.guest_os,
            ip_addresses=vm.ip_addresses, mac_addresses=[m.upper() for m in vm.mac_addresses],
            hardware={"hardware_uuid": vm.uuid, "is_virtual": True, "chassis_type": "vm", "manufacturer": vendor,
                      "model": model, "cpu_cores": vm.vcpus, "cpu_logical": vm.vcpus, "ram_gb": vm.memory_gb,
                      "disk_gb": vm.disk_gb},
        )
        # Without a BIOS UUID, VM names alone would merge same-named guests on different hosts
        uid = None if vm.uuid else f"{vm.platform}-vm-{vm.instance_id or f'{host.id}-{vm.name}'}"
        result = await InventoryService.ingest(db, vm.platform, vm_report, authoritative=False, source_uid=uid)
        vm_id = result["device_id"]
        if vm_id == host.id:
            continue                              # a host can't run on itself (mis-matched identity)
        vm_ids.append(vm_id)
        placement = (await db.execute(select(VmPlacement).where(VmPlacement.vm_device_id == vm_id))).scalars().first()
        if placement is None:
            placement = VmPlacement(vm_device_id=vm_id)
            db.add(placement)
        placement.host_device_id, placement.platform, placement.vm_name = host.id, vm.platform, vm.name[:255]
        placement.instance_id, placement.power_state = _clip(vm.instance_id, 64), _clip(vm.power_state, 16)
        placement.guest_os, placement.vcpus = _clip(vm.guest_os, 255), vm.vcpus
        placement.memory_gb, placement.disk_gb = vm.memory_gb, vm.disk_gb
        placement.tools_status = _clip(vm.tools_status, 64)
        placement.cluster, placement.datacenter = _clip(vm.cluster, 255), _clip(vm.datacenter, 255)
        placement.last_seen = now

    # Guests no longer on this host (deleted, or migrated to a host not yet reported)
    await db.execute(delete(VmPlacement).where(VmPlacement.host_device_id == host.id,
                                               VmPlacement.vm_device_id.notin_(vm_ids or [-1])))
    await db.flush()

    # CMDB: host asset --hosts--> VM asset, for guests whose devices are linked to assets.
    # Only automatic edges (created_by NULL) are managed; manual edges are never touched.
    host_asset = (await db.execute(select(Asset.id).where(Asset.device_id == host.id).limit(1))).scalar()
    linked = 0
    if vm_ids:
        for vm_asset in (await db.execute(select(Asset.id).where(Asset.device_id.in_(vm_ids)))).scalars():
            await db.execute(delete(AssetRelationship).where(
                AssetRelationship.target_asset_id == vm_asset, AssetRelationship.relationship_type == "hosts",
                AssetRelationship.created_by.is_(None), AssetRelationship.source_asset_id != (host_asset or -1)))
            if host_asset is None or host_asset == vm_asset:
                continue
            exists_edge = (await db.execute(select(AssetRelationship.id).where(
                AssetRelationship.source_asset_id == host_asset, AssetRelationship.target_asset_id == vm_asset,
                AssetRelationship.relationship_type == "hosts"))).scalar()
            if not exists_edge:
                db.add(AssetRelationship(source_asset_id=host_asset, target_asset_id=vm_asset,
                                         relationship_type="hosts", created_by=None))
            linked += 1
    return {"total": len(vm_ids), "cmdb_links": linked}


# ── asset push ──────────────────────────────────────────────────────────────
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


def source_uid_for(source: str, report: InventoryReport) -> str:
    """Stable per-source identity. Prefers hardware identity over the hostname
    so a renamed machine stays the same DeviceSource."""
    hw = report.hardware
    uid = (hw and (hw.serial_number or hw.hardware_uuid)) or report.hostname or "unknown"
    return f"{source}-{uid}"


def _raw_record(source: str, report: InventoryReport, now: datetime,
                source_uid: Optional[str] = None) -> RawDeviceRecord:
    hw = report.hardware
    return {
        "source_uid": source_uid or source_uid_for(source, report),
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
            "collector_version": report.collector_version,
            "serial_number": hw.serial_number if hw else None,
            "hardware_uuid": hw.hardware_uuid if hw else None,
        },
    }


# ── entry point ─────────────────────────────────────────────────────────────
class InventoryService:
    @staticmethod
    async def ingest(db: AsyncSession, source: str, report: InventoryReport,
                     fallback_device_id: Optional[int] = None, authoritative: bool = True,
                     source_uid: Optional[str] = None) -> Dict[str, Any]:
        """Ingest one report. Flushes; the caller commits.

        `authoritative=False` is for descriptions of a device from outside it
        (a hypervisor describing its VM): no changes are recorded, and once the
        device's own agent or scan has reported a section, that section is only
        filled where it is empty, so the device itself stays the source of truth.
        `source_uid` overrides the per-source identity derived from the report."""
        now = datetime.now(timezone.utc)
        device, created = await Correlator.upsert_device(
            db, source, _raw_record(source, report, now, source_uid), fallback_device_id=fallback_device_id)

        inv = (await db.execute(
            select(DeviceInventory).where(DeviceInventory.device_id == device.id)
        )).scalars().first()
        if inv is None:
            inv = DeviceInventory(device_id=device.id, sections_collected=[])
            db.add(inv)
        seen = set(inv.sections_collected or [])
        changes: List[Change] = []
        collected: List[str] = []

        def section(name: str) -> List[Change]:
            """Change sink for a section: discarded on its baseline report."""
            collected.append(name)
            return changes if name in seen else []

        # Summary: hardware & OS
        hw = report.hardware
        if hw is not None:
            _apply_summary(inv, {
                "manufacturer": _clip(hw.manufacturer, 255), "model": _clip(hw.model, 255),
                "chassis_type": _clip(hw.chassis_type, 32), "is_virtual": hw.is_virtual,
                "cpu": _clip(hw.cpu, 255), "cpu_cores": hw.cpu_cores, "cpu_logical": hw.cpu_logical,
                "ram_gb": hw.ram_gb, "disk_gb": hw.disk_gb, "bios_vendor": _clip(hw.bios_vendor, 255),
                "bios_version": _clip(hw.bios_version, 255), "bios_date": _clip(hw.bios_date, 32),
                "motherboard": _clip(hw.motherboard, 255),
            }, "hardware", authoritative and "hardware" in seen, changes,
               fill_only=not authoritative and "hardware" in seen)
            if authoritative:
                collected.append("hardware")
        if report.os_name or report.os_version:
            _apply_summary(inv, {
                "os_name": _clip(report.os_name, 255), "os_version": _clip(report.os_version, 255),
                "os_build": _clip(report.os_build, 64), "architecture": _clip(report.architecture, 32),
            }, "os", authoritative and "os" in seen, changes, fill_only=not authoritative and "os" in seen)
            if authoritative:
                collected.append("os")
        _apply_summary(inv, {
            "last_boot": parse_datetime(report.last_boot),
            "logged_in_user": _clip(report.logged_in_user, 255),
            "pending_reboot": report.pending_reboot,
        }, None, False, changes)

        software = None
        if report.software is not None:
            software = await _sync_software(db, device.id, report.software, now, section("software"))
        if report.patches is not None:
            await _sync_patches(db, device.id, report, now, section("patches"))
        if report.services is not None:
            await _sync_services(db, device.id, report, now, section("services"))
        if report.local_accounts is not None:
            inv.local_admin_count = await _sync_accounts(db, device.id, report, now, section("local_accounts"))

        sec = report.security
        if sec is not None:
            if sec.antivirus is not None:
                inv.antivirus_ok = await _sync_antivirus(db, device.id, sec.antivirus, now, section("antivirus"))
            if sec.firewall is not None:
                sink = section("firewall")
                new_ok = _firewall_ok(sec.firewall)
                if inv.firewall_ok is not None and new_ok is not None and inv.firewall_ok != new_ok:
                    sink.append(Change("security", "changed", "Firewall", "enabled",
                                       _fmt(inv.firewall_ok), _fmt(new_ok), "warning" if not new_ok else "info"))
                inv.firewall_profiles = [p.model_dump() for p in sec.firewall]
                inv.firewall_ok = new_ok
            for col in ("tpm_present", "tpm_ready", "secure_boot"):
                if getattr(sec, col) is not None:
                    setattr(inv, col, getattr(sec, col))
        if report.disks is not None or (sec is not None and sec.encryption is not None):
            await _sync_volumes(db, device.id, report, now, section("volumes"))
            await db.flush()
            vols = (await db.execute(select(DeviceVolume).where(DeviceVolume.device_id == device.id))).scalars().all()
            inv.disk_encrypted = _disk_encrypted(vols)
        if report.network_adapters is not None:
            await _sync_nics(db, device.id, report, now, section("network_adapters"))
        if report.monitors is not None:
            await _sync_monitors(db, device.id, report, now, section("monitors"))
        if report.printers is not None:
            await _sync_printers(db, device.id, report, now, section("printers"))

        vms = None
        if report.virtual_machines is not None:
            vms = await _sync_virtual_machines(db, device, report.virtual_machines, now)

        if authoritative or inv.source is None:
            inv.source = source
            inv.collector_version = _clip(report.collector_version, 32) or inv.collector_version
            inv.collected_at = now
        inv.sections_collected = sorted(seen | set(collected))

        for c in changes:
            db.add(DeviceChange(
                device_id=device.id, category=c.category, change_type=c.change_type,
                item=str(c.item)[:500], field=c.field, old_value=_fmt(c.old), new_value=_fmt(c.new),
                severity=c.severity, source=source, detected_at=now,
            ))

        asset_updated = False
        if source in HOST_SOURCES:
            asset_updated = await _push_to_asset(db, device, report)

        await db.flush()
        from backend.services.lifecycle_service import LifecycleService
        await LifecycleService.refresh_device(db, device.id)
        return {
            "device_id": device.id,
            "device_created": created,
            "hostname": device.hostname,
            "software": software,
            "changes": len(changes),
            "warnings": sum(1 for c in changes if c.severity == "warning"),
            "asset_updated": asset_updated,
            "virtual_machines": vms,
        }
