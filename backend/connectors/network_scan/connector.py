"""
Local-network discovery connector: ICMP ping sweep + ARP table + reverse DNS.

Finds live devices on the configured subnet without needing AD or any EDR
agent — useful for small sites and for catching unmanaged hardware. Works
fully offline (no external services).

How liveness is decided:
- a host that answers ping is alive;
- a host that appears in the ARP table with a valid MAC is ALSO alive, even
  if it dropped the ping (Windows firewalls commonly block ICMP echo, but a
  live host must still answer ARP on its own L2 segment).

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
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.connectors.base import BaseConnector, RawDeviceRecord

_MAX_HOSTS = 4096          # refuse to sweep anything larger than a /20
_CONCURRENCY = 64
_ARP_RE = re.compile(r"\(([\d.]+)\) at ([0-9a-fA-F:]+)")
_SKIP_MACS = {"00:00:00:00:00:00", "FF:FF:FF:FF:FF:FF"}


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
    if sys.platform == "darwin":
        return ["ping", "-c", "1", "-W", str(timeout_ms), "-n", "-q", ip]
    if sys.platform.startswith("win"):
        return ["ping", "-n", "1", "-w", str(timeout_ms), ip]
    # Linux: -W takes seconds
    return ["ping", "-c", "1", "-W", str(max(1, timeout_ms // 1000)), "-n", "-q", ip]


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

        async def ping(ip: str) -> bool:
            async with sem:
                try:
                    proc = await asyncio.create_subprocess_exec(
                        *_ping_cmd(ip, timeout_ms),
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    rc = await asyncio.wait_for(proc.wait(), timeout=timeout_ms / 1000 + 2)
                    return rc == 0
                except (OSError, asyncio.TimeoutError):
                    return False

        hosts = [str(h) for h in net.hosts()]
        ping_ok = dict(zip(hosts, await asyncio.gather(*(ping(h) for h in hosts))))

        # The sweep itself populates the ARP cache; hosts with a MAC are alive
        # even when their firewall dropped the ICMP echo.
        arp = await _arp_table()
        local = _local_ip()
        alive = {ip for ip, ok in ping_ok.items() if ok} | {
            ip for ip in arp if ip in ping_ok
        }

        now = datetime.now(timezone.utc)
        records: List[RawDeviceRecord] = []

        names = dict(zip(alive, await asyncio.gather(*(_reverse_dns(ip) for ip in alive))))
        for ip in sorted(alive, key=ipaddress.IPv4Address):
            if ip == local:
                continue   # the scanning host is added below with richer detail
            fqdn = names.get(ip)
            hostname = fqdn.split(".")[0] if fqdn else None
            mac = arp.get(ip)
            records.append({
                "source_uid": mac or f"ip-{ip}",
                "hostname": hostname,
                "fqdn": fqdn if (fqdn and "." in fqdn) else None,
                "ip_addresses": [ip],
                "mac_addresses": [mac] if mac else [],
                "os_name": None,           # a ping sweep cannot fingerprint the OS
                "os_version": None,
                "domain": None,
                "ou": None,
                "last_seen": now,
                "extra": {"ping": ping_ok.get(ip, False), "arp": ip in arp,
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
