"""Virtual machines reported by their hypervisor: guest devices, placements,
merging with the guest's own agent, and automatic CMDB "hosts" edges."""
from sqlalchemy import select

from backend.correlator.correlator import uuid_variants
from backend.models.asset import Asset
from backend.models.asset_relationship import AssetRelationship
from backend.models.device import Device
from backend.models.inventory import DeviceInventory
from backend.models.user import User
from backend.models.virtualization import VmPlacement
from backend.schemas.inventory import InventoryReport
from backend.services.inventory_service import InventoryService

SQL01_UUID = "4C4C4544-0042-3510-8051-C7C04F4E3332"
# The same UUID as Windows inside the guest may show it: first three groups byte-swapped
SQL01_UUID_SWAPPED = "44454c4c-4200-1035-8051-c7c04f4e3332"


def _vm(name, uuid=None, **kw):
    return {"name": name, "platform": "hyperv", "uuid": uuid, "instance_id": kw.pop("instance_id", None),
            "power_state": "on", "vcpus": 4, "memory_gb": 8.0, "disk_gb": 627.0, **kw}


def _host(hostname, serial, vms):
    return InventoryReport.model_validate({
        "hostname": hostname, "os_name": "Microsoft Windows Server 2022 Datacenter",
        "hardware": {"serial_number": serial, "manufacturer": "Dell Inc.", "model": "PowerEdge R750"},
        "virtual_machines": vms,
    })


async def _ingest_host(db, hostname, serial, vms):
    result = await InventoryService.ingest(db, "agent", _host(hostname, serial, vms))
    await db.commit()
    return result


async def _placements(db):
    rows = (await db.execute(select(VmPlacement))).scalars().all()
    return {r.vm_name: r for r in rows}


async def _device(db, device_id):
    return (await db.execute(select(Device).where(Device.id == device_id))).scalars().one()


async def _inventory(db, device_id):
    return (await db.execute(select(DeviceInventory).where(DeviceInventory.device_id == device_id))).scalars().one()


def test_uuid_variants_include_the_byte_swapped_twin():
    assert uuid_variants(SQL01_UUID) == {SQL01_UUID.lower(), SQL01_UUID_SWAPPED}
    assert uuid_variants("not-a-uuid") == {"not-a-uuid"}


async def test_host_report_creates_guest_devices_and_placements(db_session):
    host = await _ingest_host(db_session, "HV01", "HOSTSN1", [
        _vm("SQL01", SQL01_UUID, instance_id="aaaa1111-0000-0000-0000-000000000001",
            guest_hostname="sql01.corp.local", guest_os="Windows Server 2022 Datacenter",
            tools_status="Up to date", ip_addresses=["10.0.5.21"], mac_addresses=["00:15:5d:0a:0b:0c"]),
        _vm("old-build", "11112222-3333-4444-5555-666677778888", power_state="off", vcpus=2, memory_gb=2.0),
    ])
    assert host["virtual_machines"] == {"total": 2, "cmdb_links": 0}

    placements = await _placements(db_session)
    assert set(placements) == {"SQL01", "old-build"}
    sql = placements["SQL01"]
    assert (sql.host_device_id, sql.platform, sql.power_state, sql.tools_status) == (
        host["device_id"], "hyperv", "on", "Up to date")
    assert placements["old-build"].power_state == "off"

    guest = await _device(db_session, sql.vm_device_id)
    assert (guest.hostname, guest.fqdn) == ("SQL01", "sql01.corp.local")
    assert guest.hardware_uuid == SQL01_UUID.lower()
    assert guest.mac_addresses == ["00:15:5D:0A:0B:0C"]
    inv = await _inventory(db_session, guest.id)
    assert (inv.is_virtual, inv.chassis_type, inv.manufacturer, inv.cpu_cores, inv.ram_gb) == (
        True, "vm", "Microsoft Corporation", 4, 8.0)
    assert inv.os_name == "Windows Server 2022 Datacenter"
    assert inv.source == "hyperv"
    assert inv.sections_collected == []          # the hypervisor's view isn't the guest's own inventory

    # Guests without a guest hostname are named after the VM
    assert (await _device(db_session, placements["old-build"].vm_device_id)).hostname == "OLD-BUILD"


async def test_guest_agent_merges_with_the_hypervisor_view(db_session):
    await _ingest_host(db_session, "HV01", "HOSTSN1", [_vm("SQL01", SQL01_UUID, guest_hostname="sql01.corp.local")])
    vm_device_id = (await _placements(db_session))["SQL01"].vm_device_id

    # The agent inside the VM reports the UUID byte-swapped and a different VM serial
    agent = await InventoryService.ingest(db_session, "agent", InventoryReport.model_validate({
        "hostname": "SQL01", "os_name": "Microsoft Windows Server 2022 Datacenter",
        "hardware": {"serial_number": "0000-0017-0412-3511", "hardware_uuid": SQL01_UUID_SWAPPED,
                     "manufacturer": "Microsoft Corporation", "model": "Virtual Machine", "ram_gb": 16.0},
    }))
    await db_session.commit()
    assert agent["device_id"] == vm_device_id
    assert len((await db_session.execute(select(Device))).scalars().all()) == 2

    # From now on the hypervisor fills gaps but never overwrites what the guest reported
    await _ingest_host(db_session, "HV01", "HOSTSN1", [
        _vm("SQL01", SQL01_UUID, guest_hostname="sql01.corp.local", memory_gb=4.0, guest_os="Windows")])
    inv = await _inventory(db_session, vm_device_id)
    assert inv.ram_gb == 16.0
    assert inv.os_name == "Microsoft Windows Server 2022 Datacenter"
    assert inv.source == "agent"
    assert inv.cpu_cores == 4                    # not reported by the agent: filled from the hypervisor


async def test_hypervisor_updates_guests_without_an_agent(db_session):
    await _ingest_host(db_session, "HV01", "HOSTSN1", [_vm("web01", "aaaaaaaa-0000-0000-0000-000000000001")])
    vm_device_id = (await _placements(db_session))["web01"].vm_device_id
    await _ingest_host(db_session, "HV01", "HOSTSN1", [
        _vm("web01", "aaaaaaaa-0000-0000-0000-000000000001", vcpus=8, memory_gb=32.0)])
    inv = await _inventory(db_session, vm_device_id)
    assert (inv.cpu_cores, inv.ram_gb) == (8, 32.0)     # resized VM picked up


async def test_removed_and_migrated_guests(db_session):
    a = await _ingest_host(db_session, "HV01", "HOSTSN1", [
        _vm("web01", "aaaaaaaa-0000-0000-0000-000000000001"), _vm("web02", "aaaaaaaa-0000-0000-0000-000000000002")])

    # web01 live-migrates to HV02; HV02 reports before HV01 does
    b = await _ingest_host(db_session, "HV02", "HOSTSN2", [_vm("web01", "aaaaaaaa-0000-0000-0000-000000000001")])
    assert (await _placements(db_session))["web01"].host_device_id == b["device_id"]

    # HV01 now reports only web02: web01 stays on HV02, web02 on HV01
    await _ingest_host(db_session, "HV01", "HOSTSN1", [_vm("web02", "aaaaaaaa-0000-0000-0000-000000000002")])
    placements = await _placements(db_session)
    assert {n: p.host_device_id for n, p in placements.items()} == {"web01": b["device_id"], "web02": a["device_id"]}

    # A deleted VM loses its placement but its device (and history) remain
    await _ingest_host(db_session, "HV01", "HOSTSN1", [])
    placements = await _placements(db_session)
    assert set(placements) == {"web01"}
    assert len((await db_session.execute(select(Device))).scalars().all()) == 4


async def test_same_named_guests_with_different_uuids_stay_separate(db_session):
    await _ingest_host(db_session, "HV01", "HOSTSN1", [_vm("test", "aaaaaaaa-0000-0000-0000-000000000001")])
    await _ingest_host(db_session, "HV02", "HOSTSN2", [_vm("test", "aaaaaaaa-0000-0000-0000-000000000002")])
    rows = (await db_session.execute(select(VmPlacement))).scalars().all()
    assert len(rows) == 2 and rows[0].vm_device_id != rows[1].vm_device_id

    # Each guest's own agent lands on its own device, not the first "TEST"
    hv02 = (await db_session.execute(select(Device.id).where(Device.hostname == "HV02"))).scalar_one()
    second = next(r for r in rows if r.host_device_id == hv02)
    agent = await InventoryService.ingest(db_session, "agent", InventoryReport.model_validate({
        "hostname": "test", "hardware": {"hardware_uuid": "aaaaaaaa-0000-0000-0000-000000000002"}}))
    assert agent["device_id"] == second.vm_device_id


async def test_renamed_guest_without_uuid_keeps_its_device(db_session):
    await _ingest_host(db_session, "HV01", "HOSTSN1", [_vm("app-old", instance_id="11111111-aaaa-0000-0000-000000000001")])
    before = (await _placements(db_session))["app-old"].vm_device_id
    await _ingest_host(db_session, "HV01", "HOSTSN1", [_vm("app-new", instance_id="11111111-aaaa-0000-0000-000000000001")])
    assert (await _placements(db_session))["app-new"].vm_device_id == before


async def test_a_guest_resolving_to_the_host_itself_is_skipped(db_session):
    host = await _ingest_host(db_session, "HV01", "HOSTSN1", [])
    host_device = await _device(db_session, host["device_id"])
    host_device.hardware_uuid = "bbbbbbbb-0000-0000-0000-000000000001"
    await db_session.commit()
    result = await _ingest_host(db_session, "HV01", "HOSTSN1", [_vm("weird", "BBBBBBBB-0000-0000-0000-000000000001")])
    assert result["virtual_machines"]["total"] == 0
    assert await _placements(db_session) == {}


async def test_cmdb_hosts_edges_follow_the_guest(db_session):
    a = await _ingest_host(db_session, "HV01", "HOSTSN1", [_vm("web01", "aaaaaaaa-0000-0000-0000-000000000001")])
    b = await _ingest_host(db_session, "HV02", "HOSTSN2", [])
    vm_device_id = (await _placements(db_session))["web01"].vm_device_id
    user = User(username="admin", email="admin@example.com", hashed_password="x", role="admin")
    hv1, hv2, web = (Asset(name=n, asset_tag=t, category="hardware", asset_type="server", device_id=d)
                     for n, t, d in [("HV01", "AST-1", a["device_id"]), ("HV02", "AST-2", b["device_id"]),
                                     ("web01", "AST-3", vm_device_id)])
    db_session.add_all([user, hv1, hv2, web])
    await db_session.commit()

    async def edges():
        rows = (await db_session.execute(select(AssetRelationship))).scalars().all()
        return {(r.source_asset_id, r.target_asset_id, r.relationship_type, r.created_by is None) for r in rows}

    result = await _ingest_host(db_session, "HV01", "HOSTSN1", [_vm("web01", "aaaaaaaa-0000-0000-0000-000000000001")])
    assert result["virtual_machines"]["cmdb_links"] == 1
    assert await edges() == {(hv1.id, web.id, "hosts", True)}

    # Reporting again doesn't duplicate the edge
    await _ingest_host(db_session, "HV01", "HOSTSN1", [_vm("web01", "aaaaaaaa-0000-0000-0000-000000000001")])
    assert len(await edges()) == 1

    # A manual edge someone drew stays put; the automatic one moves with the VM
    db_session.add(AssetRelationship(source_asset_id=web.id, target_asset_id=hv1.id,
                                     relationship_type="depends_on", created_by=user.id))
    await db_session.commit()
    await _ingest_host(db_session, "HV02", "HOSTSN2", [_vm("web01", "aaaaaaaa-0000-0000-0000-000000000001")])
    assert await edges() == {(hv2.id, web.id, "hosts", True), (web.id, hv1.id, "depends_on", False)}


async def test_agent_report_with_guests_through_the_api(api):
    from tests.test_inventory_ingest import _post, _setup_token
    await _setup_token(api)
    r = await _post(api, {
        "schema_version": 2, "collector_version": "2.1.0", "hostname": "HV01",
        "hardware": {"serial_number": "HOSTSN1"},
        "virtual_machines": [
            _vm("SQL01", SQL01_UUID, guest_hostname="sql01.corp.local", ip_addresses=["10.0.5.21"]),
            _vm("old-build", "11112222-3333-4444-5555-666677778888", power_state="off", vcpus=2, memory_gb=2.0),
        ],
    })
    assert r.status_code == 200, r.text
    host_id = r.json()["data"]["device_id"]

    v = (await api.get(f"/api/devices/{host_id}/virtualization")).json()["data"]
    assert v["host"] is None
    assert [(g["vm_name"], g["hostname"], g["power_state"], g["ip"]) for g in v["guests"]] == [
        ("SQL01", "SQL01", "on", "10.0.5.21"), ("old-build", "OLD-BUILD", "off", None)]
    assert v["totals"] == {"guests": 2, "running": 1, "vcpus_running": 4, "memory_gb_running": 8.0}
    assert v["guests"][0]["inventoried"] is False

    guest = (await api.get(f"/api/devices/{v['guests'][0]['device_id']}/virtualization")).json()["data"]
    assert (guest["host"]["device_id"], guest["host"]["hostname"], guest["guests"]) == (host_id, "HV01", [])
    assert (await api.get("/api/devices/999999/virtualization")).status_code == 404


async def test_virtual_machine_reports(api):
    from backend.reporting.library import BY_ID
    async with api.session_factory() as s:
        await _ingest_host(s, "HV01", "HOSTSN1", [
            _vm("SQL01", SQL01_UUID, guest_hostname="sql01.corp.local", tools_status="Up to date"),
            _vm("web01", "aaaaaaaa-0000-0000-0000-000000000001", tools_status="Update required"),
            _vm("old-build", "aaaaaaaa-0000-0000-0000-000000000002", power_state="off", disk_gb=40.0),
        ])
        await _ingest_host(s, "HV02", "HOSTSN2", [_vm("test", "aaaaaaaa-0000-0000-0000-000000000003",
                                                      power_state="suspended", disk_gb=10.0)])
        await InventoryService.ingest(s, "agent", InventoryReport.model_validate({
            "hostname": "SQL01", "hardware": {"hardware_uuid": SQL01_UUID}, "software": []}))
        await s.commit()

    async def run(report_id):
        r = await api.post("/api/reports/run", json={"definition": BY_ID[f"builtin:{report_id}"]["definition"]})
        assert r.status_code == 200, r.text
        return r.json()["data"]

    by_host = await run("vms-by-host")
    assert {g["value"]: g["count"] for g in by_host["groups"]} == {"HV01": 3, "HV02": 1}
    off = await run("vms-powered-off")
    assert [(r["vm_name"], r["host"], r["power_state"]) for r in off["rows"]] == [
        ("old-build", "HV01", "off"), ("test", "HV02", "suspended")]
    assert off["rows"][0]["_link_id"]                      # rows open the VM's device page
    assert [r["vm_name"] for r in (await run("vms-no-inventory"))["rows"]] == ["web01"]
    assert [r["vm_name"] for r in (await run("vms-integration-services"))["rows"]] == ["web01"]
