"""
Local-network discovery connector: ICMP ping sweep + ARP table, enriched with
active name/OS probes — all agentless and fully offline (no external services).

Per live host it gathers:
- liveness  — answers ping, OR appears in the ARP table (Windows firewalls
              commonly drop ICMP echo but a live host still answers ARP);
- hostname  — reverse DNS → NetBIOS node-status (Windows/SMB) → mDNS
              (Apple/IoT) → SNMP sysName → SSDP friendlyName. First hit wins;
- os / role — SNMP sysDescr (routers/printers) → open-port classification
              (445/3389→Windows, 631/9100→printer, 62078→iOS, …) → ICMP TTL
              (128≈Windows, 64≈Unix/macOS/Linux). Deep-probe adds SSDP model +
              manufacturer for routers/TVs/IoT. A scan still cannot read the
              exact OS *version* or serial — that needs an agent (AD/EDR).

The active probes (SSDP, SNMP, port-scan) run when deep_probe is enabled
(default). They are best-effort and agentless; firewalled hosts stay sparse.

Note for containerised deployments: a bridge-networked container only sees
its own virtual subnet. Run the API with host networking (Linux) or run the
scan from a host-installed instance to sweep the real LAN.
"""
from __future__ import annotations

import asyncio
import ipaddress
import platform
import re
import socket
import struct
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from backend.connectors.base import BaseConnector, RawDeviceRecord

_MAX_HOSTS = 4096          # refuse to sweep anything larger than a /20
_CONCURRENCY = 64
_ARP_RE = re.compile(r"\(([\d.]+)\) at ([0-9a-fA-F:]+)")
_TTL_RE = re.compile(r"ttl[=\s](\d+)", re.IGNORECASE)
_SKIP_MACS = {"00:00:00:00:00:00", "FF:FF:FF:FF:FF:FF"}


def _os_from_ttl(ttl: Optional[int]) -> Optional[str]:
    """Initial TTLs are powers-of-two ceilings; on-subnet hosts arrive undecremented."""
    if ttl is None:
        return None
    if ttl > 128:
        return "Network device"        # 255 — routers, switches, printers
    if ttl > 64:
        return "Windows"               # 128
    if ttl > 32:
        return "Unix/macOS/Linux"      # 64
    return None


def _netbios_name(ip: str, timeout: float = 1.2, attempts: int = 2) -> Optional[str]:
    """NetBIOS node-status query (UDP 137). Returns the workstation name if any.

    UDP is lossy and Windows hosts answer intermittently, so retry a couple of
    times before giving up — this is what reliably names Windows machines.
    """
    # Header + question for the wildcard name '*' (NBSTAT / IN).
    wildcard = b"CKAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"  # encoded '*'+15 nulls
    query = struct.pack(">6H", 0x4B4E, 0x0010, 1, 0, 0, 0) \
        + b"\x20" + wildcard + b"\x00" + struct.pack(">2H", 0x0021, 0x0001)
    data = None
    for _ in range(attempts):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.settimeout(timeout)
                s.sendto(query, (ip, 137))
                data, _ = s.recvfrom(2048)
                break
        except OSError:
            continue
    if data is None:
        return None
    # RDATA starts after the 12-byte header + echoed question (34) + RR fixed (10).
    try:
        off = 12 + 34 + 10
        count = data[off]
        off += 1
        for _ in range(count):
            raw = data[off:off + 15].rstrip(b" \x00")
            suffix = data[off + 15]
            flags = struct.unpack(">H", data[off + 16:off + 18])[0]
            off += 18
            is_group = bool(flags & 0x8000)
            # suffix 0x00, unique = the machine (workstation) name
            if suffix == 0x00 and not is_group:
                name = raw.decode("ascii", "ignore").strip()
                if name:
                    return name
    except (IndexError, struct.error):
        return None
    return None


def _mdns_name(ip: str, timeout: float = 1.0) -> Optional[str]:
    """Unicast mDNS reverse (PTR) query on UDP 5353. Returns e.g. 'device.local'."""
    labels = ip.split(".")[::-1] + ["in-addr", "arpa"]
    qname = b"".join(bytes([len(l)]) + l.encode() for l in labels) + b"\x00"
    query = struct.pack(">6H", 0, 0, 1, 0, 0, 0) + qname + struct.pack(">2H", 12, 1)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(timeout)
            s.sendto(query, (ip, 5353))
            data, _ = s.recvfrom(2048)
    except OSError:
        return None
    # Parse the first PTR answer's target name, following DNS label compression.
    try:
        def read_name(pos: int) -> Tuple[str, int]:
            parts, jumped, end = [], False, pos
            while True:
                ln = data[pos]
                if ln & 0xC0 == 0xC0:               # compression pointer
                    ptr = struct.unpack(">H", data[pos:pos + 2])[0] & 0x3FFF
                    if not jumped:
                        end = pos + 2
                    pos, jumped = ptr, True
                    continue
                if ln == 0:
                    pos += 1
                    break
                parts.append(data[pos + 1:pos + 1 + ln].decode("ascii", "ignore"))
                pos += 1 + ln
            return ".".join(parts), (end if jumped else pos)

        qdcount, ancount = struct.unpack(">2H", data[4:8])
        pos = 12
        for _ in range(qdcount):                    # skip echoed question
            _, pos = read_name(pos)
            pos += 4
        for _ in range(ancount):
            _, pos = read_name(pos)
            rtype = struct.unpack(">H", data[pos:pos + 2])[0]
            pos += 8
            rdlen = struct.unpack(">H", data[pos:pos + 2])[0]
            pos += 2
            if rtype == 12:                         # PTR
                target, _ = read_name(pos)
                return target.rstrip(".") or None
            pos += rdlen
    except (IndexError, struct.error):
        return None
    return None


def _local_ip() -> Optional[str]:
    """Local interface IP via a connected UDP socket (no packets are sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.254.254.254", 1))
            return s.getsockname()[0]
    except OSError:
        return None


# ── Port scan: classify OS/role from open TCP ports ───────────────────────
# Each port maps to a hint; the strongest hint wins when several are open.
_PORT_HINTS = {
    3389: ("Windows", "workstation/server (RDP)"),
    445:  ("Windows", "workstation/server (SMB)"),
    139:  ("Windows", "workstation/server (NetBIOS)"),
    135:  ("Windows", "workstation/server (RPC)"),
    5985: ("Windows", "managed host (WinRM)"),
    5986: ("Windows", "managed host (WinRM over HTTPS)"),
    5357: ("Windows", "workstation (WSD)"),
    62078: ("iOS", "iPhone/iPad"),
    9100: (None, "printer (JetDirect)"),
    631:  (None, "printer (IPP)"),
    515:  (None, "printer (LPD)"),
    548:  ("macOS", "Mac (AFP)"),
    22:   (None, "SSH host (Linux/Unix/network)"),
    5900: (None, "VNC host"),
    1883: (None, "IoT (MQTT)"),
    80:   (None, "web UI (router/IoT)"),
    443:  (None, "web UI (router/IoT)"),
    8080: (None, "web UI (router/IoT)"),
}
_SCAN_PORTS = list(_PORT_HINTS)


async def _port_scan(ip: str, timeout: float = 0.6) -> List[int]:
    """Return the open TCP ports from the probe list (parallel connect scan)."""
    async def check(port: int) -> Optional[int]:
        try:
            fut = asyncio.open_connection(ip, port)
            _, w = await asyncio.wait_for(fut, timeout=timeout)
            w.close()
            try:
                await w.wait_closed()
            except OSError:
                pass
            return port
        except (OSError, asyncio.TimeoutError):
            return None

    results = await asyncio.gather(*(check(p) for p in _SCAN_PORTS))
    return sorted(p for p in results if p is not None)


def _classify_ports(open_ports: List[int]) -> Tuple[Optional[str], Optional[str]]:
    """(os_hint, role_hint) derived from open ports, honouring _PORT_HINTS order."""
    os_hint = role = None
    for port in _SCAN_PORTS:                 # iterate by priority
        if port in open_ports:
            os_h, role_h = _PORT_HINTS[port]
            if os_hint is None and os_h:
                os_hint = os_h
            if role is None:
                role = role_h
    return os_hint, role


# ── SNMP v1: sysDescr / sysName (routers, printers, switches) ──────────────
def _snmp_get(ip: str, community: str = "public", timeout: float = 1.0) -> Dict[str, str]:
    """Minimal SNMPv1 GET for sysDescr.0 and sysName.0. Returns {} on no reply."""
    def _tlv(tag: int, val: bytes) -> bytes:
        return bytes([tag]) + bytes([len(val)]) + val   # lengths here are always <128

    def _int(n: int) -> bytes:
        return _tlv(0x02, n.to_bytes((n.bit_length() // 8) + 1, "big") or b"\x00")

    def _oid(parts: List[int]) -> bytes:
        body = bytes([parts[0] * 40 + parts[1]])
        for p in parts[2:]:
            if p < 128:
                body += bytes([p])
            else:
                stack = []
                while p:
                    stack.insert(0, p & 0x7F)
                    p >>= 7
                body += bytes([b | 0x80 for b in stack[:-1]] + [stack[-1]])
        return _tlv(0x06, body)

    sys_descr = [1, 3, 6, 1, 2, 1, 1, 1, 0]
    sys_name = [1, 3, 6, 1, 2, 1, 1, 5, 0]
    varbinds = b"".join(
        _tlv(0x30, _oid(o) + _tlv(0x05, b""))     # OID + NULL
        for o in (sys_descr, sys_name)
    )
    pdu = _tlv(0xA0, _int(0x2A) + _int(0) + _int(0) + _tlv(0x30, varbinds))
    msg = _tlv(0x30, _int(0) + _tlv(0x04, community.encode()) + pdu)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(timeout)
            s.sendto(msg, (ip, 161))
            data, _ = s.recvfrom(4096)
    except OSError:
        return {}

    # Collect the OCTET STRING values in order (sysDescr, then sysName).
    strings, i = [], 0
    while i < len(data) - 1:
        if data[i] == 0x04:
            ln = data[i + 1]
            if ln < 128 and i + 2 + ln <= len(data):
                val = data[i + 2:i + 2 + ln]
                if val and val != community.encode():
                    strings.append(val.decode("utf-8", "ignore"))
                i += 2 + ln
                continue
        i += 1
    out = {}
    if strings:
        out["sys_descr"] = strings[0]
    if len(strings) > 1:
        out["sys_name"] = strings[1]
    return out


# ── SSDP / UPnP: model + manufacturer (routers, TVs, media, IoT) ───────────
def _ssdp_discover_sync(timeout: float = 2.0) -> Dict[str, Dict[str, str]]:
    """One multicast M-SEARCH; returns {ip: {'server':..., 'location':...}}.

    Blocking sockets (run via a thread) — uvloop does not implement the
    asyncio sock_sendto/sock_recvfrom datagram helpers.
    """
    msg = (
        "M-SEARCH * HTTP/1.1\r\n"
        "HOST: 239.255.255.250:1900\r\n"
        'MAN: "ssdp:discover"\r\n'
        "MX: 1\r\n"
        "ST: ssdp:all\r\n\r\n"
    ).encode()

    found: Dict[str, Dict[str, str]] = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    deadline = timeout
    try:
        sock.sendto(msg, ("239.255.255.250", 1900))
        sock.settimeout(0.5)
        import time
        start = time.monotonic()
        while time.monotonic() - start < deadline:
            try:
                data, addr = sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            text = data.decode("utf-8", "ignore")
            entry = found.setdefault(addr[0], {})
            for line in text.split("\r\n"):
                low = line.lower()
                if low.startswith("server:"):
                    entry["server"] = line.split(":", 1)[1].strip()
                elif low.startswith("location:"):
                    entry["location"] = line.split(":", 1)[1].strip()
    except OSError:
        pass
    finally:
        sock.close()
    return found


async def _ssdp_discover(timeout: float = 2.0) -> Dict[str, Dict[str, str]]:
    return await asyncio.to_thread(_ssdp_discover_sync, timeout)


async def _ssdp_device_details(location: str, timeout: float = 2.0) -> Dict[str, str]:
    """Fetch the UPnP description XML for friendlyName / manufacturer / modelName."""
    try:
        import urllib.request

        def _fetch() -> str:
            with urllib.request.urlopen(location, timeout=timeout) as r:
                return r.read(65536).decode("utf-8", "ignore")

        xml = await asyncio.to_thread(_fetch)
    except Exception:
        return {}
    out = {}
    for tag in ("friendlyName", "manufacturer", "modelName", "modelDescription"):
        m = re.search(rf"<{tag}>(.*?)</{tag}>", xml, re.DOTALL)
        if m:
            out[tag] = m.group(1).strip()
    return out


def _resolve_subnet(config: Dict[str, Any]) -> ipaddress.IPv4Network:
    subnet = (config.get("subnet") or "auto").strip()
    if subnet == "auto":
        ip = _local_ip()
        if not ip:
            raise ValueError("Could not auto-detect the local subnet; set 'subnet' explicitly")
        return ipaddress.ip_network(f"{ip}/24", strict=False)
    net = ipaddress.ip_network(subnet, strict=False)
    if net.num_addresses > _MAX_HOSTS:
        raise ValueError(f"Subnet {net} has {net.num_addresses} addresses; "
                         f"maximum supported is {_MAX_HOSTS} (use /20 or smaller)")
    return net


def _target_hosts(config: Dict[str, Any]) -> List[str]:
    """Addresses to sweep: an explicit `addresses` list (scan targets expand
    ranges and host lists into one), else every host in the subnet."""
    if config.get("addresses"):
        return [str(ipaddress.ip_address(a)) for a in config["addresses"]]
    return [str(h) for h in _resolve_subnet(config).hosts()]


def _ping_cmd(ip: str, timeout_ms: int) -> List[str]:
    # No -q: we parse the per-reply line for the TTL (OS fingerprint).
    if sys.platform == "darwin":
        return ["ping", "-c", "1", "-W", str(timeout_ms), "-n", ip]
    if sys.platform.startswith("win"):
        return ["ping", "-n", "1", "-w", str(timeout_ms), ip]
    # Linux: -W takes seconds
    return ["ping", "-c", "1", "-W", str(max(1, timeout_ms // 1000)), "-n", ip]


def _normalize_mac(mac: str) -> str:
    """macOS arp prints single-digit octets (a4:83:e7:1:2:3) — zero-pad them."""
    return ":".join(o.zfill(2) for o in mac.split(":")).upper()


async def _arp_table() -> Dict[str, str]:
    """ip -> MAC from the OS ARP cache."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "arp", "-an",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
    except (OSError, asyncio.TimeoutError):
        return {}
    table = {}
    for ip, mac in _ARP_RE.findall(out.decode(errors="replace")):
        mac = _normalize_mac(mac)
        if mac not in _SKIP_MACS:
            table[ip] = mac
    return table


async def _reverse_dns(ip: str) -> Optional[str]:
    try:
        name = await asyncio.wait_for(
            asyncio.to_thread(lambda: socket.gethostbyaddr(ip)[0]), timeout=1.5
        )
        return name
    except (OSError, asyncio.TimeoutError):
        return None


class NetworkScanConnector(BaseConnector):
    name = "network_scan"
    display_name = "Network Scan (Ping Sweep)"

    async def test_connection(self, config: Dict[str, Any]) -> bool:
        # Valid subnet + ping binary available = scan can run.
        hosts = _target_hosts(config)
        try:
            proc = await asyncio.create_subprocess_exec(
                *_ping_cmd(hosts[0], 200),
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
        except FileNotFoundError:
            # The sweep treats a failed ping as "host down", so without this
            # check a scan would silently find almost nothing.
            raise RuntimeError(
                "The 'ping' command is not installed on the server "
                "(Debian/Ubuntu: apt-get install iputils-ping)"
            )
        await proc.communicate()
        return True

    async def fetch_devices(self, config: Dict[str, Any]) -> List[RawDeviceRecord]:
        hosts = _target_hosts(config)
        timeout_ms = int(config.get("timeout_ms", 1000))
        sem = asyncio.Semaphore(int(config.get("concurrency") or _CONCURRENCY))

        async def ping(ip: str) -> Tuple[bool, Optional[int]]:
            """Returns (alive, ttl). TTL is parsed from the reply for OS guessing."""
            async with sem:
                try:
                    proc = await asyncio.create_subprocess_exec(
                        *_ping_cmd(ip, timeout_ms),
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    out, _ = await asyncio.wait_for(
                        proc.communicate(), timeout=timeout_ms / 1000 + 2)
                    if proc.returncode != 0:
                        return False, None
                    m = _TTL_RE.search(out.decode(errors="replace"))
                    return True, (int(m.group(1)) if m else None)
                except (OSError, asyncio.TimeoutError):
                    return False, None

        ping_res = dict(zip(hosts, await asyncio.gather(*(ping(h) for h in hosts))))
        ping_ok = {ip: r[0] for ip, r in ping_res.items()}
        ttls = {ip: r[1] for ip, r in ping_res.items()}

        # The sweep itself populates the ARP cache; hosts with a MAC are alive
        # even when their firewall dropped the ICMP echo.
        arp = await _arp_table()
        local = _local_ip()

        # Proxy-ARP guard: on routed/hotspot networks the gateway answers ARP for
        # every address with its own MAC. A MAC bound to many IPs is such an
        # artifact — those ARP-only addresses are not real hosts on our segment, so
        # trust only genuine ping responders for them (avoids inventing a whole /24).
        from collections import Counter
        mac_counts = Counter(m for m in arp.values() if m)
        proxy_macs = {m for m, c in mac_counts.items() if c >= 8}

        alive = {ip for ip, ok in ping_ok.items() if ok}          # ping responders always
        for ip, mac in arp.items():
            if ip in ping_ok and mac not in proxy_macs:            # real, uniquely-MAC'd host
                alive.add(ip)

        now = datetime.now(timezone.utc)
        records: List[RawDeviceRecord] = []
        deep = config.get("deep_probe", True)   # SSDP/SNMP/port-scan enrichment

        # SSDP is a single multicast query answered by many devices at once.
        ssdp: Dict[str, Dict[str, str]] = await _ssdp_discover() if deep else {}
        for ip, info in ssdp.items():
            if info.get("location"):
                info.update(await _ssdp_device_details(info["location"]))

        # Per-host enrichment: name resolution + (optionally) ports & SNMP.
        async def enrich(ip: str) -> Tuple[str, dict]:
            async with sem:
                out: dict = {}
                rdns = await _reverse_dns(ip)
                if rdns:
                    out["name"], out["name_source"] = rdns, "reverse_dns"
                else:
                    nb = await asyncio.to_thread(_netbios_name, ip)
                    if nb:
                        out["name"], out["name_source"] = nb, "netbios"
                    else:
                        md = await asyncio.to_thread(_mdns_name, ip)
                        out["name"], out["name_source"] = (md, "mdns") if md else (None, "none")
                if deep:
                    out["open_ports"] = await _port_scan(ip)
                    out["snmp"] = await asyncio.to_thread(_snmp_get, ip)
                return ip, out

        enriched = dict(await asyncio.gather(*(enrich(ip) for ip in alive if ip != local)))

        for ip in sorted(alive, key=ipaddress.IPv4Address):
            if ip == local:
                continue   # the scanning host is added below with richer detail
            e = enriched.get(ip, {})
            sd = ssdp.get(ip, {})
            open_ports = e.get("open_ports", [])
            snmp = e.get("snmp", {})
            port_os, port_role = _classify_ports(open_ports)

            # Hostname: DNS/NetBIOS/mDNS → SNMP sysName → SSDP friendlyName.
            name = e.get("name") or snmp.get("sys_name") or sd.get("friendlyName")
            name_src = e.get("name_source", "none")
            if not e.get("name") and snmp.get("sys_name"):
                name_src = "snmp"
            elif not e.get("name") and sd.get("friendlyName"):
                name_src = "ssdp"
            fqdn = name if (name and "." in name) else None
            hostname = name.split(".")[0] if name else None

            # OS: SNMP sysDescr (richest) → open-port hint → TTL guess.
            os_name = snmp.get("sys_descr") or port_os or _os_from_ttl(ttls.get(ip))

            # Human-readable device type/model for the detail view.
            model = None
            if sd.get("manufacturer") or sd.get("modelName"):
                model = " ".join(filter(None, [sd.get("manufacturer"), sd.get("modelName")]))

            mac = arp.get(ip)
            records.append({
                # IP is the stable identity for a passive scan — a device's MAC
                # may be absent from ARP or randomised (phones), which would
                # otherwise create duplicate rows across scans.
                "source_uid": f"netscan-{ip}",
                "hostname": hostname,
                "fqdn": fqdn,
                "ip_addresses": [ip],
                "mac_addresses": [mac] if mac else [],
                "os_name": os_name,
                "os_version": None,      # exact version needs an agent
                "domain": None,
                "ou": None,
                "last_seen": now,
                "extra": {
                    "ping": ping_ok.get(ip, False), "arp": ip in arp,
                    "ttl": ttls.get(ip), "name_source": name_src,
                    "open_ports": open_ports, "role": port_role,
                    "model": model, "ssdp_server": sd.get("server"),
                    "snmp_descr": snmp.get("sys_descr"),
                    "method": "ping_sweep",
                },
            })

        # Always include the machine running the scan (it never ARPs itself).
        if local and local in set(hosts):
            own_host = socket.gethostname()
            records.append({
                "source_uid": f"self-{own_host}",
                "hostname": own_host.split(".")[0],
                "fqdn": own_host if "." in own_host else None,
                "ip_addresses": [local],
                "mac_addresses": [],
                "os_name": f"{platform.system()} {platform.mac_ver()[0]}".strip()
                           if sys.platform == "darwin" else platform.system(),
                "os_version": platform.release(),
                "domain": None,
                "ou": None,
                "last_seen": now,
                "extra": {"method": "self", "scanner": True},
            })
        return records

    def get_config_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "required": ["subnet"],
            "properties": {
                "subnet": {
                    "type": "string",
                    "title": "Subnet (CIDR)",
                    "default": "auto",
                    "description": "e.g. 192.168.1.0/24 — or 'auto' to detect the local /24",
                },
                "timeout_ms": {
                    "type": "integer",
                    "title": "Ping timeout (ms)",
                    "default": 1000,
                },
                "deep_probe": {
                    "type": "boolean",
                    "title": "Deep probe (SSDP/SNMP/port-scan)",
                    "default": True,
                    "description": "Actively query each host for model, OS and role. "
                                   "Slower but far more detail. Disable for a quick sweep.",
                },
            },
        }
