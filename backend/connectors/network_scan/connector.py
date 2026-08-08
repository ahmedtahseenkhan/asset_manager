"""
Local-network discovery connector: ICMP ping sweep + ARP table, enriched with
active name/OS probes — all agentless and fully offline (no external services).

Per live host it gathers:
- liveness  — answers ping, OR appears in the ARP table (Windows firewalls
              commonly drop ICMP echo but a live host still answers ARP);
- hostname  — reverse DNS, else NetBIOS node-status (Windows/SMB), else mDNS
              (Apple/IoT/printers). First hit wins, in that order;
- os family — inferred from the ICMP reply TTL (128≈Windows, 64≈Unix/macOS/
              Linux, 255≈network gear). A scan cannot read the OS *version*;
              that needs an agent (AD/EDR connectors).

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
        net = _resolve_subnet(config)
        proc = await asyncio.create_subprocess_exec(
            *_ping_cmd(str(next(net.hosts())), 200),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()
        return True

    async def fetch_devices(self, config: Dict[str, Any]) -> List[RawDeviceRecord]:
        net = _resolve_subnet(config)
        timeout_ms = int(config.get("timeout_ms", 1000))
        sem = asyncio.Semaphore(_CONCURRENCY)

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

        hosts = [str(h) for h in net.hosts()]
        ping_res = dict(zip(hosts, await asyncio.gather(*(ping(h) for h in hosts))))
        ping_ok = {ip: r[0] for ip, r in ping_res.items()}
        ttls = {ip: r[1] for ip, r in ping_res.items()}

        # The sweep itself populates the ARP cache; hosts with a MAC are alive
        # even when their firewall dropped the ICMP echo.
        arp = await _arp_table()
        local = _local_ip()
        alive = {ip for ip, ok in ping_ok.items() if ok} | {
            ip for ip in arp if ip in ping_ok
        }

        now = datetime.now(timezone.utc)
        records: List[RawDeviceRecord] = []

        # Resolve a name for each host: reverse DNS → NetBIOS → mDNS (first hit).
        async def resolve(ip: str) -> Tuple[str, Optional[str], str]:
            rdns = await _reverse_dns(ip)
            if rdns:
                return ip, rdns, "reverse_dns"
            nb = await asyncio.to_thread(_netbios_name, ip)
            if nb:
                return ip, nb, "netbios"
            md = await asyncio.to_thread(_mdns_name, ip)
            if md:
                return ip, md, "mdns"
            return ip, None, "none"

        resolved = {ip: (name, src) for ip, name, src
                    in await asyncio.gather(*(resolve(ip) for ip in alive if ip != local))}

        for ip in sorted(alive, key=ipaddress.IPv4Address):
            if ip == local:
                continue   # the scanning host is added below with richer detail
            name, name_src = resolved.get(ip, (None, "none"))
            fqdn = name if (name and "." in name) else None
            hostname = name.split(".")[0] if name else None
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
                "os_name": _os_from_ttl(ttls.get(ip)),   # family only; version needs an agent
                "os_version": None,
                "domain": None,
                "ou": None,
                "last_seen": now,
                "extra": {"ping": ping_ok.get(ip, False), "arp": ip in arp,
                          "ttl": ttls.get(ip), "name_source": name_src,
                          "method": "ping_sweep"},
            })

        # Always include the machine running the scan (it never ARPs itself).
        if local and ipaddress.ip_address(local) in net:
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
            },
        }
