"""Phase 1 inventory: per-section storage, baselines, change detection, posture flags."""
from datetime import date

from sqlalchemy import select

from backend.models.inventory import (
    DeviceChange, DeviceInventory, DeviceLocalAccount, DevicePatch, DeviceVolume,
)
from backend.models.software import InstalledSoftware
from backend.schemas.inventory import InventoryReport
from backend.services.inventory_service import InventoryService, parse_date

BASE = {
    "schema_version": 2, "collector_version": "2.0.0", "hostname": "PC-42",
    "os_name": "Microsoft Windows 11 Pro", "os_version": "10.0.22631", "os_build": "22631",
    "hardware": {"serial_number": "SN-42", "manufacturer": "Dell Inc.", "model": "Latitude 7440",
                 "ram_gb": 16.0, "cpu": "Intel Core i7-1365U"},
    "software": [{"name": "Zoom", "version": "5.17"}, {"name": "7-Zip", "version": "23.01"}],
    "patches": [{"id": "KB5034441", "installed_on": "1/15/2024"}],
    "local_accounts": [{"name": "Administrator", "enabled": False, "is_admin": True},
                       {"name": "alice", "enabled": True, "is_admin": False}],
    "security": {
        "antivirus": [{"name": "Microsoft Defender Antivirus", "enabled": True, "up_to_date": True}],
        "firewall": [{"profile": "Domain", "enabled": True}, {"profile": "Public", "enabled": True}],
        "encryption": [{"volume": "C:", "method": "BitLocker", "protected": True}],
        "secure_boot": True,
    },
    "disks": [{"name": "C:\\", "filesystem": "NTFS", "size_gb": 476.3, "free_gb": 120.5}],
}


def report(**overrides) -> InventoryReport:
    data = {**BASE, **overrides}
    return InventoryReport.model_validate(data)


def with_security(**sec) -> dict:
    return {"security": {**BASE["security"], **sec}}


async def ingest(db, rep):
    result = await InventoryService.ingest(db, "agent", rep)
    await db.commit()
    return result


async def changes(db):
    return (await db.execute(select(DeviceChange).order_by(DeviceChange.id))).scalars().all()


async def test_first_report_is_a_baseline(db_session):
    r = await ingest(db_session, report())
    assert r["changes"] == 0
    r = await ingest(db_session, report())
    assert r["changes"] == 0
    inv = (await db_session.execute(select(DeviceInventory))).scalars().one()
    assert (inv.antivirus_ok, inv.firewall_ok, inv.disk_encrypted, inv.local_admin_count) == (True, True, True, 1)
    assert inv.collector_version == "2.0.0" and "software" in inv.sections_collected
    vol = (await db_session.execute(select(DeviceVolume))).scalars().one()
    assert (vol.name, vol.size_gb, vol.encrypted) == ("C:", 476.3, True)   # disks + encryption merged
    patch = (await db_session.execute(select(DevicePatch))).scalars().one()
    assert patch.installed_on == date(2024, 1, 15)


async def test_software_upgrade_is_one_change_and_keeps_the_row(db_session):
    await ingest(db_session, report())
    zoom_id = (await db_session.execute(
        select(InstalledSoftware.id).where(InstalledSoftware.name == "Zoom"))).scalar_one()
    r = await ingest(db_session, report(software=[{"name": "Zoom", "version": "5.18"},
                                                  {"name": "7-Zip", "version": "23.01"},
                                                  {"name": "Slack", "version": "4.36"}]))
    assert r["software"]["upgraded"] == 1 and r["software"]["added"] == 1
    got = [(c.category, c.change_type, c.item, c.old_value, c.new_value) for c in await changes(db_session)]
    assert ("software", "changed", "Zoom", "5.17", "5.18") in got
    assert ("software", "added", "Slack", None, "4.36") in got
    assert len(got) == 2
    assert (await db_session.execute(
        select(InstalledSoftware.id).where(InstalledSoftware.name == "Zoom"))).scalar_one() == zoom_id


async def test_new_local_admin_is_a_warning(db_session):
    await ingest(db_session, report())
    r = await ingest(db_session, report(local_accounts=[
        {"name": "Administrator", "enabled": False, "is_admin": True},
        {"name": "alice", "enabled": True, "is_admin": True},       # promoted
        {"name": "mallory", "enabled": True, "is_admin": True},     # new admin
    ]))
    assert r["warnings"] == 2
    got = {(c.change_type, c.item, c.severity) for c in await changes(db_session)}
    assert got == {("changed", "alice", "warning"), ("added", "mallory", "warning")}
    inv = (await db_session.execute(select(DeviceInventory))).scalars().one()
    assert inv.local_admin_count == 3


async def test_security_regressions_are_warnings(db_session):
    await ingest(db_session, report())
    r = await ingest(db_session, report(**with_security(
        antivirus=[{"name": "Microsoft Defender Antivirus", "enabled": False, "up_to_date": True}],
        firewall=[{"profile": "Domain", "enabled": True}, {"profile": "Public", "enabled": False}],
        encryption=[{"volume": "C:", "method": "BitLocker", "protected": False}],
    )))
    assert r["warnings"] == 3
    items = {c.item for c in await changes(db_session)}
    assert items == {"Antivirus Microsoft Defender Antivirus", "Firewall", "Volume C:"}
    inv = (await db_session.execute(select(DeviceInventory))).scalars().one()
    assert (inv.antivirus_ok, inv.firewall_ok, inv.disk_encrypted) == (False, False, False)


async def test_hardware_change_ignores_rounding_noise(db_session):
    await ingest(db_session, report())
    await ingest(db_session, report(hardware={**BASE["hardware"], "ram_gb": 16.04}))
    assert await changes(db_session) == []
    await ingest(db_session, report(hardware={**BASE["hardware"], "ram_gb": 32.0}))
    (c,) = await changes(db_session)
    assert (c.category, c.item, c.old_value, c.new_value) == ("hardware", "RAM (GB)", "16", "32")


async def test_uncollected_sections_are_left_alone(db_session):
    await ingest(db_session, report())
    partial = {k: v for k, v in BASE.items() if k not in ("patches", "local_accounts", "security", "disks")}
    r = await ingest(db_session, InventoryReport.model_validate(partial))
    assert r["changes"] == 0
    assert len((await db_session.execute(select(DevicePatch))).scalars().all()) == 1
    assert len((await db_session.execute(select(DeviceLocalAccount))).scalars().all()) == 2
    inv = (await db_session.execute(select(DeviceInventory))).scalars().one()
    assert inv.antivirus_ok is True and inv.disk_encrypted is True


async def test_section_first_seen_later_is_still_a_baseline(db_session):
    # v1 agents never sent patches; the first v2 report must not log every KB.
    first = {k: v for k, v in BASE.items() if k != "patches"}
    await ingest(db_session, InventoryReport.model_validate(first))
    r = await ingest(db_session, report(patches=[{"id": f"KB{i}"} for i in range(50)]))
    assert r["changes"] == 0
    r = await ingest(db_session, report(patches=[{"id": f"KB{i}"} for i in range(51)]))
    assert r["changes"] == 1


async def test_unknown_antivirus_state_is_not_reported_as_missing(db_session):
    await ingest(db_session, report(**with_security(antivirus=[{"name": "SentinelOne"}])))
    inv = (await db_session.execute(select(DeviceInventory))).scalars().one()
    assert inv.antivirus_ok is None
    await ingest(db_session, report(**with_security(antivirus=[])))
    await db_session.refresh(inv)
    assert inv.antivirus_ok is False


def test_parse_date_formats():
    assert parse_date("2024-01-15") == date(2024, 1, 15)
    assert parse_date("2024-01-15T08:30:00Z") == date(2024, 1, 15)
    assert parse_date("20240115") == date(2024, 1, 15)
    assert parse_date("1/15/2024") == date(2024, 1, 15)
    assert parse_date("not a date") is None and parse_date(None) is None
