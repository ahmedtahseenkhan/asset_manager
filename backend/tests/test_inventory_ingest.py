"""Agent ingestion through InventoryService: v1 compatibility, v2 sections,
software diffing, and asset updates."""
from sqlalchemy import select

from backend.models.agent import AgentToken
from backend.models.asset import Asset
from backend.models.device import Device
from backend.models.software import InstalledSoftware

TOKEN = "t" * 43


async def _setup_token(api):
    async with api.session_factory() as s:
        s.add(AgentToken(token=TOKEN, name="test"))
        await s.commit()


async def _post(api, payload, token=TOKEN):
    return await api.post("/api/ingest/agent", json=payload, headers={"X-Agent-Token": token})


async def _software(api, device_id):
    async with api.session_factory() as s:
        rows = (await s.execute(select(InstalledSoftware).where(
            InstalledSoftware.device_id == device_id))).scalars().all()
    return {(r.name, r.version) for r in rows}


V1 = {
    "hostname": "LAPTOP-01", "os_name": "Windows", "os_version": "Windows 11 Pro 10.0.22631",
    "serial_number": "5CG1234XYZ", "machine_id": "4C4C4544-0042-3510-8051-B4C04F4E3332",
    "manufacturer": "HP", "model": "EliteBook 840", "ram_gb": 16,
    "ip_addresses": ["10.0.0.5"], "mac_addresses": ["AA:BB:CC:00:11:22"],
    "software": [{"name": "Zoom", "version": "5.17"}, {"name": "7-Zip", "version": "23.01"}],
}


async def test_rejects_bad_token(api):
    r = await _post(api, V1, token="nope")
    assert r.status_code == 401


async def test_v1_payload_creates_device_and_software(api):
    await _setup_token(api)
    r = await _post(api, V1)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["device_created"] is True
    assert data["software"] == {"total": 2, "added": 2, "removed": 0, "upgraded": 0}

    async with api.session_factory() as s:
        device = (await s.execute(select(Device))).scalars().one()
        token = (await s.execute(select(AgentToken))).scalars().one()
    assert device.serial_number == "5CG1234XYZ"
    assert device.hardware_uuid == "4c4c4544-0042-3510-8051-b4c04f4e3332"
    assert token.reports_count == 1
    assert await _software(api, device.id) == {("Zoom", "5.17"), ("7-Zip", "23.01")}


async def test_software_is_diffed_not_replaced(api):
    await _setup_token(api)
    device_id = (await _post(api, V1)).json()["data"]["device_id"]
    async with api.session_factory() as s:
        zoom_id = (await s.execute(select(InstalledSoftware.id).where(
            InstalledSoftware.name == "Zoom"))).scalar_one()

    v2 = {"schema_version": 2, "hostname": "LAPTOP-01",
          "hardware": {"serial_number": "5CG1234XYZ"},
          "software": [{"name": "Zoom", "version": "5.17"}, {"name": "Slack", "version": "4.36"}]}
    data = (await _post(api, v2)).json()["data"]
    assert data["device_id"] == device_id
    assert data["software"] == {"total": 2, "added": 1, "removed": 1, "upgraded": 0}
    assert await _software(api, device_id) == {("Zoom", "5.17"), ("Slack", "4.36")}
    async with api.session_factory() as s:  # unchanged rows keep their identity
        assert (await s.execute(select(InstalledSoftware.id).where(
            InstalledSoftware.name == "Zoom"))).scalar_one() == zoom_id


async def test_uncollected_section_leaves_data_alone(api):
    await _setup_token(api)
    device_id = (await _post(api, V1)).json()["data"]["device_id"]
    # v2 report without a software section: software was not collected.
    data = (await _post(api, {"schema_version": 2, "hostname": "LAPTOP-01",
                              "hardware": {"serial_number": "5CG1234XYZ"}})).json()["data"]
    assert data["software"] is None
    assert len(await _software(api, device_id)) == 2


async def test_empty_section_means_nothing_installed(api):
    await _setup_token(api)
    device_id = (await _post(api, V1)).json()["data"]["device_id"]
    await _post(api, {"schema_version": 2, "hostname": "LAPTOP-01",
                      "hardware": {"serial_number": "5CG1234XYZ"}, "software": []})
    assert await _software(api, device_id) == set()


async def test_linked_asset_receives_authoritative_fields(api):
    await _setup_token(api)
    device_id = (await _post(api, V1)).json()["data"]["device_id"]
    async with api.session_factory() as s:
        s.add(Asset(name="Laptop 01", asset_tag="AST-1", category="hardware",
                    asset_type="laptop", device_id=device_id))
        await s.commit()

    data = (await _post(api, V1)).json()["data"]
    assert data["asset_updated"] is True
    async with api.session_factory() as s:
        asset = (await s.execute(select(Asset))).scalars().one()
    assert (asset.serial_number, asset.model, asset.vendor) == ("5CG1234XYZ", "EliteBook 840", "HP")
    assert asset.ip_address == "10.0.0.5"


async def test_malformed_v2_payload_is_rejected(api):
    await _setup_token(api)
    r = await _post(api, {"schema_version": 2, "software": [{"version": "1.0"}]})  # no name
    assert r.status_code == 422
