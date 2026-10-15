"""
Linux / macOS / Unix inventory over SSH.

Pipes the Python agent (agent/itam_agent.py) to `python3 - --dry-run` on the
host and parses its JSON report — the same collector the installed agent runs.
Hosts without python3 get a basic identity report from a few shell commands.

Host keys use trust on first use: the key is fetched *before* authenticating
and stored; later connections accept only that key, so credentials are never
sent to a host whose key changed.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Awaitable, Callable, Optional

import asyncssh

from backend.schemas.inventory import InventoryReport
from backend.scanning.collectors import AGENT_DIR, CollectorError, CredentialInput

TIMEOUT_S = 180
# Trust the strongest key type the host offers; later connections then
# negotiate the same type because only that key is trusted.
_PREFERRED_HOST_KEY_ALGS = ("ssh-ed25519", "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384",
                            "ecdsa-sha2-nistp521", "rsa-sha2-512", "rsa-sha2-256", "ssh-rsa")

# (host, port) -> stored OpenSSH public key or None; and a saver for new keys.
KeyLookup = Callable[[str, int], Awaitable[Optional[str]]]
KeySaver = Callable[[str, int, asyncssh.SSHKey], Awaitable[None]]


def _port(cred: CredentialInput) -> int:
    return int(cred.params.get("port") or 22)


async def _trusted_key(host: str, port: int, lookup: KeyLookup, save: KeySaver) -> asyncssh.SSHKey:
    stored = await lookup(host, port)
    if stored:
        return asyncssh.import_public_key(stored)
    try:
        key = await asyncio.wait_for(asyncssh.get_server_host_key(
            host, port, config=None, server_host_key_algs=_PREFERRED_HOST_KEY_ALGS), 15)
    except (OSError, asyncio.TimeoutError, asyncssh.Error) as exc:
        raise CollectorError("unreachable", f"SSH port {port}: {exc}"[:200])
    if key is None:
        raise CollectorError("unreachable", f"no SSH host key from port {port}")
    await save(host, port, key)
    return key


async def _connect(host: str, cred: CredentialInput, lookup: KeyLookup, save: KeySaver):
    port = _port(cred)
    key = await _trusted_key(host, port, lookup, save)
    options = dict(host=host, port=port, username=cred.username, known_hosts=([key], [], []),
                   connect_timeout=15, login_timeout=20, agent_path=None, client_keys=None,
                   config=None,                  # never pick up ~/.ssh/config of the server account
                   password=None, preferred_auth="publickey,keyboard-interactive,password")
    if cred.cred_type == "ssh_password":
        options["password"] = cred.secret.get("password")
        options["preferred_auth"] = "keyboard-interactive,password"
    elif cred.cred_type == "ssh_key":
        try:
            options["client_keys"] = [asyncssh.import_private_key(
                cred.secret.get("private_key", ""), cred.secret.get("passphrase") or None)]
        except (asyncssh.KeyImportError, ValueError) as exc:
            raise CollectorError("auth_failed", f"private key unreadable: {exc}"[:200])
        options["preferred_auth"] = "publickey"
    else:
        raise CollectorError("not_supported", cred.cred_type)
    try:
        return await asyncssh.connect(**options)
    except asyncssh.HostKeyNotVerifiable:
        raise CollectorError("host_key_changed", f"{host}:{port}")
    except asyncssh.PermissionDenied:
        raise CollectorError("auth_failed", f"user {cred.username}")
    except (asyncio.TimeoutError, TimeoutError):
        raise CollectorError("timeout", f"SSH port {port}")
    except (OSError, asyncssh.Error) as exc:
        raise CollectorError("unreachable", f"SSH port {port}: {exc}"[:200])


def _sudo(cred: CredentialInput, command: str) -> str:
    # -n: never prompt; fails fast unless the account has NOPASSWD for it.
    return f"sudo -n {command}" if cred.params.get("sudo") == "yes" else command


async def _basic_report(conn) -> InventoryReport:
    """Identity from POSIX commands when python3 is missing."""
    out = await conn.run("hostname; uname -s; uname -r; uname -m; cat /etc/os-release 2>/dev/null", check=False)
    lines = (out.stdout or "").splitlines()
    rel = dict(re.findall(r'^(\w+)="?([^"\n]*)"?$', out.stdout or "", re.M))
    return InventoryReport(
        collector_version="ssh-basic",
        hostname=lines[0].split(".")[0] if lines else None,
        os_name=rel.get("NAME") or (lines[1] if len(lines) > 1 else None),
        os_version=rel.get("VERSION_ID") or (lines[2] if len(lines) > 2 else None),
        os_build=lines[2] if len(lines) > 2 else None,
        architecture=lines[3] if len(lines) > 3 else None,
    )


async def collect(host: str, cred: CredentialInput, lookup: KeyLookup, save: KeySaver) -> InventoryReport:
    agent = (AGENT_DIR / "itam_agent.py").read_text(encoding="utf-8")

    async def run() -> InventoryReport:
        async with await _connect(host, cred, lookup, save) as conn:
            probe = await conn.run("command -v python3", check=False)
            if probe.exit_status != 0:
                report = await _basic_report(conn)
                report.collector_version = "ssh-basic (no python3)"
                return report
            result = await conn.run(_sudo(cred, "python3 - --dry-run"), input=agent, check=False)
            if result.exit_status != 0:
                err = (result.stderr or "").strip().splitlines()[-1:] or ["exit %s" % result.exit_status]
                if "sudo" in err[0] and cred.params.get("sudo") == "yes":
                    raise CollectorError("access_denied", "sudo needs NOPASSWD for python3")
                raise CollectorError("collector_failed", err[0][:300])
            try:
                return InventoryReport.model_validate(json.loads(result.stdout))
            except ValueError as exc:
                raise CollectorError("collector_failed", f"unreadable output: {exc}"[:300])

    try:
        return await asyncio.wait_for(run(), TIMEOUT_S)
    except asyncio.TimeoutError:
        raise CollectorError("timeout", f"no result within {TIMEOUT_S}s")


async def test(host: str, cred: CredentialInput, lookup: KeyLookup, save: KeySaver) -> dict:
    async def run() -> dict:
        async with await _connect(host, cred, lookup, save) as conn:
            out = await conn.run("hostname; uname -sr", check=False)
            if out.exit_status != 0:
                raise CollectorError("collector_failed", (out.stderr or "").strip()[:200])
            lines = (out.stdout or "").splitlines()
            info = {"hostname": lines[0] if lines else None, "os": lines[1] if len(lines) > 1 else None}
            if (await conn.run("command -v python3", check=False)).exit_status != 0:
                info["note"] = "python3 not found: scans will collect basic details only"
            elif cred.params.get("sudo") == "yes":
                # Check exactly what a scan runs, so a sudoers rule limited to python3 passes.
                if (await conn.run(_sudo(cred, "python3 -c pass"), check=False)).exit_status != 0:
                    raise CollectorError("access_denied", "sudo -n python3 refused; NOPASSWD needed")
            return info
    try:
        return await asyncio.wait_for(run(), 60)
    except asyncio.TimeoutError:
        raise CollectorError("timeout", "no answer within 60s")
