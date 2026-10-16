"""
Store topology snapshots and answer "where is this plugged in?" and "draw the
network".

Uplinks: a port is an uplink when a switch/router/AP sits behind it (LLDP/CDP
capability) or it carries many MACs. A MAC is located on the non-uplink port
that learned it — the access port — rather than on every uplink it crossed.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from sqlalchemy import String, cast, delete, insert, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.device import Device
from backend.models.inventory import DeviceInventory, DeviceNetworkAdapter
from backend.models.topology import ArpEntry, MacLocation, NetworkNeighbor, NetworkPort
from backend.topology.snmp_topology import TopologySnapshot

UPLINK_MAC_THRESHOLD = 25      # an access port rarely has more (PC + phone + a few VMs)
MAX_ENDPOINTS = 500            # endpoints drawn on the map


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _resolve_device(db: AsyncSession, *, ip: Optional[str], name: Optional[str],
                          mac: Optional[str]) -> Optional[int]:
    if ip:
        row = (await db.execute(select(Device.id).where(
            cast(Device.ip_addresses, String).contains(f'"{ip}"')).limit(1))).scalar()
        if row:
            return row
    if name:
        short = name.split(".")[0].upper()
        row = (await db.execute(select(Device.id).where(
            or_(Device.hostname == short, Device.fqdn == name.lower())).limit(1))).scalar()
        if row:
            return row
    if mac:
        row = (await db.execute(select(Device.id).where(
            cast(Device.mac_addresses, String).contains(f'"{mac.upper()}"')).limit(1))).scalar()
        if row:
            return row
    return None


async def save_snapshot(db: AsyncSession, device_id: int, snap: TopologySnapshot) -> Dict[str, int]:
    """Replace this device's topology with the snapshot. Flushes; caller commits."""
    now = _now()
    existing = {p.if_index: p for p in (await db.execute(
        select(NetworkPort).where(NetworkPort.device_id == device_id))).scalars()}
    seen = set()
    for p in snap.ports:
        seen.add(p.if_index)
        row = existing.get(p.if_index) or NetworkPort(device_id=device_id, if_index=p.if_index)
        row.name, row.description, row.alias = p.name, p.description, p.alias
        row.mac, row.speed_mbps, row.oper_up, row.admin_up, row.vlan = p.mac, p.speed_mbps, p.oper_up, p.admin_up, p.vlan
        row.last_seen = now
        db.add(row)
    stale = [r.id for i, r in existing.items() if i not in seen]
    if stale:
        await db.execute(delete(NetworkPort).where(NetworkPort.id.in_(stale)))
    await db.flush()
    port_ids = {p.if_index: p.id for p in (await db.execute(
        select(NetworkPort).where(NetworkPort.device_id == device_id))).scalars()}

    # Neighbours
    await db.execute(delete(NetworkNeighbor).where(NetworkNeighbor.device_id == device_id))
    bridge_ports: Set[int] = set()
    for n in snap.neighbors:
        remote_id = await _resolve_device(db, ip=n.mgmt_ip, name=n.sys_name,
                                          mac=n.chassis_id if n.chassis_id and len(n.chassis_id) == 17 else None)
        if remote_id == device_id:
            remote_id = None
        if n.is_bridge and n.local_if_index in port_ids:
            bridge_ports.add(port_ids[n.local_if_index])
        db.add(NetworkNeighbor(
            device_id=device_id, port_id=port_ids.get(n.local_if_index), local_port=(n.local_port or "")[:255] or None,
            protocol=n.protocol, remote_chassis_id=(n.chassis_id or "")[:255] or None,
            remote_port=(n.port or "")[:255] or None, remote_port_desc=(n.port_desc or "")[:255] or None,
            remote_name=(n.sys_name or "")[:255] or None, remote_description=(n.sys_desc or "")[:500] or None,
            remote_mgmt_ip=n.mgmt_ip, remote_is_bridge=n.is_bridge, remote_device_id=remote_id, last_seen=now,
        ))

    # Forwarding table: skip the switch's own interface MACs
    own_macs = {p.mac for p in snap.ports if p.mac}
    await db.execute(delete(MacLocation).where(MacLocation.device_id == device_id))
    rows, seen_keys = [], set()
    for e in snap.fdb:
        key = (e.mac, e.vlan)
        if e.mac in own_macs or key in seen_keys or e.if_index not in port_ids:
            continue
        seen_keys.add(key)
        rows.append({"device_id": device_id, "port_id": port_ids[e.if_index], "mac": e.mac,
                     "vlan": e.vlan, "last_seen": now})
    if rows:
        await db.execute(insert(MacLocation), rows)
    counts = Counter(r["port_id"] for r in rows)
    for pid in port_ids.values():
        port = await db.get(NetworkPort, pid)
        port.mac_count = counts.get(pid, 0)
        port.is_uplink = pid in bridge_ports or port.mac_count >= UPLINK_MAC_THRESHOLD

    # ARP cache
    await db.execute(delete(ArpEntry).where(ArpEntry.device_id == device_id))
    arp_rows = {a.ip: {"device_id": device_id, "ip": a.ip, "mac": a.mac, "if_index": a.if_index, "last_seen": now}
                for a in snap.arp}
    if arp_rows:
        await db.execute(insert(ArpEntry), list(arp_rows.values()))
    await db.flush()
    return {"ports": len(port_ids), "neighbors": len(snap.neighbors), "macs": len(rows), "arp": len(arp_rows)}


async def device_macs(db: AsyncSession, device: Device) -> Set[str]:
    """MACs of a device: reported directly, from its adapters, from its own SNMP
    interface table, and from router ARP caches for its IPs."""
    macs = {m.upper() for m in (device.mac_addresses or [])}
    macs |= {m.upper() for m in (await db.execute(
        select(DeviceNetworkAdapter.mac).where(DeviceNetworkAdapter.device_id == device.id,
                                               DeviceNetworkAdapter.mac.isnot(None)))).scalars()}
    macs |= set((await db.execute(select(NetworkPort.mac).where(
        NetworkPort.device_id == device.id, NetworkPort.mac.isnot(None)))).scalars())
    if device.ip_addresses:
        macs |= set((await db.execute(select(ArpEntry.mac).where(ArpEntry.ip.in_(device.ip_addresses)))).scalars())
    return {m for m in macs if m and m != "00:00:00:00:00:00"}


async def locate(db: AsyncSession, device: Device) -> List[Dict[str, Any]]:
    """Where a device is connected, best match first."""
    macs = await device_macs(db, device)
    if not macs:
        return []
    rows = (await db.execute(
        select(MacLocation, NetworkPort, Device.hostname)
        .join(NetworkPort, NetworkPort.id == MacLocation.port_id)
        .join(Device, Device.id == MacLocation.device_id)
        .where(MacLocation.mac.in_(macs))
    )).all()
    out = []
    for loc, port, switch_name in rows:
        out.append({
            "switch_id": loc.device_id, "switch": switch_name, "port": port.name or port.description,
            "port_alias": port.alias, "port_id": port.id, "vlan": loc.vlan or port.vlan, "mac": loc.mac,
            "uplink": port.is_uplink, "macs_on_port": port.mac_count, "last_seen": loc.last_seen,
        })
    # Access ports first; among them the port with the fewest MACs is the most specific.
    out.sort(key=lambda r: (r["uplink"], r["macs_on_port"]))
    return out


def _role(dev: Device, inv: Optional[DeviceInventory], has_fdb: bool, has_arp: bool) -> str:
    if has_fdb:
        return "switch"
    if has_arp:
        return "router"
    text = " ".join(filter(None, [dev.os_name, inv.os_name if inv else None, inv.chassis_type if inv else None])).lower()
    for key, role in (("printer", "printer"), ("windows", "windows"), ("mac", "mac"), ("linux", "linux"),
                      ("ubuntu", "linux"), ("phone", "phone"), ("ios", "phone")):
        if key in text:
            return role
    return "device"


async def graph(db: AsyncSession, include_endpoints: bool = False, vlan: Optional[int] = None) -> Dict[str, Any]:
    """Nodes and edges for the map: infrastructure, links between it, optionally endpoints."""
    infra_ids = set((await db.execute(select(NetworkPort.device_id).distinct())).scalars())
    neighbors = (await db.execute(select(NetworkNeighbor))).scalars().all()
    infra_ids |= {n.remote_device_id for n in neighbors if n.remote_device_id and n.remote_is_bridge}
    fdb_ids = set((await db.execute(select(MacLocation.device_id).distinct())).scalars())
    arp_ids = set((await db.execute(select(ArpEntry.device_id).distinct())).scalars())
    ports = {p.id: p for p in (await db.execute(select(NetworkPort))).scalars()}

    nodes: Dict[str, Dict[str, Any]] = {}

    async def add_device(device_id: int, kind: str) -> str:
        key = f"d{device_id}"
        if key not in nodes:
            dev = await db.get(Device, device_id)
            inv = (await db.execute(select(DeviceInventory).where(DeviceInventory.device_id == device_id))).scalars().first()
            nodes[key] = {"id": key, "device_id": device_id, "label": dev.hostname or (dev.ip_addresses or ["?"])[0],
                          "ip": (dev.ip_addresses or [None])[0], "kind": kind,
                          "role": _role(dev, inv, device_id in fdb_ids, device_id in arp_ids),
                          "model": inv.model if inv else None}
        return key

    for did in infra_ids:
        await add_device(did, "infrastructure")

    edges: Dict[frozenset, Dict[str, Any]] = {}
    for n in neighbors:
        a = await add_device(n.device_id, "infrastructure")
        if n.remote_device_id:
            b = await add_device(n.remote_device_id, "infrastructure" if n.remote_is_bridge else "endpoint")
        else:   # neighbour we have no device for yet (not scanned): still draw it
            b = f"x{n.remote_chassis_id or n.remote_name}"
            nodes.setdefault(b, {"id": b, "device_id": None, "label": n.remote_name or n.remote_chassis_id,
                                 "ip": n.remote_mgmt_ip, "kind": "external",
                                 "role": "switch" if n.remote_is_bridge else "device", "model": n.remote_description})
        if a == b:
            continue
        local = ports.get(n.port_id).name if n.port_id in ports else n.local_port
        pair = frozenset((a, b))
        edge = edges.setdefault(pair, {"id": "e" + "-".join(sorted(pair)), "source": a, "target": b,
                                       "kind": "link", "protocols": set(), "ports": {}})
        edge["protocols"].add(n.protocol)
        edge["ports"][a] = local
        edge["ports"].setdefault(b, n.remote_port_desc or n.remote_port)

    endpoint_count = 0
    if include_endpoints:
        q = (select(MacLocation, NetworkPort).join(NetworkPort, NetworkPort.id == MacLocation.port_id)
             .where(NetworkPort.is_uplink.is_(False)))
        if vlan is not None:
            q = q.where(or_(MacLocation.vlan == vlan, NetworkPort.vlan == vlan))
        by_mac: Dict[str, List[Any]] = defaultdict(list)
        for loc, port in (await db.execute(q)).all():
            by_mac[loc.mac].append((loc, port))
        arp_by_mac: Dict[str, str] = {}
        for ip, mac in (await db.execute(select(ArpEntry.ip, ArpEntry.mac))).all():
            arp_by_mac.setdefault(mac, ip)
        for mac, entries in by_mac.items():
            if endpoint_count >= MAX_ENDPOINTS:
                break
            loc, port = min(entries, key=lambda e: e[1].mac_count)
            dev_id = await _resolve_device(db, ip=arp_by_mac.get(mac), name=None, mac=mac)
            if dev_id is None or f"d{dev_id}" in nodes and nodes[f"d{dev_id}"]["kind"] == "infrastructure":
                continue
            b = await add_device(dev_id, "endpoint")
            a = f"d{loc.device_id}"
            if a not in nodes:
                await add_device(loc.device_id, "infrastructure")
            pair = frozenset((a, b))
            if pair not in edges:
                edges[pair] = {"id": "e" + "-".join(sorted(pair)), "source": a, "target": b, "kind": "access",
                               "protocols": {"fdb"}, "ports": {a: port.name or port.description},
                               "vlan": loc.vlan or port.vlan}
                endpoint_count += 1

    out_edges = []
    for e in edges.values():
        out_edges.append({**e, "protocols": sorted(e["protocols"]),
                          "source_port": e["ports"].get(e["source"]), "target_port": e["ports"].get(e["target"])})
        out_edges[-1].pop("ports")
    return {
        "nodes": list(nodes.values()), "edges": out_edges,
        "stats": {"infrastructure": sum(1 for n in nodes.values() if n["kind"] == "infrastructure"),
                  "external": sum(1 for n in nodes.values() if n["kind"] == "external"),
                  "endpoints": sum(1 for n in nodes.values() if n["kind"] == "endpoint"),
                  "links": sum(1 for e in out_edges if e["kind"] == "link"),
                  "endpoints_capped": endpoint_count >= MAX_ENDPOINTS},
    }


async def switch_ports(db: AsyncSession, device_id: int) -> List[Dict[str, Any]]:
    """Port table for a switch: status, VLAN, neighbour and what's connected."""
    ports = (await db.execute(select(NetworkPort).where(NetworkPort.device_id == device_id)
                              .order_by(NetworkPort.if_index))).scalars().all()
    neigh = defaultdict(list)
    for n in (await db.execute(select(NetworkNeighbor).where(NetworkNeighbor.device_id == device_id))).scalars():
        neigh[n.port_id].append({"name": n.remote_name or n.remote_chassis_id, "port": n.remote_port_desc or n.remote_port,
                                 "device_id": n.remote_device_id, "protocol": n.protocol})
    macs = defaultdict(list)
    for loc in (await db.execute(select(MacLocation).where(MacLocation.device_id == device_id))).scalars():
        macs[loc.port_id].append(loc.mac)
    arp = dict((await db.execute(select(ArpEntry.mac, ArpEntry.ip))).all())
    out = []
    for p in ports:
        connected = []
        if not p.is_uplink:
            for mac in macs.get(p.id, [])[:10]:
                dev_id = await _resolve_device(db, ip=arp.get(mac), name=None, mac=mac)
                name = (await db.get(Device, dev_id)).hostname if dev_id else None
                connected.append({"mac": mac, "ip": arp.get(mac), "device_id": dev_id, "hostname": name})
        out.append({"id": p.id, "if_index": p.if_index, "name": p.name or p.description, "alias": p.alias,
                    "oper_up": p.oper_up, "admin_up": p.admin_up, "speed_mbps": p.speed_mbps, "vlan": p.vlan,
                    "mac_count": p.mac_count, "uplink": p.is_uplink, "neighbors": neigh.get(p.id, []),
                    "connected": connected})
    return out
