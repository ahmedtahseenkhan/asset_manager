"""
Network-device inventory over SNMP v1/v2c/v3 — read-only (GET/WALK only).

Collects: sysName/sysDescr/sysObjectID (vendor from the enterprise number),
ENTITY-MIB model/serial/firmware, Printer-MIB serial, and IF-MIB interfaces
with MACs and IPv4 addresses. Suited to switches, routers, firewalls,
printers, UPSes and NAS devices.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData, ContextData, ObjectIdentity, ObjectType, SnmpEngine, UdpTransportTarget,
    UsmUserData, bulk_walk_cmd, get_cmd, usm3DESEDEPrivProtocol, usmAesCfb128Protocol,
    usmAesCfb192Protocol, usmAesCfb256Protocol, usmDESPrivProtocol, usmHMAC128SHA224AuthProtocol,
    usmHMAC192SHA256AuthProtocol, usmHMAC256SHA384AuthProtocol, usmHMAC384SHA512AuthProtocol,
    usmHMACMD5AuthProtocol, usmHMACSHAAuthProtocol, usmNoAuthProtocol, usmNoPrivProtocol,
)

from backend.schemas.inventory import Hardware, InventoryReport, NetworkAdapter
from backend.scanning.collectors import CollectorError, CredentialInput

PORT = 161

SYS_DESCR, SYS_OBJECT_ID, SYS_NAME = "1.3.6.1.2.1.1.1.0", "1.3.6.1.2.1.1.2.0", "1.3.6.1.2.1.1.5.0"
PRT_SERIAL = "1.3.6.1.2.1.43.5.1.1.17.1"            # Printer-MIB prtGeneralSerialNumber
ENT_CLASS, ENT_MFG, ENT_MODEL = "1.3.6.1.2.1.47.1.1.1.1.5", "1.3.6.1.2.1.47.1.1.1.1.12", "1.3.6.1.2.1.47.1.1.1.1.13"
ENT_SERIAL, ENT_SW_REV = "1.3.6.1.2.1.47.1.1.1.1.11", "1.3.6.1.2.1.47.1.1.1.1.10"
IF_DESCR, IF_MAC, IF_OPER = "1.3.6.1.2.1.2.2.1.2", "1.3.6.1.2.1.2.2.1.6", "1.3.6.1.2.1.2.2.1.8"
IF_HIGH_SPEED = "1.3.6.1.2.1.31.1.1.1.15"          # Mb/s
IP_AD_IFINDEX = "1.3.6.1.2.1.4.20.1.2"             # ipAdEntIfIndex.<ip> = ifIndex

# IANA enterprise numbers of common network/printer vendors (sysObjectID 1.3.6.1.4.1.<n>).
VENDORS = {
    9: "Cisco", 11: "HP", 2: "IBM", 43: "3Com", 171: "D-Link", 236: "Samsung", 253: "Xerox",
    311: "Microsoft", 367: "Ricoh", 641: "Lexmark", 674: "Dell", 1347: "Kyocera", 1588: "Brocade",
    1602: "Canon", 1916: "Extreme Networks", 1991: "Brocade (Foundry)", 2011: "Huawei", 2435: "Brother",
    2620: "Check Point", 2636: "Juniper", 3375: "F5", 4526: "Netgear", 5596: "Tandberg",
    6027: "Dell (Force10)", 6486: "Alcatel-Lucent", 6574: "Synology", 6876: "VMware", 8072: "Net-SNMP",
    11863: "TP-Link", 12356: "Fortinet", 14823: "Aruba", 14988: "MikroTik", 18334: "Konica Minolta",
    24681: "QNAP", 25461: "Palo Alto Networks", 25506: "H3C", 30065: "Arista", 318: "APC",
    41112: "Ubiquiti", 47196: "HPE Aruba", 2604: "Sophos", 21067: "Barracuda",
}

_AUTH = {"MD5": usmHMACMD5AuthProtocol, "SHA": usmHMACSHAAuthProtocol, "SHA224": usmHMAC128SHA224AuthProtocol,
         "SHA256": usmHMAC192SHA256AuthProtocol, "SHA384": usmHMAC256SHA384AuthProtocol,
         "SHA512": usmHMAC384SHA512AuthProtocol}
_PRIV = {"DES": usmDESPrivProtocol, "3DES": usm3DESEDEPrivProtocol, "AES128": usmAesCfb128Protocol,
         "AES192": usmAesCfb192Protocol, "AES256": usmAesCfb256Protocol}


def _auth_data(cred: CredentialInput):
    if cred.cred_type == "snmp_v2c":
        mp = 0 if cred.params.get("version") == "1" else 1
        return CommunityData(cred.secret.get("community", ""), mpModel=mp)
    if cred.cred_type == "snmp_v3":
        level = cred.params.get("security_level", "authPriv")
        auth_key = cred.secret.get("auth_password") if level != "noAuthNoPriv" else None
        priv_key = cred.secret.get("priv_password") if level == "authPriv" else None
        return UsmUserData(
            cred.username, authKey=auth_key, privKey=priv_key,
            authProtocol=_AUTH.get(cred.params.get("auth_protocol", "SHA"), usmHMACSHAAuthProtocol)
            if auth_key else usmNoAuthProtocol,
            privProtocol=_PRIV.get(cred.params.get("priv_protocol", "AES128"), usmAesCfb128Protocol)
            if priv_key else usmNoPrivProtocol,
        )
    raise CollectorError("not_supported", cred.cred_type)


def _text(value) -> Optional[str]:
    if value is None:
        return None
    s = value.prettyPrint() if hasattr(value, "prettyPrint") else str(value)
    s = s.strip()
    return None if not s or s.startswith("No Such") else s


def _mac(value) -> Optional[str]:
    raw = bytes(value) if value is not None else b""
    if len(raw) != 6 or raw == b"\x00" * 6:
        return None
    return ":".join(f"{b:02X}" for b in raw)


class _Session:
    def __init__(self, host: str, cred: CredentialInput, port: int):
        self.engine = SnmpEngine()
        self.auth = _auth_data(cred)
        self.host, self.port = host, port
        self.target = None

    async def open(self):
        self.target = await UdpTransportTarget.create((self.host, self.port), timeout=2, retries=1)

    async def get(self, *oids: str) -> Dict[str, object]:
        err, status, _idx, binds = await get_cmd(
            self.engine, self.auth, self.target, ContextData(), *(ObjectType(ObjectIdentity(o)) for o in oids))
        if err:
            text = str(err)
            # SNMPv3 tells a bad user/password apart from silence; v1/v2c can't.
            if any(k in text for k in ("digest", "Unknown USM user", "Unsupported SNMP security level",
                                       "decryption", "Wrong SNMP PDU")):
                raise CollectorError("auth_failed", text)
            raise CollectorError("snmp_no_response", text)
        if status:
            raise CollectorError("collector_failed", status.prettyPrint())
        return {str(name): val for name, val in binds}

    async def walk(self, oid: str, limit: int = 2000) -> Dict[str, object]:
        """{index suffix: value} under oid."""
        out: Dict[str, object] = {}
        async for err, status, _idx, binds in bulk_walk_cmd(
                self.engine, self.auth, self.target, ContextData(), 0, 25,
                ObjectType(ObjectIdentity(oid)), lexicographicMode=False):
            if err or status:
                break
            for name, val in binds:
                out[str(name)[len(oid) + 1:]] = val
            if len(out) >= limit:
                break
        return out

    def close(self):
        self.engine.close_dispatcher()


async def _system(s: _Session) -> Dict[str, Optional[str]]:
    base = await s.get(SYS_DESCR, SYS_OBJECT_ID, SYS_NAME)
    oid = base.get(SYS_OBJECT_ID)
    return {"descr": _text(base.get(SYS_DESCR)),
            # str() gives the dotted OID; prettyPrint() would give "SNMPv2-SMI::enterprises.…"
            "object_id": str(oid) if oid is not None and _text(oid) else None,
            "name": _text(base.get(SYS_NAME))}


def _vendor(object_id: Optional[str]) -> Optional[str]:
    if object_id and object_id.startswith("1.3.6.1.4.1."):
        try:
            return VENDORS.get(int(object_id.split(".")[6]))
        except (IndexError, ValueError):
            return None
    return None


async def collect(host: str, cred: CredentialInput, port: int = PORT) -> InventoryReport:
    s = _Session(host, cred, port)
    try:
        await s.open()
        sysinfo = await _system(s)

        # ENTITY-MIB: prefer the chassis (class 3), else the first entity with a serial.
        classes = await s.walk(ENT_CLASS)
        serials, models = await s.walk(ENT_SERIAL), await s.walk(ENT_MODEL)
        mfgs, revs = await s.walk(ENT_MFG), await s.walk(ENT_SW_REV)
        order = sorted(classes, key=lambda i: (str(classes[i]) != "3", int(i) if i.isdigit() else 0)) or list(serials)
        pick = lambda table: next((_text(table.get(i)) for i in order if _text(table.get(i))), None)  # noqa: E731
        serial = pick(serials)
        if not serial:
            serial = _text((await s.get(PRT_SERIAL)).get(PRT_SERIAL))

        # IF-MIB interfaces that are up and have a MAC, with their IPv4 addresses.
        descr, macs, oper, speed = (await s.walk(IF_DESCR), await s.walk(IF_MAC),
                                    await s.walk(IF_OPER), await s.walk(IF_HIGH_SPEED))
        ip_by_if: Dict[str, List[str]] = {}
        for ip, ifindex in (await s.walk(IP_AD_IFINDEX)).items():
            ip_by_if.setdefault(str(ifindex), []).append(ip)
        adapters = []
        for idx, d in descr.items():
            mac = _mac(macs.get(idx))
            if mac and str(oper.get(idx)) == "1":
                sp = speed.get(idx)
                adapters.append(NetworkAdapter(
                    name=_text(d) or f"if{idx}", mac=mac, ip_addresses=ip_by_if.get(idx, []),
                    speed_mbps=int(sp) if sp is not None and int(sp) > 0 else None))
    except CollectorError:
        raise
    except Exception as exc:          # malformed agents on cheap devices: report, don't crash the run
        raise CollectorError("collector_failed", f"{type(exc).__name__}: {exc}"[:300])
    finally:
        s.close()

    descr_line = (sysinfo["descr"] or "").splitlines()[0][:255] if sysinfo["descr"] else None
    ips = sorted({ip for a in adapters for ip in a.ip_addresses if not ip.startswith("127.")} | {host})
    return InventoryReport(
        collector_version="snmp",
        hostname=(sysinfo["name"] or "").split(".")[0] or None,
        fqdn=sysinfo["name"] if sysinfo["name"] and "." in sysinfo["name"] else None,
        os_name=descr_line,
        os_version=pick(revs),
        ip_addresses=ips,
        mac_addresses=sorted({a.mac for a in adapters if a.mac}),
        hardware=Hardware(manufacturer=pick(mfgs) or _vendor(sysinfo["object_id"]),
                          model=pick(models), serial_number=serial),
        network_adapters=adapters,
    )


async def test(host: str, cred: CredentialInput, port: int = PORT) -> dict:
    s = _Session(host, cred, port)
    try:
        await s.open()
        info = await _system(s)
    finally:
        s.close()
    return {"hostname": info["name"], "os": (info["descr"] or "").splitlines()[0] if info["descr"] else None,
            "vendor": _vendor(info["object_id"])}
