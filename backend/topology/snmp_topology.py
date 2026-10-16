"""
Read layer-2/3 topology from a switch or router over SNMP (read-only).

  IF-MIB        interfaces (name, alias, MAC, speed, status)
  Q-BRIDGE-MIB  VLAN-aware forwarding table + port VLAN (PVID)
  BRIDGE-MIB    forwarding table on switches without Q-BRIDGE; on Cisco
                switches, per VLAN via community@vlan / context "vlan-N"
  LLDP-MIB      neighbours (any vendor)
  CISCO-CDP-MIB neighbours (Cisco)
  IP-MIB        ARP cache (routers / layer-3 switches)

Parsing is separate from fetching: the parse_* functions take the raw walk
results ({index suffix: value}) so they can be tested on recorded tables.
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from backend.scanning.collectors import CredentialInput
from backend.scanning.collectors.snmp import PORT, SYS_OBJECT_ID, _Session

# IF-MIB
IF_DESCR, IF_TYPE, IF_MAC = "1.3.6.1.2.1.2.2.1.2", "1.3.6.1.2.1.2.2.1.3", "1.3.6.1.2.1.2.2.1.6"
IF_ADMIN, IF_OPER = "1.3.6.1.2.1.2.2.1.7", "1.3.6.1.2.1.2.2.1.8"
IF_NAME, IF_HIGH_SPEED, IF_ALIAS = "1.3.6.1.2.1.31.1.1.1.1", "1.3.6.1.2.1.31.1.1.1.15", "1.3.6.1.2.1.31.1.1.1.18"
# BRIDGE / Q-BRIDGE
BASE_PORT_IFINDEX = "1.3.6.1.2.1.17.1.4.1.2"
TP_FDB_PORT, TP_FDB_STATUS = "1.3.6.1.2.1.17.4.3.1.2", "1.3.6.1.2.1.17.4.3.1.3"
Q_FDB_PORT, Q_FDB_STATUS = "1.3.6.1.2.1.17.7.1.2.2.1.2", "1.3.6.1.2.1.17.7.1.2.2.1.3"
Q_PVID = "1.3.6.1.2.1.17.7.1.4.5.1.1"
# LLDP
LLDP_LOC_PORT_ID, LLDP_LOC_PORT_DESC = "1.0.8802.1.1.2.1.3.7.1.3", "1.0.8802.1.1.2.1.3.7.1.4"
LLDP_REM = "1.0.8802.1.1.2.1.4.1.1"
LLDP_REM_COLS = {"chassis_subtype": 4, "chassis": 5, "port_subtype": 6, "port": 7, "port_desc": 8,
                 "sys_name": 9, "sys_desc": 10, "caps": 12}
LLDP_REM_MAN_ADDR = "1.0.8802.1.1.2.1.4.2.1.3"
# CDP
CDP_CACHE = "1.3.6.1.4.1.9.9.23.1.2.1.1"
CDP_COLS = {"address": 4, "device_id": 6, "device_port": 7, "platform": 8, "caps": 9}
CISCO_VTP_VLAN_STATE = "1.3.6.1.4.1.9.9.46.1.3.1.1.2"
# IP-MIB ARP
ARP_MAC, ARP_TYPE = "1.3.6.1.2.1.4.22.1.2", "1.3.6.1.2.1.4.22.1.4"

# Software/virtual interfaces that aren't physical ports: loopback, tunnel,
# propVirtual (SVIs), l2vlan, l3ipvlan.
_VIRTUAL_IF_TYPES = {24, 131, 53, 135, 136}
FDB_LIMIT, ARP_LIMIT = 50_000, 50_000


@dataclass
class PortInfo:
    if_index: int
    name: Optional[str] = None
    description: Optional[str] = None
    alias: Optional[str] = None
    mac: Optional[str] = None
    speed_mbps: Optional[int] = None
    oper_up: Optional[bool] = None
    admin_up: Optional[bool] = None
    vlan: Optional[int] = None


@dataclass
class NeighborInfo:
    protocol: str
    local_if_index: Optional[int]
    local_port: Optional[str]
    chassis_id: Optional[str] = None
    port: Optional[str] = None
    port_desc: Optional[str] = None
    sys_name: Optional[str] = None
    sys_desc: Optional[str] = None
    mgmt_ip: Optional[str] = None
    is_bridge: Optional[bool] = None


@dataclass
class FdbEntry:
    mac: str
    if_index: int
    vlan: Optional[int]


@dataclass
class ArpInfo:
    ip: str
    mac: str
    if_index: Optional[int]


@dataclass
class TopologySnapshot:
    ports: List[PortInfo] = field(default_factory=list)
    neighbors: List[NeighborInfo] = field(default_factory=list)
    fdb: List[FdbEntry] = field(default_factory=list)
    arp: List[ArpInfo] = field(default_factory=list)


# ── value helpers (accept pysnmp objects or plain Python values) ───────────
def _bytes(v: Any) -> bytes:
    if v is None:
        return b""
    if hasattr(v, "asOctets"):
        return v.asOctets()
    if isinstance(v, bytes):
        return v
    return str(v).encode()


def _str(v: Any) -> Optional[str]:
    if v is None:
        return None
    if hasattr(v, "asOctets") or isinstance(v, bytes):
        raw = _bytes(v).rstrip(b"\x00")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
        if not all(ch.isprintable() or ch in "\r\n\t" for ch in text):
            return None                       # binary (e.g. a MAC): caller formats it
        return text.strip() or None
    text = str(v).strip()
    return text or None


def _int(v: Any) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def mac_from_bytes(raw: bytes) -> Optional[str]:
    if len(raw) != 6 or raw in (b"\x00" * 6, b"\xff" * 6):
        return None
    return ":".join(f"{b:02X}" for b in raw)


def mac_from_index(parts: List[str]) -> Optional[str]:
    """Six decimal OID sub-identifiers → MAC."""
    try:
        return mac_from_bytes(bytes(int(p) for p in parts))
    except ValueError:
        return None


def _addr(raw: bytes) -> Optional[str]:
    if len(raw) == 4:
        return str(ipaddress.IPv4Address(raw))
    return None


# ── parsing ─────────────────────────────────────────────────────────────────
def parse_ports(t: Dict[str, Dict[str, Any]]) -> List[PortInfo]:
    ports = []
    for idx, descr in t.get("descr", {}).items():
        if _int(t.get("type", {}).get(idx)) in _VIRTUAL_IF_TYPES or not idx.isdigit():
            continue
        speed = _int(t.get("high_speed", {}).get(idx))
        ports.append(PortInfo(
            if_index=int(idx),
            name=_str(t.get("name", {}).get(idx)),
            description=_str(descr),
            alias=_str(t.get("alias", {}).get(idx)),
            mac=mac_from_bytes(_bytes(t.get("mac", {}).get(idx))),
            speed_mbps=speed if speed else None,
            oper_up=None if idx not in t.get("oper", {}) else _int(t["oper"][idx]) == 1,
            admin_up=None if idx not in t.get("admin", {}) else _int(t["admin"][idx]) == 1,
        ))
    return ports


def parse_fdb(q_port: Dict[str, Any], q_status: Dict[str, Any], tp_port: Dict[str, Any],
              tp_status: Dict[str, Any], bridge_to_if: Dict[int, int],
              vlan: Optional[int] = None) -> List[FdbEntry]:
    """Learned entries only (status 3); prefers the VLAN-aware Q-BRIDGE table."""
    out: List[FdbEntry] = []
    if q_port:
        for idx, bport in q_port.items():
            parts = idx.split(".")
            if len(parts) != 7 or _int(q_status.get(idx, 3)) != 3:
                continue
            mac, if_index = mac_from_index(parts[1:]), bridge_to_if.get(_int(bport) or 0)
            if mac and if_index:
                out.append(FdbEntry(mac, if_index, _int(parts[0])))
        return out
    for idx, bport in tp_port.items():
        parts = idx.split(".")
        if len(parts) != 6 or _int(tp_status.get(idx, 3)) != 3:
            continue
        mac, if_index = mac_from_index(parts), bridge_to_if.get(_int(bport) or 0)
        if mac and if_index:
            out.append(FdbEntry(mac, if_index, vlan))
    return out


def _format_lldp_id(subtype: Optional[int], value: Any, *, chassis: bool) -> Optional[str]:
    raw = _bytes(value)
    if (chassis and subtype == 4) or (not chassis and subtype == 3):     # macAddress
        return mac_from_bytes(raw) or _str(value)
    if chassis and subtype == 5 and len(raw) == 5 and raw[0] == 1:       # networkAddress, IPv4
        return str(ipaddress.IPv4Address(raw[1:]))
    return _str(value) or (raw.hex(":") if raw else None)


def _lldp_bridge(caps: Any) -> Optional[bool]:
    raw = _bytes(caps)
    if not raw:
        return None
    # BITS, MSB first: other(0) repeater(1) bridge(2) wlanAP(3) router(4) telephone(5) docsis(6) station(7)
    return bool(raw[0] & (0x20 | 0x10 | 0x08))


def parse_lldp(rem: Dict[str, Dict[str, Any]], man_addr: Dict[str, Any], loc_port_id: Dict[str, Any],
               loc_port_desc: Dict[str, Any], ports: List[PortInfo], bridge_to_if: Dict[int, int]) -> List[NeighborInfo]:
    by_name = {p.name: p.if_index for p in ports if p.name}
    by_descr = {p.description: p.if_index for p in ports if p.description}
    if_indexes = {p.if_index for p in ports}

    def local_if(port_num: int) -> Tuple[Optional[int], Optional[str]]:
        label = _str(loc_port_id.get(str(port_num))) or _str(loc_port_desc.get(str(port_num)))
        for candidate in (_str(loc_port_id.get(str(port_num))), _str(loc_port_desc.get(str(port_num)))):
            if candidate in by_name:
                return by_name[candidate], label
            if candidate in by_descr:
                return by_descr[candidate], label
        if port_num in bridge_to_if:
            return bridge_to_if[port_num], label
        return (port_num if port_num in if_indexes else None), label

    mgmt: Dict[Tuple[str, str], str] = {}
    for idx in man_addr:
        p = idx.split(".")
        # timeMark.localPort.remIndex.addrSubtype(1=ipv4).addrLen(4).a.b.c.d
        if len(p) == 9 and p[3] == "1" and p[4] == "4":
            mgmt.setdefault((p[1], p[2]), ".".join(p[5:9]))

    out = []
    for idx in rem.get("chassis", {}):
        p = idx.split(".")
        if len(p) != 3:
            continue
        get = lambda col: rem.get(col, {}).get(idx)  # noqa: E731
        if_index, label = local_if(int(p[1]))
        out.append(NeighborInfo(
            protocol="lldp", local_if_index=if_index, local_port=label,
            chassis_id=_format_lldp_id(_int(get("chassis_subtype")), get("chassis"), chassis=True),
            port=_format_lldp_id(_int(get("port_subtype")), get("port"), chassis=False),
            port_desc=_str(get("port_desc")), sys_name=_str(get("sys_name")),
            sys_desc=_str(get("sys_desc")), mgmt_ip=mgmt.get((p[1], p[2])), is_bridge=_lldp_bridge(get("caps")),
        ))
    return out


def parse_cdp(cdp: Dict[str, Dict[str, Any]], ports: List[PortInfo]) -> List[NeighborInfo]:
    names = {p.if_index: p.name or p.description for p in ports}
    out = []
    for idx, dev_id in cdp.get("device_id", {}).items():
        p = idx.split(".")
        if len(p) != 2:
            continue
        caps_raw = _bytes(cdp.get("caps", {}).get(idx))
        caps = int.from_bytes(caps_raw, "big") if caps_raw else None
        if_index = _int(p[0])
        out.append(NeighborInfo(
            protocol="cdp", local_if_index=if_index, local_port=names.get(if_index),
            sys_name=_str(dev_id), port=_str(cdp.get("device_port", {}).get(idx)),
            sys_desc=_str(cdp.get("platform", {}).get(idx)),
            mgmt_ip=_addr(_bytes(cdp.get("address", {}).get(idx))),
            is_bridge=None if caps is None else bool(caps & (0x01 | 0x02 | 0x08)),   # router, bridge, switch
        ))
    return out


def parse_arp(macs: Dict[str, Any], types: Dict[str, Any]) -> List[ArpInfo]:
    out = []
    for idx, raw in macs.items():
        p = idx.split(".")
        if len(p) != 5 or _int(types.get(idx, 3)) == 2:       # 2 = invalid
            continue
        mac = mac_from_bytes(_bytes(raw))
        if mac:
            out.append(ArpInfo(ip=".".join(p[1:]), mac=mac, if_index=_int(p[0])))
    return out


# ── fetching ────────────────────────────────────────────────────────────────
async def _walk_cols(s: _Session, base: str, cols: Dict[str, int], limit: int = 5000) -> Dict[str, Dict[str, Any]]:
    return {name: await s.walk(f"{base}.{num}", limit) for name, num in cols.items()}


def _bridge_map(raw: Dict[str, Any]) -> Dict[int, int]:
    return {int(k): int(v) for k, v in raw.items() if k.isdigit() and _int(v)}


async def collect(host: str, cred: CredentialInput, port: Optional[int] = None) -> TopologySnapshot:
    port = port or int(cred.params.get("port") or PORT)
    s = _Session(host, cred, port)
    try:
        await s.open()
        ifs = {"descr": await s.walk(IF_DESCR), "type": await s.walk(IF_TYPE), "mac": await s.walk(IF_MAC),
               "admin": await s.walk(IF_ADMIN), "oper": await s.walk(IF_OPER), "name": await s.walk(IF_NAME),
               "high_speed": await s.walk(IF_HIGH_SPEED), "alias": await s.walk(IF_ALIAS)}
        ports = parse_ports(ifs)
        bridge_to_if = _bridge_map(await s.walk(BASE_PORT_IFINDEX))
        pvid = await s.walk(Q_PVID)
        by_if = {p.if_index: p for p in ports}
        for bport, vlan in pvid.items():
            if bport.isdigit() and bridge_to_if.get(int(bport)) in by_if:
                by_if[bridge_to_if[int(bport)]].vlan = _int(vlan)

        fdb = parse_fdb(await s.walk(Q_FDB_PORT, FDB_LIMIT), await s.walk(Q_FDB_STATUS, FDB_LIMIT),
                        await s.walk(TP_FDB_PORT, FDB_LIMIT), await s.walk(TP_FDB_STATUS, FDB_LIMIT), bridge_to_if)
        if not fdb:
            object_id = str((await s.get(SYS_OBJECT_ID)).get(SYS_OBJECT_ID) or "")
            if object_id.startswith("1.3.6.1.4.1.9."):           # Cisco: one bridge table per VLAN
                fdb = await _cisco_per_vlan_fdb(host, cred, port, s)

        lldp = parse_lldp(await _walk_cols(s, LLDP_REM, LLDP_REM_COLS), await s.walk(LLDP_REM_MAN_ADDR),
                          await s.walk(LLDP_LOC_PORT_ID), await s.walk(LLDP_LOC_PORT_DESC), ports, bridge_to_if)
        cdp = parse_cdp(await _walk_cols(s, CDP_CACHE, CDP_COLS), ports)
        arp = parse_arp(await s.walk(ARP_MAC, ARP_LIMIT), await s.walk(ARP_TYPE, ARP_LIMIT))
    finally:
        s.close()
    return TopologySnapshot(ports=ports, neighbors=lldp + cdp, fdb=fdb, arp=arp)


async def _cisco_per_vlan_fdb(host: str, cred: CredentialInput, port: int, s: _Session) -> List[FdbEntry]:
    vlans = []
    for idx, state in (await s.walk(CISCO_VTP_VLAN_STATE)).items():
        p = idx.split(".")
        vlan = _int(p[-1])
        if vlan and _int(state) == 1 and not 1002 <= vlan <= 1005:     # operational, not the token-ring defaults
            vlans.append(vlan)
    out: List[FdbEntry] = []
    for vlan in vlans[:256]:
        vs = _Session(host, cred, port, vlan=vlan)
        try:
            await vs.open()
            out += parse_fdb({}, {}, await vs.walk(TP_FDB_PORT, FDB_LIMIT), await vs.walk(TP_FDB_STATUS, FDB_LIMIT),
                             _bridge_map(await vs.walk(BASE_PORT_IFINDEX)), vlan=vlan)
        finally:
            vs.close()
        if len(out) >= FDB_LIMIT:
            break
    return out
