"""
Generate snmpsim recordings of a small network, used by the live topology
tests (snmpsim answers with these; the community string selects the device).

    core       Cisco-style core switch: Q-BRIDGE FDB, LLDP to access + router, server on Gi1/0/2
    access     access switch: uplink Gi1/0/48 (LLDP bridge), IP phone on Gi1/0/5 with a PC
               behind it (LLDP telephone), PC on Gi1/0/12, printer on Gi1/0/20
    router     Cisco router: CDP neighbour (core), ARP cache with every endpoint
    legacy     older Cisco switch without Q-BRIDGE: per-VLAN FDB via community@vlan
               (legacy@10, legacy@20)

    python make_recordings.py <output dir>
"""
import sys
from pathlib import Path

IF = "1.3.6.1.2.1.2.2.1"
IFX = "1.3.6.1.2.1.31.1.1.1"
SYS = "1.3.6.1.2.1.1"


def mac_hex(mac: str) -> str:
    return mac.replace(":", "").lower()


def mac_oid(mac: str) -> str:
    return ".".join(str(int(b, 16)) for b in mac.split(":"))


def text_hex(s: str) -> str:
    return s.encode().hex()


class Rec:
    def __init__(self):
        self.rows = {}

    def add(self, oid: str, typ: str, value):
        value = str(value)
        if typ == "4" and any(c in value for c in "\r\n|"):
            typ, value = "4x", text_hex(value)        # the format is one record per line
        self.rows[oid] = (typ, value)

    def system(self, descr, object_id, name):
        self.add(f"{SYS}.1.0", "4", descr)
        self.add(f"{SYS}.2.0", "6", object_id)
        self.add(f"{SYS}.5.0", "4", name)

    def interface(self, if_index, name, mac, speed=1000, up=True):
        self.add(f"{IF}.2.{if_index}", "4", name)
        self.add(f"{IF}.3.{if_index}", "2", 6)
        self.add(f"{IF}.6.{if_index}", "4x", mac_hex(mac))
        self.add(f"{IF}.7.{if_index}", "2", 1)
        self.add(f"{IF}.8.{if_index}", "2", 1 if up else 2)
        self.add(f"{IFX}.1.{if_index}", "4", name)
        self.add(f"{IFX}.15.{if_index}", "66", speed)
        self.add(f"{IFX}.18.{if_index}", "4", "")

    def bridge_port(self, bport, if_index, pvid=None):
        self.add(f"1.3.6.1.2.1.17.1.4.1.2.{bport}", "2", if_index)
        if pvid:
            self.add(f"1.3.6.1.2.1.17.7.1.4.5.1.1.{bport}", "66", pvid)

    def q_fdb(self, vlan, mac, bport):
        self.add(f"1.3.6.1.2.1.17.7.1.2.2.1.2.{vlan}.{mac_oid(mac)}", "2", bport)
        self.add(f"1.3.6.1.2.1.17.7.1.2.2.1.3.{vlan}.{mac_oid(mac)}", "2", 3)

    def tp_fdb(self, mac, bport):
        self.add(f"1.3.6.1.2.1.17.4.3.1.2.{mac_oid(mac)}", "2", bport)
        self.add(f"1.3.6.1.2.1.17.4.3.1.3.{mac_oid(mac)}", "2", 3)

    def lldp_local(self, port_num, name):
        self.add(f"1.0.8802.1.1.2.1.3.7.1.2.{port_num}", "2", 5)
        self.add(f"1.0.8802.1.1.2.1.3.7.1.3.{port_num}", "4", name)

    def lldp_remote(self, port_num, chassis_mac, port_name, sys_name, sys_desc, caps_byte, mgmt_ip=None):
        idx = f"0.{port_num}.1"
        b = "1.0.8802.1.1.2.1.4.1.1"
        self.add(f"{b}.4.{idx}", "2", 4)
        self.add(f"{b}.5.{idx}", "4x", mac_hex(chassis_mac))
        self.add(f"{b}.6.{idx}", "2", 5)
        self.add(f"{b}.7.{idx}", "4", port_name)
        self.add(f"{b}.8.{idx}", "4", port_name)
        self.add(f"{b}.9.{idx}", "4", sys_name)
        self.add(f"{b}.10.{idx}", "4", sys_desc)
        self.add(f"{b}.12.{idx}", "4x", f"{caps_byte:02x}00")
        if mgmt_ip:
            self.add(f"1.0.8802.1.1.2.1.4.2.1.3.{idx}.1.4.{mgmt_ip}", "2", 2)

    def arp(self, if_index, ip, mac):
        self.add(f"1.3.6.1.2.1.4.22.1.2.{if_index}.{ip}", "4x", mac_hex(mac))
        self.add(f"1.3.6.1.2.1.4.22.1.4.{if_index}.{ip}", "2", 3)

    def write(self, path: Path):
        key = lambda oid: tuple(int(x) for x in oid.split("."))  # noqa: E731
        lines = [f"{oid}|{t}|{v}" for oid, (t, v) in sorted(self.rows.items(), key=lambda kv: key(kv[0]))]
        path.write_text("\n".join(lines) + "\n")


BRIDGE, ROUTER, PHONE = 0x20, 0x08, 0x04          # LLDP capability bits (first octet)
PC_BEHIND_PHONE, PHONE_MAC = "AA:00:00:00:00:05", "00:04:F2:00:00:05"
PC12, PRINTER, SERVER = "AA:00:00:00:00:12", "AA:00:00:00:00:20", "AA:00:00:00:01:01"
CORE_MAC, ACCESS_MAC, ROUTER_MAC = "00:1A:2B:00:00:01", "00:1A:2B:00:00:02", "00:1A:2B:00:00:FE"
CISCO_SWITCH, CISCO_ROUTER = "1.3.6.1.4.1.9.1.2134", "1.3.6.1.4.1.9.1.1"


def core() -> Rec:
    r = Rec()
    r.system("Cisco IOS Software, C9300 Software\r\nTechnical Support: http://www.cisco.com", CISCO_SWITCH,
             "core-sw.corp.local")
    for p in (1, 2, 24):
        r.interface(10100 + p, f"Gi1/0/{p}", f"00:1A:2B:00:01:{p:02X}")
        r.bridge_port(p, 10100 + p, pvid=10)
        r.lldp_local(p, f"Gi1/0/{p}")
    r.lldp_remote(1, ACCESS_MAC, "Gi1/0/48", "access-sw.corp.local", "Cisco C9200", BRIDGE, "10.0.0.2")
    r.lldp_remote(24, ROUTER_MAC, "Gi0/0", "rtr-01.corp.local", "Cisco ISR", ROUTER, "10.0.0.254")
    for mac, port, vlan in ((PC12, 1, 20), (PRINTER, 1, 20), (PC_BEHIND_PHONE, 1, 20), (PHONE_MAC, 1, 30),
                            (SERVER, 2, 10), (ROUTER_MAC, 24, 10)):
        r.q_fdb(vlan, mac, port)
    return r


def access() -> Rec:
    r = Rec()
    r.system("Cisco IOS Software, C9200 Software", CISCO_SWITCH, "access-sw.corp.local")
    for p in (5, 12, 20, 48):
        r.interface(10100 + p, f"Gi1/0/{p}", f"00:1A:2B:00:02:{p:02X}")
        r.bridge_port(p, 10100 + p, pvid=20 if p != 48 else 1)
        r.lldp_local(p, f"Gi1/0/{p}")
    r.lldp_remote(48, CORE_MAC, "Gi1/0/1", "core-sw.corp.local", "Cisco C9300", BRIDGE, "10.0.0.1")
    r.lldp_remote(5, PHONE_MAC, "Port 1", "SEP0004F2000005", "Cisco IP Phone 8845", PHONE)
    for mac, port, vlan in ((PC_BEHIND_PHONE, 5, 20), (PHONE_MAC, 5, 30), (PC12, 12, 20), (PRINTER, 20, 20),
                            (SERVER, 48, 10), (ROUTER_MAC, 48, 10)):
        r.q_fdb(vlan, mac, port)
    return r


def router() -> Rec:
    r = Rec()
    r.system("Cisco IOS Software, ISR4331", CISCO_ROUTER, "rtr-01.corp.local")
    r.interface(1, "Gi0/0", ROUTER_MAC)
    r.interface(2, "Gi0/1", "00:1A:2B:00:00:FD")
    cdp = "1.3.6.1.4.1.9.9.23.1.2.1.1"
    r.add(f"{cdp}.4.1.1", "4x", "0a000001")                      # 10.0.0.1
    r.add(f"{cdp}.6.1.1", "4", "core-sw.corp.local")
    r.add(f"{cdp}.7.1.1", "4", "GigabitEthernet1/0/24")
    r.add(f"{cdp}.8.1.1", "4", "cisco C9300-48P")
    r.add(f"{cdp}.9.1.1", "4x", "00000028")                      # switch + IGMP
    for ip, mac in (("10.20.0.5", PC_BEHIND_PHONE), ("10.20.0.12", PC12), ("10.20.0.20", PRINTER),
                    ("10.30.0.6", PHONE_MAC), ("10.10.0.10", SERVER), ("10.0.0.1", CORE_MAC)):
        r.arp(1, ip, mac)
    return r


def legacy() -> dict:
    base = Rec()
    base.system("Cisco IOS Software, C2960 Software", CISCO_SWITCH, "legacy-sw.corp.local")
    for p in (1, 2):
        base.interface(10100 + p, f"Fa0/{p}", f"00:1A:2B:00:03:{p:02X}", speed=100)
    for vlan in (10, 20):
        base.add(f"1.3.6.1.4.1.9.9.46.1.3.1.1.2.1.{vlan}", "2", 1)
    base.add("1.3.6.1.4.1.9.9.46.1.3.1.1.2.1.1002", "2", 1)     # token-ring default: ignored
    per_vlan = {}
    for vlan, port, mac in ((10, 1, "BB:00:00:00:00:10"), (20, 2, "BB:00:00:00:00:20")):
        v = Rec()
        v.bridge_port(port, 10100 + port)
        v.tp_fdb(mac, port)
        per_vlan[f"legacy@{vlan}"] = v
    return {"legacy": base, **per_vlan}


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent / "data")
    out.mkdir(parents=True, exist_ok=True)
    recs = {"core": core(), "access": access(), "router": router(), **legacy()}
    for name, rec in recs.items():
        rec.write(out / f"{name}.snmprec")
    print(f"wrote {len(recs)} recordings to {out}")
