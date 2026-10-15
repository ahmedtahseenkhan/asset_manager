"""Hardware-identity matching and source authority (agent / credentialed scans)."""
from sqlalchemy.future import select

from backend.correlator.correlator import Correlator, hardware_identity
from backend.models.device import Device
from tests.conftest import make_raw


async def _devices(db):
    return (await db.execute(select(Device))).scalars().all()


async def test_same_serial_merges_renamed_machine(db_session):
    await Correlator.process_batch(db_session, "agent", [
        make_raw(source_uid="a-1", hostname="OLD-NAME", fqdn=None, extra={"serial_number": "5CG1234XYZ"}),
    ])
    await Correlator.process_batch(db_session, "wmi", [
        make_raw(source_uid="w-1", hostname="NEW-NAME", fqdn=None, extra={"serial_number": "5CG1234XYZ"}),
    ])
    devices = await _devices(db_session)
    assert len(devices) == 1
    assert devices[0].serial_number == "5CG1234XYZ"


async def test_hardware_uuid_takes_precedence_over_hostname(db_session):
    uuid = "4c4c4544-0042-3510-8051-b4c04f4e3332"
    await Correlator.process_batch(db_session, "agent", [
        make_raw(source_uid="a-1", hostname="PC-A", fqdn=None, extra={"hardware_uuid": uuid.upper()}),
    ])
    await Correlator.process_batch(db_session, "ssh", [
        make_raw(source_uid="s-1", hostname="PC-B", fqdn=None, extra={"hardware_uuid": uuid}),
    ])
    devices = await _devices(db_session)
    assert len(devices) == 1
    assert devices[0].hardware_uuid == uuid


async def test_placeholder_serials_never_merge_machines(db_session):
    await Correlator.process_batch(db_session, "agent", [
        make_raw(source_uid="a-1", hostname="PC-1", fqdn=None, mac_addresses=["AA:00:00:00:00:01"],
                 extra={"serial_number": "To be filled by O.E.M."}),
        make_raw(source_uid="a-2", hostname="PC-2", fqdn=None, mac_addresses=["AA:00:00:00:00:02"],
                 extra={"serial_number": "To be filled by O.E.M."}),
    ])
    devices = await _devices(db_session)
    assert len(devices) == 2
    assert all(d.serial_number is None for d in devices)


def test_hardware_identity_filters_placeholders():
    assert hardware_identity(make_raw(extra={"serial_number": "00000000"})) == (None, None)
    assert hardware_identity(make_raw(extra={"serial_number": " Default string "})) == (None, None)
    assert hardware_identity(make_raw(
        extra={"hardware_uuid": "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF"})) == (None, None)
    assert hardware_identity(make_raw(extra={"serial_number": "C02XL0GHJGH5"})) == ("C02XL0GHJGH5", None)


async def test_agent_os_beats_active_directory(db_session):
    await Correlator.process_batch(db_session, "ad", [
        make_raw(source_uid="ad-1", hostname="PC-001", os_name="Windows 10 Pro", os_version="10"),
    ])
    await Correlator.process_batch(db_session, "agent", [
        make_raw(source_uid="ag-1", hostname="PC-001", os_name="Windows 11 Pro", os_version="11"),
    ])
    # A later AD sync must not overwrite what the machine itself reported.
    await Correlator.process_batch(db_session, "ad", [
        make_raw(source_uid="ad-1", hostname="PC-001", os_name="Windows 10 Pro", os_version="10"),
    ])
    (device,) = await _devices(db_session)
    assert device.os_version == "11"


async def test_upsert_device_returns_device_without_committing(db_session):
    device, created = await Correlator.upsert_device(db_session, "agent", make_raw(source_uid="x"))
    assert created and device.id is not None
    await db_session.rollback()
    assert await _devices(db_session) == []
