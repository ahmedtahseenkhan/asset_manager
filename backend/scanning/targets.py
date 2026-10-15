"""
Scan-target address specs → concrete IPv4 addresses.

    cidr   "192.168.1.0/24"                       (several allowed, comma/newline separated)
    range  "10.0.0.10-10.0.0.50" or "10.0.0.10-50"
    hosts  "srv01, srv02.corp.local, 10.0.0.7"    (names resolved via DNS)
    ad     "OU=Workstations,DC=corp,DC=local" or "*" — computer objects from the
           configured Active Directory connector, resolved via DNS (use resolve())

Exclusions use the same syntax as cidr/range/hosts entries.
"""
from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from typing import Iterable, List, Set

TARGET_TYPES = ("cidr", "range", "hosts", "ad")
MAX_ADDRESSES = 4096   # same ceiling as the network-scan connector (/20)

_SPLIT = re.compile(r"[,\s;]+")


class TargetSpecError(ValueError):
    pass


def _entries(spec: str) -> List[str]:
    return [e for e in _SPLIT.split(spec or "") if e]


def _expand_range(entry: str) -> Iterable[ipaddress.IPv4Address]:
    start_s, end_s = entry.split("-", 1)
    start = ipaddress.IPv4Address(start_s.strip())
    end_s = end_s.strip()
    if "." not in end_s:                       # shorthand: 10.0.0.10-50
        end_s = start_s.rsplit(".", 1)[0] + "." + end_s
    end = ipaddress.IPv4Address(end_s)
    if end < start:
        raise TargetSpecError(f"Range {entry!r} ends before it starts")
    if int(end) - int(start) + 1 > MAX_ADDRESSES:
        raise TargetSpecError(f"Range {entry!r} exceeds {MAX_ADDRESSES} addresses")
    return (ipaddress.IPv4Address(i) for i in range(int(start), int(end) + 1))


def _expand_entry(entry: str, resolve_names: bool) -> Iterable[ipaddress.IPv4Address]:
    try:
        if "/" in entry:
            net = ipaddress.IPv4Network(entry, strict=False)
            if net.num_addresses > MAX_ADDRESSES:
                raise TargetSpecError(
                    f"{net} has {net.num_addresses} addresses; maximum is {MAX_ADDRESSES} (/20)")
            return list(net.hosts()) if net.prefixlen < 31 else list(net)
        if "-" in entry and re.match(r"^\d+\.\d+\.\d+\.\d+-", entry):
            return list(_expand_range(entry))
        return [ipaddress.IPv4Address(entry)]
    except ipaddress.AddressValueError:
        pass
    except ValueError as exc:
        if isinstance(exc, TargetSpecError):
            raise
        raise TargetSpecError(f"Invalid address {entry!r}: {exc}") from exc
    if not resolve_names:
        raise TargetSpecError(f"Invalid address {entry!r}")
    try:
        infos = socket.getaddrinfo(entry, None, socket.AF_INET)
    except socket.gaierror as exc:
        raise TargetSpecError(f"Cannot resolve host {entry!r}") from exc
    return [ipaddress.IPv4Address(i[4][0]) for i in infos]


def expand(target_type: str, value: str, exclusions: str = "") -> List[str]:
    """Sorted, de-duplicated addresses. Raises TargetSpecError on bad input."""
    if target_type not in TARGET_TYPES:
        raise TargetSpecError(f"Unknown target type {target_type!r}")
    if target_type == "ad":
        raise TargetSpecError("Active Directory targets need the directory; use resolve()")
    entries = _entries(value)
    if not entries:
        raise TargetSpecError("Target has no addresses")
    if target_type == "cidr" and any("/" not in e for e in entries):
        raise TargetSpecError("CIDR targets need a prefix, e.g. 192.168.1.0/24")
    if target_type == "range" and any("-" not in e for e in entries):
        raise TargetSpecError("Range targets look like 10.0.0.10-10.0.0.50")

    addrs: Set[ipaddress.IPv4Address] = set()
    for e in entries:
        addrs.update(_expand_entry(e, resolve_names=(target_type == "hosts")))
        if len(addrs) > MAX_ADDRESSES:
            raise TargetSpecError(f"Target exceeds {MAX_ADDRESSES} addresses")
    for e in _entries(exclusions):
        addrs.difference_update(_expand_entry(e, resolve_names=True))
    if not addrs:
        raise TargetSpecError("Every address is excluded")
    return [str(a) for a in sorted(addrs)]


def _ad_computer_names(config: dict, base: str) -> List[str]:
    """DNS names of computer objects under `base`. Raises TargetSpecError with
    the directory's own error, so a bad bind isn't mistaken for an empty OU."""
    import ldap3
    from ldap3.core.exceptions import LDAPException
    from backend.connectors.ad.connector import ActiveDirectoryConnector

    try:
        conn = ActiveDirectoryConnector()._get_connection(config)
        conn.search(search_base=base, search_filter="(&(objectCategory=computer)(objectClass=computer))",
                    attributes=["dNSHostName", "name"], search_scope=ldap3.SUBTREE, paged_size=1000)
        names = [str(e.dNSHostName.value or e.name.value) for e in conn.entries
                 if (e.dNSHostName.value or e.name.value)]
        conn.unbind()
    except LDAPException as exc:
        raise TargetSpecError(f"Active Directory query failed: {exc}") from exc
    return names


def _lookup(name: str) -> List[ipaddress.IPv4Address]:
    try:
        return [ipaddress.IPv4Address(i[4][0]) for i in socket.getaddrinfo(name, None, socket.AF_INET)]
    except (socket.gaierror, UnicodeError):
        return []


async def resolve(db, target_type: str, value: str, exclusions: str = "") -> List[str]:
    """Addresses for any target type (AD included). Raises TargetSpecError."""
    if target_type != "ad":
        return await asyncio.to_thread(expand, target_type, value, exclusions)

    from sqlalchemy import select
    from backend.models.connector_config import ConnectorConfig

    cfg = (await db.execute(select(ConnectorConfig).where(ConnectorConfig.connector_name == "ad"))).scalars().first()
    if cfg is None or not cfg.config:
        raise TargetSpecError("Configure the Active Directory connector first (Connectors → Active Directory)")
    base = value.strip()
    if base in ("", "*"):
        base = cfg.config.get("search_base") or ""
    names = await asyncio.to_thread(_ad_computer_names, cfg.config, base)
    if not names:
        raise TargetSpecError(f"No computer objects found under {base}")

    sem = asyncio.Semaphore(32)

    async def one(name: str):
        async with sem:
            return await asyncio.to_thread(_lookup, name)

    addrs: Set[ipaddress.IPv4Address] = set()
    for found in await asyncio.gather(*(one(n) for n in names)):
        addrs.update(found)
    if len(addrs) > MAX_ADDRESSES:
        raise TargetSpecError(f"Target exceeds {MAX_ADDRESSES} addresses")
    for e in _entries(exclusions):
        addrs.difference_update(_expand_entry(e, resolve_names=True))
    if not addrs:
        raise TargetSpecError(f"None of the {len(names)} computers resolved to an address in DNS")
    return [str(a) for a in sorted(addrs)]
