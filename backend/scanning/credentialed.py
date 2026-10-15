"""
Credentialed inventory of one host, as part of a scan run.

Rules for using stored credentials (account-lockout safe):
- only credentials assigned to the scan target are used, and only against
  addresses inside that target;
- per method, at most MAX_CREDENTIALS_PER_METHOD are tried per host per run;
- the credential that last worked for the host is tried first;
- trying stops at the first success, and moves to the next method when the
  service isn't reachable (another credential wouldn't help).
"""
from __future__ import annotations

import asyncio
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

import asyncssh
from sqlalchemy import select

from backend.models.ssh_host_key import SshHostKey
from backend.schemas.inventory import InventoryReport
from backend.scanning.collectors import AUTH_CODES, CollectorError, CredentialInput
from backend.scanning.collectors import snmp as snmp_collector
from backend.scanning.collectors import ssh as ssh_collector
from backend.scanning.collectors import winrm as winrm_collector

METHOD_ORDER = ("winrm", "ssh", "snmp")
METHOD_CRED_TYPES = {
    "winrm": {"windows"},
    "ssh": {"ssh_password", "ssh_key"},
    "snmp": {"snmp_v2c", "snmp_v3"},
}
CRED_TYPE_METHOD = {t: m for m, types in METHOD_CRED_TYPES.items() for t in types}
MAX_CREDENTIALS_PER_METHOD = 3


@dataclass
class Attempt:
    method: str
    credential_id: int
    code: Optional[str] = None          # None = success
    message: Optional[str] = None


@dataclass
class HostOutcome:
    report: Optional[InventoryReport] = None
    method: Optional[str] = None
    credential_id: Optional[int] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    attempts: List[Attempt] = field(default_factory=list)
    duration_ms: int = 0


class HostKeyStore:
    """SSH trust-on-first-use backed by ssh_host_keys."""

    def __init__(self, session_factory):
        self._sessions = session_factory

    async def lookup(self, host: str, port: int) -> Optional[str]:
        async with self._sessions() as db:
            row = (await db.execute(select(SshHostKey).where(
                SshHostKey.host == host, SshHostKey.port == port))).scalars().first()
            if row:
                row.last_seen = datetime.now(timezone.utc)
                await db.commit()
                return row.public_key
        return None

    async def save(self, host: str, port: int, key: asyncssh.SSHKey) -> None:
        async with self._sessions() as db:
            db.add(SshHostKey(host=host, port=port, key_type=key.get_algorithm(),
                              public_key=key.export_public_key().decode().strip(),
                              fingerprint=key.get_fingerprint()))
            await db.commit()


def _tcp_open(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


async def _reachable(host: str, method: str, creds: List[CredentialInput]) -> bool:
    """Cheap pre-check so hosts without the service don't use up credential attempts."""
    if method == "winrm":
        ports = (winrm_collector.HTTP_PORT, winrm_collector.HTTPS_PORT)
    elif method == "ssh":
        ports = tuple({int(c.params.get("port") or 22) for c in creds})
    else:
        return True   # SNMP is UDP: the only way to know is to ask
    results = await asyncio.gather(*(asyncio.to_thread(_tcp_open, host, p) for p in ports))
    return any(results)


async def _run(method: str, host: str, cred: CredentialInput, keys: HostKeyStore) -> InventoryReport:
    if method == "winrm":
        return await winrm_collector.collect(host, cred)
    if method == "ssh":
        return await ssh_collector.collect(host, cred, keys.lookup, keys.save)
    return await snmp_collector.collect(host, cred)


async def inventory_host(host: str, methods: List[str], credentials: List[CredentialInput],
                         keys: HostKeyStore, preferred_credential_id: Optional[int] = None) -> HostOutcome:
    started = time.monotonic()
    outcome = HostOutcome()
    for method in METHOD_ORDER:
        if method not in methods:
            continue
        creds = [c for c in credentials if c.cred_type in METHOD_CRED_TYPES[method]]
        creds.sort(key=lambda c: c.id != preferred_credential_id)       # stable: keeps target order
        creds = creds[:MAX_CREDENTIALS_PER_METHOD]
        if not creds or not await _reachable(host, method, creds):
            continue
        for cred in creds:
            try:
                report = await _run(method, host, cred, keys)
            except CollectorError as exc:
                outcome.attempts.append(Attempt(method, cred.id, exc.code, exc.message))
                outcome.error_code, outcome.error_message = exc.code, exc.message
                outcome.credential_id, outcome.method = cred.id, method
                if exc.code in AUTH_CODES:
                    continue            # a different account may work
                break                   # unreachable, untrusted, script error: next method
            outcome.attempts.append(Attempt(method, cred.id))
            outcome.report, outcome.method, outcome.credential_id = report, method, cred.id
            outcome.error_code = outcome.error_message = None
            if report.collector_version and report.collector_version.startswith("ssh-basic"):
                outcome.error_code = "no_python"
                outcome.error_message = CollectorError("no_python").message
            outcome.duration_ms = int((time.monotonic() - started) * 1000)
            return outcome
    outcome.duration_ms = int((time.monotonic() - started) * 1000)
    return outcome


async def test_credential(host: str, cred: CredentialInput, keys: HostKeyStore) -> Dict[str, object]:
    """Sign in with one credential and run a harmless query; nothing is stored."""
    method = CRED_TYPE_METHOD.get(cred.cred_type)
    if method == "winrm":
        info = await winrm_collector.test(host, cred)
    elif method == "ssh":
        info = await ssh_collector.test(host, cred, keys.lookup, keys.save)
    elif method == "snmp":
        info = await snmp_collector.test(host, cred)
    else:
        raise CollectorError("not_supported", cred.cred_type)
    return {"method": method, **info}
