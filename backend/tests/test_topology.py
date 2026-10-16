"""Topology: snapshot storage, uplink detection, locating devices, map graph, API, scan integration.

The network mirrors tests/live/snmpsim/make_recordings.py: core switch, access
switch (PC behind an IP phone on Gi1/0/5), router with the ARP cache. Endpoint
devices have IPs only — as when scanned from inside Docker — so locating them
relies on the router's ARP table.
"""
from sqlalchemy import select

from backend.licensing.state import license_manager
from backend.licensing.verifier import LicenseInfo, LicenseStatus
from backend.models.device import Device
from backend.models.topology import NetworkNeighbor, NetworkPort
from backend.topology.service import graph, locate, save_snapshot
from backend.topology.snmp_topology import (
    ArpInfo, FdbEntry, NeighborInfo, PortInfo, TopologySnapshot, parse_arp, parse_cdp, parse_fdb, parse_lldp,
)

PC_PHONE, PHONE, PC12, PRINTER, SERVER = ("AA:00:00:00:00:05", "00:04:F2:00:00:05", "AA:00:00:00:00:12",
                                          "AA:00:00:00:00:20", "AA:00:00:00:01:01")
CORE_MAC, ACCESS_MAC, ROUTER_MAC = "00:1A:2B:00:00:01", "00:1A:2B:00:00:02", "00:1A:2B:00:00:FE"


def core_snap():
    return TopologySnapshot(
        ports=[PortInfo(10101, "Gi1/0/1"), PortInfo(10102, "Gi1/0/2"), PortInfo(10124, "Gi1/0/24")],
        neighbors=[NeighborInfo("lldp", 10101, "Gi1/0/1", ACCESS_MAC, "Gi1/0/48", sys_name="access-sw.corp.local",
                                mgmt_ip="10.0.0.2", is_bridge=True),
                   NeighborInfo("lldp", 10124, "Gi1/0/24", ROUTER_MAC, "Gi0/0", sys_name="rtr-01.corp.local",
                                mgmt_ip="10.0.0.254", is_bridge=True)],
        fdb=[FdbEntry(m, 10101, 20) for m in (PC_PHONE, PC12, PRINTER)]
        + [FdbEntry(PHONE, 10101, 30), FdbEntry(SERVER, 10102, 10), FdbEntry(ROUTER_MAC, 10124, 10)])


def access_snap():
    return TopologySnapshot(
        ports=[PortInfo(10105, "Gi1/0/5", vlan=20), PortInfo(10112, "Gi1/0/12", vlan=20),
               PortInfo(10120, "Gi1/0/20", vlan=20), PortInfo(10148, "Gi1/0/48", vlan=1)],
        neighbors=[NeighborInfo("lldp", 10148, "Gi1/0/48", CORE_MAC, "Gi1/0/1", sys_name="core-sw.corp.local",
                                mgmt_ip="10.0.0.1", is_bridge=True),
                   NeighborInfo("lldp", 10105, "Gi1/0/5", PHONE, "Port 1", sys_name="SEP0004F2000005", is_bridge=False)],
        fdb=[FdbEntry(PC_PHONE, 10105, 20), FdbEntry(PHONE, 10105, 30), FdbEntry(PC12, 10112, 20),
             FdbEntry(PRINTER, 10120, 20), FdbEntry(SERVER, 10148, 10), FdbEntry(ROUTER_MAC, 10148, 10)])


def router_snap():
    return TopologySnapshot(
        ports=[PortInfo(1, "Gi0/0", mac=ROUTER_MAC)],
        neighbors=[NeighborInfo("cdp", 1, "Gi0/0", sys_name="core-sw.corp.local", port="GigabitEthernet1/0/24",
                                mgmt_ip="10.0.0.1", is_bridge=True)],
        arp=[ArpInfo(ip, mac, 1) for ip, mac in (("10.20.0.5", PC_PHONE), ("10.20.0.12", PC12),
                                                 ("10.20.0.20", PRINTER), ("10.10.0.10", SERVER))])


async def _network(db):
    def dev(name, ip):
        d = Device(hostname=name, ip_addresses=[ip], mac_addresses=[])
        db.add(d)
        return d
    devs = {n: dev(n, ip) for n, ip in (("CORE-SW", "10.0.0.1"), ("ACCESS-SW", "10.0.0.2"), ("RTR-01", "10.0.0.254"),
                                        ("PC-12", "10.20.0.12"), ("PC-PHONE", "10.20.0.5"),
                                        ("PRINTER-1", "10.20.0.20"), ("SRV-01", "10.10.0.10"))}
    await db.flush()
    await save_snapshot(db, devs["CORE-SW"].id, core_snap())
    await save_snapshot(db, devs["ACCESS-SW"].id, access_snap())
    await save_snapshot(db, devs["RTR-01"].id, router_snap())
    await db.commit()
    return devs


async def test_uplinks_and_neighbour_resolution(db_session):
    devs = await _network(db_session)
    ports = {(p.device_id, p.name): p for p in (await db_session.execute(select(NetworkPort))).scalars()}
    assert ports[(devs["CORE-SW"].id, "Gi1/0/1")].is_uplink and ports[(devs["CORE-SW"].id, "Gi1/0/24")].is_uplink
    assert ports[(devs["ACCESS-SW"].id, "Gi1/0/48")].is_uplink
    assert not ports[(devs["ACCESS-SW"].id, "Gi1/0/5")].is_uplink        # an IP phone is not a switch
    assert ports[(devs["ACCESS-SW"].id, "Gi1/0/5")].mac_count == 2
    resolved = {n.remote_name: n.remote_device_id for n in (await db_session.execute(select(NetworkNeighbor))).scalars()}
    assert resolved["access-sw.corp.local"] == devs["ACCESS-SW"].id
    assert resolved["SEP0004F2000005"] is None


async def test_locate_uses_access_port_and_router_arp(db_session):
    devs = await _network(db_session)
    pc12 = await locate(db_session, devs["PC-12"])
    assert (pc12[0]["switch"], pc12[0]["port"], pc12[0]["vlan"], pc12[0]["uplink"]) == ("ACCESS-SW", "Gi1/0/12", 20, False)
    assert pc12[-1]["uplink"] is True                                    # also seen on the core's uplink
    behind_phone = await locate(db_session, devs["PC-PHONE"])
    assert (behind_phone[0]["switch"], behind_phone[0]["port"]) == ("ACCESS-SW", "Gi1/0/5")
    server = await locate(db_session, devs["SRV-01"])
    assert (server[0]["switch"], server[0]["port"]) == ("CORE-SW", "Gi1/0/2")
    router = await locate(db_session, devs["RTR-01"])                   # via its own interface MAC
    assert (router[0]["switch"], router[0]["port"]) == ("CORE-SW", "Gi1/0/24")


async def test_graph_links_and_endpoints(db_session):
    devs = await _network(db_session)
    g = await graph(db_session)
    labels = {n["id"]: n["label"] for n in g["nodes"]}
    links = {frozenset((labels[e["source"]], labels[e["target"]])): e for e in g["edges"]}
    assert frozenset(("CORE-SW", "ACCESS-SW")) in links
    core_rtr = links[frozenset(("CORE-SW", "RTR-01"))]
    assert core_rtr["protocols"] == ["cdp", "lldp"]                      # seen from both sides, drawn once
    assert frozenset(("ACCESS-SW", "SEP0004F2000005")) in links          # unscanned neighbour still drawn
    assert g["stats"]["infrastructure"] == 3 and g["stats"]["endpoints"] == 0
    roles = {n["label"]: n["role"] for n in g["nodes"]}
    assert roles["CORE-SW"] == "switch" and roles["RTR-01"] == "router"

    g = await graph(db_session, include_endpoints=True)
    labels = {n["id"]: n["label"] for n in g["nodes"]}
    access = {(labels[e["source"]], labels[e["target"]], e["source_port"]) for e in g["edges"] if e["kind"] == "access"}
    assert ("ACCESS-SW", "PC-12", "Gi1/0/12") in access and ("CORE-SW", "SRV-01", "Gi1/0/2") in access
    assert ("ACCESS-SW", "PC-PHONE", "Gi1/0/5") in access
    vlan20 = await graph(db_session, include_endpoints=True, vlan=20)
    assert "SRV-01" not in {n["label"] for n in vlan20["nodes"]}
    _ = devs


async def test_snapshot_replaces_previous(db_session):
    devs = await _network(db_session)
    snap = access_snap()
    snap.fdb = [e for e in snap.fdb if e.mac != PC12]                    # PC-12 unplugged
    await save_snapshot(db_session, devs["ACCESS-SW"].id, snap)
    await db_session.commit()
    pc12 = await locate(db_session, devs["PC-12"])
    assert all(r["switch"] == "CORE-SW" for r in pc12)                   # only stale core entry left


# ── parsers on raw walk tables ──
def test_parsers():
    bridge = {48: 10148, 5: 10105}
    ports = [PortInfo(10148, "Gi1/0/48"), PortInfo(10105, "Gi1/0/5")]
    fdb = parse_fdb({"20.170.0.0.0.0.18": 48, "20.170.0.0.0.0.19": 5}, {"20.170.0.0.0.0.18": 3,
                    "20.170.0.0.0.0.19": 4}, {}, {}, bridge)
    assert [(f.mac, f.if_index, f.vlan) for f in fdb] == [("AA:00:00:00:00:12", 10148, 20)]   # status 4 = mgmt, skipped
    legacy = parse_fdb({}, {}, {"187.0.0.0.0.16": 5}, {}, bridge, vlan=10)
    assert [(f.mac, f.vlan) for f in legacy] == [("BB:00:00:00:00:10", 10)]

    rem = {"chassis_subtype": {"0.48.1": 4}, "chassis": {"0.48.1": bytes.fromhex("001a2b000001")},
           "port_subtype": {"0.48.1": 5}, "port": {"0.48.1": b"Gi1/0/1"}, "sys_name": {"0.48.1": b"core-sw"},
           "caps": {"0.48.1": bytes([0x20, 0x00])}}
    (n,) = parse_lldp(rem, {"0.48.1.1.4.10.0.0.1": 2}, {"48": b"Gi1/0/48"}, {}, ports, bridge)
    assert (n.local_if_index, n.chassis_id, n.port, n.mgmt_ip, n.is_bridge) == (10148, CORE_MAC, "Gi1/0/1", "10.0.0.1", True)
    phone = dict(rem, caps={"0.48.1": bytes([0x04, 0x00])})
    assert parse_lldp(phone, {}, {"48": b"Gi1/0/48"}, {}, ports, bridge)[0].is_bridge is False

    (c,) = parse_cdp({"device_id": {"10148.1": b"sw2"}, "address": {"10148.1": bytes([10, 0, 0, 9])},
                      "caps": {"10148.1": bytes.fromhex("00000028")}}, ports)
    assert (c.local_if_index, c.local_port, c.mgmt_ip, c.is_bridge) == (10148, "Gi1/0/48", "10.0.0.9", True)

    arp = parse_arp({"1.10.20.0.12": bytes.fromhex("aa0000000012"), "1.10.20.0.99": bytes(6)},
                    {"1.10.20.0.12": 3})
    assert [(a.ip, a.mac) for a in arp] == [("10.20.0.12", PC12)]


# ── API & scan integration ──
async def test_api_and_licensing(api, monkeypatch):
    async with api.session_factory() as s:
        devs = await _network(s)
    loc = (await api.get(f"/api/topology/devices/{devs['PC-12'].id}/location")).json()["data"]
    assert loc[0]["port"] == "Gi1/0/12"
    ports = (await api.get(f"/api/topology/devices/{devs['ACCESS-SW'].id}/ports")).json()["data"]
    gi12 = next(p for p in ports if p["name"] == "Gi1/0/12")
    assert gi12["connected"][0]["hostname"] == "PC-12" and gi12["connected"][0]["ip"] == "10.20.0.12"
    graph_data = (await api.get("/api/topology/graph?endpoints=true")).json()["data"]
    assert graph_data["stats"]["links"] >= 2 and graph_data["stats"]["macs"] > 0

    monkeypatch.setattr(license_manager, "_info", LicenseInfo(
        LicenseStatus.VALID, claims={"modules": ["assets"], "max_assets": 10, "max_users": 10}))
    assert (await api.get("/api/topology/graph")).status_code == 403


async def test_snmp_scan_collects_topology(api, monkeypatch):
    from backend.connectors.network_scan.connector import NetworkScanConnector
    from backend.scanning import credentialed
    from backend.scanning.runner import scan_runner
    from backend.schemas.inventory import InventoryReport
    from tests.conftest import make_raw

    async def sweep(self, config):
        return [make_raw(source_uid="netscan-10.0.0.2", hostname=None, fqdn=None, ip_addresses=["10.0.0.2"],
                         mac_addresses=[])]
    monkeypatch.setattr(NetworkScanConnector, "fetch_devices", sweep)

    async def fake_inventory(host, methods, creds, keys, preferred=None):
        return credentialed.HostOutcome(report=InventoryReport(hostname="ACCESS-SW", os_name="Cisco IOS"),
                                        method="snmp", credential_id=creds[0].id,
                                        attempts=[credentialed.Attempt("snmp", creds[0].id)])
    monkeypatch.setattr("backend.scanning.runner.inventory_host", fake_inventory)

    async def fake_topology(host, cred):
        return access_snap()
    monkeypatch.setattr("backend.topology.snmp_topology.collect", fake_topology)

    cred = (await api.post("/api/scan/credentials", json={"name": "ro", "cred_type": "snmp_v2c",
                                                         "secret": {"community": "x"}})).json()["data"]
    target = (await api.post("/api/scan/targets", json={"name": "Switches", "target_type": "hosts",
                                                        "value": "10.0.0.2", "methods": ["snmp"],
                                                        "credential_ids": [cred["id"]]})).json()["data"]
    run_id = (await api.post(f"/api/scan/targets/{target['id']}/run")).json()["data"]["run_id"]
    await scan_runner.wait(run_id)
    async with api.session_factory() as s:
        names = sorted((await s.execute(select(NetworkPort.name))).scalars())
    assert names == ["Gi1/0/12", "Gi1/0/20", "Gi1/0/48", "Gi1/0/5"]
