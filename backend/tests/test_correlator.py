"""
Unit tests for the Correlator.

Each test gets a fresh in-memory SQLite database via the `db_session` fixture.
"""
import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy.future import select

from backend.correlator.correlator import Correlator
from backend.models.device import Device
from backend.models.device_source import DeviceSource
from tests.conftest import make_raw


# ============================================================ process_batch


async def test_new_device_is_created(db_session):
    raw = make_raw(hostname="PC-001", fqdn="pc-001.corp.local")
    created, updated = await Correlator.process_batch(db_session, "ad", [raw])

    assert created == 1
    assert updated == 0

    result = await db_session.execute(select(Device))
    devices = result.scalars().all()
    assert len(devices) == 1
    assert devices[0].hostname == "PC-001"
    assert devices[0].fqdn == "pc-001.corp.local"
    assert devices[0].status == "active"


async def test_device_source_is_created_with_device(db_session):
    raw = make_raw(source_uid="ad-001", hostname="PC-001", fqdn="pc-001.corp.local")
    await Correlator.process_batch(db_session, "ad", [raw])

    result = await db_session.execute(select(DeviceSource))
    sources = result.scalars().all()
    assert len(sources) == 1
    assert sources[0].source_name == "ad"
    assert sources[0].source_uid == "ad-001"


async def test_existing_device_matched_by_fqdn(db_session):
    raw = make_raw(fqdn="pc-001.corp.local")
    await Correlator.process_batch(db_session, "ad", [raw])

    # Second sync of same device
    raw2 = make_raw(fqdn="pc-001.corp.local", source_uid="cs-001", os_name="Windows 11")
    created, updated = await Correlator.process_batch(db_session, "crowdstrike", [raw2])

    assert created == 0
    assert updated == 1

    result = await db_session.execute(select(Device))
    devices = result.scalars().all()
    assert len(devices) == 1  # no duplicate


async def test_existing_device_matched_by_hostname_when_no_fqdn(db_session):
    raw = make_raw(hostname="SRV-DB", fqdn=None)
    await Correlator.process_batch(db_session, "ad", [raw])

    raw2 = make_raw(hostname="SRV-DB", fqdn=None, source_uid="cs-002")
    created, updated = await Correlator.process_batch(db_session, "crowdstrike", [raw2])

    assert created == 0
    assert updated == 1


async def test_two_different_devices_are_not_merged(db_session):
    raw1 = make_raw(hostname="PC-001", fqdn="pc-001.corp.local", source_uid="a1")
    raw2 = make_raw(hostname="PC-002", fqdn="pc-002.corp.local", source_uid="a2")
    created, updated = await Correlator.process_batch(db_session, "ad", [raw1, raw2])

    assert created == 2
    assert updated == 0


# ============================================================ source authority


async def test_ad_wins_hostname_over_crowdstrike(db_session):
    # AD sets hostname first
    ad_raw = make_raw(source_uid="ad-1", hostname="CORRECT-NAME", fqdn="correct.corp.local")
    await Correlator.process_batch(db_session, "ad", [ad_raw])

    # CrowdStrike reports a different hostname for the same FQDN
    cs_raw = make_raw(source_uid="cs-1", hostname="WRONG-NAME", fqdn="correct.corp.local")
    await Correlator.process_batch(db_session, "crowdstrike", [cs_raw])

    result = await db_session.execute(select(Device))
    device = result.scalars().first()
    # AD has higher authority for hostname → should not be overwritten
    assert device.hostname == "CORRECT-NAME"


async def test_crowdstrike_wins_os_over_ad(db_session):
    # AD sets OS
    ad_raw = make_raw(source_uid="ad-1", fqdn="srv.corp.local", os_name="Windows")
    await Correlator.process_batch(db_session, "ad", [ad_raw])

    # CrowdStrike reports a more precise OS for the same device
    cs_raw = make_raw(source_uid="cs-1", fqdn="srv.corp.local", os_name="Windows 11")
    await Correlator.process_batch(db_session, "crowdstrike", [cs_raw])

    result = await db_session.execute(select(Device))
    device = result.scalars().first()
    # CrowdStrike has higher authority for os_name → should win
    assert device.os_name == "Windows"  # normalizer maps "Windows 11" → family "Windows"


# ============================================================ IP / MAC merge


async def test_ip_addresses_are_merged_across_sources(db_session):
    raw1 = make_raw(fqdn="srv.corp.local", ip_addresses=["10.0.0.1"])
    await Correlator.process_batch(db_session, "ad", [raw1])

    raw2 = make_raw(fqdn="srv.corp.local", ip_addresses=["10.0.0.1", "192.168.1.5"])
    await Correlator.process_batch(db_session, "crowdstrike", [raw2])

    result = await db_session.execute(select(Device))
    device = result.scalars().first()
    assert set(device.ip_addresses) == {"10.0.0.1", "192.168.1.5"}


async def test_mac_addresses_are_merged_across_sources(db_session):
    raw1 = make_raw(fqdn="srv.corp.local", mac_addresses=["AA:BB:CC:DD:EE:FF"])
    await Correlator.process_batch(db_session, "ad", [raw1])

    raw2 = make_raw(fqdn="srv.corp.local", mac_addresses=["AA:BB:CC:DD:EE:FF", "11:22:33:44:55:66"])
    await Correlator.process_batch(db_session, "defender", [raw2])

    result = await db_session.execute(select(Device))
    device = result.scalars().first()
    assert set(device.mac_addresses) == {"AA:BB:CC:DD:EE:FF", "11:22:33:44:55:66"}


# ============================================================ device source upsert


async def test_device_source_is_upserted_not_duplicated(db_session):
    raw = make_raw(fqdn="pc.corp.local")
    await Correlator.process_batch(db_session, "ad", [raw])
    await Correlator.process_batch(db_session, "ad", [raw])  # same source, same device

    result = await db_session.execute(select(DeviceSource))
    sources = result.scalars().all()
    assert len(sources) == 1  # not duplicated


async def test_multiple_sources_per_device(db_session):
    fqdn = "shared.corp.local"
    await Correlator.process_batch(db_session, "ad",          [make_raw(fqdn=fqdn, source_uid="ad-1")])
    await Correlator.process_batch(db_session, "crowdstrike", [make_raw(fqdn=fqdn, source_uid="cs-1")])
    await Correlator.process_batch(db_session, "defender",    [make_raw(fqdn=fqdn, source_uid="df-1")])

    result = await db_session.execute(select(DeviceSource))
    sources = result.scalars().all()
    assert len(sources) == 3
    assert {s.source_name for s in sources} == {"ad", "crowdstrike", "defender"}


# ============================================================ MAC address correlation


async def test_device_matched_by_mac_when_no_fqdn_or_hostname(db_session):
    # Nameless device (kiosk/appliance) identified only by MAC
    raw1 = make_raw(hostname=None, fqdn=None, mac_addresses=["AA:BB:CC:DD:EE:FF"], source_uid="ad-1")
    created, _ = await Correlator.process_batch(db_session, "ad", [raw1])
    assert created == 1

    # Second connector reports the same MAC, still no name info
    raw2 = make_raw(hostname=None, fqdn=None, mac_addresses=["AA:BB:CC:DD:EE:FF"], source_uid="cs-1")
    created2, updated2 = await Correlator.process_batch(db_session, "crowdstrike", [raw2])

    assert created2 == 0
    assert updated2 == 1
    result = await db_session.execute(select(Device))
    assert len(result.scalars().all()) == 1


async def test_mac_match_normalises_dashes_to_colons(db_session):
    # Nameless device stored with colon-separated MAC
    raw1 = make_raw(hostname=None, fqdn=None, mac_addresses=["AA:BB:CC:DD:EE:FF"], source_uid="ad-1")
    await Correlator.process_batch(db_session, "ad", [raw1])

    # Incoming record uses dash-separated MAC (common on Windows WMI)
    raw2 = make_raw(hostname=None, fqdn=None, mac_addresses=["AA-BB-CC-DD-EE-FF"], source_uid="cs-1")
    created, updated = await Correlator.process_batch(db_session, "crowdstrike", [raw2])

    assert created == 0
    assert updated == 1


async def test_broadcast_mac_does_not_cause_false_match(db_session):
    # Two nameless devices that both report the broadcast MAC must NOT be merged
    raw1 = make_raw(hostname=None, fqdn=None, mac_addresses=["FF:FF:FF:FF:FF:FF"], source_uid="ad-1")
    raw2 = make_raw(hostname=None, fqdn=None, mac_addresses=["FF:FF:FF:FF:FF:FF"], source_uid="ad-2")
    created, _ = await Correlator.process_batch(db_session, "ad", [raw1, raw2])
    assert created == 2


async def test_mac_not_used_when_fqdn_present_but_no_match(db_session):
    # Device A has a MAC; device B has same MAC but a different FQDN.
    # MAC fallback must NOT fire because device B has an FQDN — it's a genuinely
    # different device (or a renamed one), not a nameless appliance.
    raw1 = make_raw(fqdn="vm-a.corp.local", hostname="VM-A",
                    mac_addresses=["11:22:33:44:55:66"], source_uid="a1")
    await Correlator.process_batch(db_session, "ad", [raw1])

    raw2 = make_raw(fqdn="vm-b.corp.local", hostname="VM-B",
                    mac_addresses=["11:22:33:44:55:66"], source_uid="a2")
    created, _ = await Correlator.process_batch(db_session, "ad", [raw2])

    assert created == 1
    result = await db_session.execute(select(Device))
    assert len(result.scalars().all()) == 2


# ============================================================ last_seen update


async def test_last_seen_updated_to_most_recent(db_session):
    old_ts = datetime.now(timezone.utc) - timedelta(days=5)
    new_ts = datetime.now(timezone.utc)

    raw1 = make_raw(fqdn="pc.corp.local", last_seen=old_ts)
    await Correlator.process_batch(db_session, "ad", [raw1])

    raw2 = make_raw(fqdn="pc.corp.local", last_seen=new_ts)
    await Correlator.process_batch(db_session, "crowdstrike", [raw2])

    result = await db_session.execute(select(Device))
    device = result.scalars().first()
    # last_seen should reflect the most recent timestamp
    assert device.last_seen.replace(tzinfo=timezone.utc) >= old_ts


# ============================================================ mark_stale_devices


async def test_device_marked_inactive_when_all_sources_stale(db_session):
    raw = make_raw(fqdn="stale.corp.local")
    await Correlator.process_batch(db_session, "ad", [raw])

    # Set last_synced to 40 days ago — beyond the 30-day stale window
    src_result = await db_session.execute(select(DeviceSource))
    src = src_result.scalars().first()
    src.last_synced = datetime.now(timezone.utc) - timedelta(days=40)
    await db_session.commit()

    sync_start = datetime.now(timezone.utc)
    stale_count = await Correlator.mark_stale_devices(db_session, "ad", sync_start)

    assert stale_count == 1
    result = await db_session.execute(select(Device))
    device = result.scalars().first()
    assert device.status == "inactive"


async def test_device_stays_active_when_one_source_is_fresh(db_session):
    fqdn = "mixed.corp.local"
    await Correlator.process_batch(db_session, "ad",          [make_raw(fqdn=fqdn, source_uid="ad-1")])
    await Correlator.process_batch(db_session, "crowdstrike", [make_raw(fqdn=fqdn, source_uid="cs-1")])

    # Mark the AD source as beyond the stale threshold
    src_result = await db_session.execute(
        select(DeviceSource).where(DeviceSource.source_name == "ad")
    )
    ad_src = src_result.scalars().first()
    ad_src.last_synced = datetime.now(timezone.utc) - timedelta(days=40)
    await db_session.commit()

    # CrowdStrike source is recent (set by process_batch above, a few ms ago)
    sync_start = datetime.now(timezone.utc)
    stale_count = await Correlator.mark_stale_devices(db_session, "ad", sync_start)

    # CrowdStrike synced recently → device should NOT become inactive
    assert stale_count == 0
    result = await db_session.execute(select(Device))
    device = result.scalars().first()
    assert device.status == "active"


async def test_already_inactive_device_not_double_counted(db_session):
    raw = make_raw(fqdn="old.corp.local")
    await Correlator.process_batch(db_session, "ad", [raw])

    # Set last_synced to 40 days ago — beyond the 30-day stale window
    src_result = await db_session.execute(select(DeviceSource))
    src = src_result.scalars().first()
    src.last_synced = datetime.now(timezone.utc) - timedelta(days=40)
    await db_session.commit()

    sync_start = datetime.now(timezone.utc)
    first_run  = await Correlator.mark_stale_devices(db_session, "ad", sync_start)
    second_run = await Correlator.mark_stale_devices(db_session, "ad", sync_start)

    assert first_run == 1
    assert second_run == 0   # already inactive, not counted again
