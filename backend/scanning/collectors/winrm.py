"""
Windows inventory over WinRM (PowerShell Remoting).

Runs the same PowerShell collector the Windows agent uses (agent/itam_agent.ps1)
in a remote session with -DryRun and parses its JSON output, so a scanned host
and an agent host produce identical inventory.

Transport: HTTPS (5986) when available; otherwise HTTP (5985), where pypsrp
encrypts the message payload with NTLM/Kerberos ("encryption=auto"), so
credentials and data are never sent in clear text.
"""
from __future__ import annotations

import asyncio
import json
import socket

import requests
from pypsrp.client import Client
from pypsrp.exceptions import AuthenticationError, WinRMTransportError, WSManFaultError

from backend.schemas.inventory import InventoryReport
from backend.scanning.collectors import AGENT_DIR, CollectorError, CredentialInput

HTTP_PORT, HTTPS_PORT = 5985, 5986
TIMEOUT_S = 180          # software enumeration on a busy host can take a while

# Lightweight script for "test credential": proves sign-in and admin rights.
TEST_SCRIPT = (
    "$os = Get-CimInstance Win32_OperatingSystem; "
    "[pscustomobject]@{ hostname = $env:COMPUTERNAME; os = $os.Caption; "
    "admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent())"
    ".IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) } | ConvertTo-Json -Compress"
)


def _agent_script() -> str:
    """The agent script wrapped so its param block binds -DryRun remotely."""
    body = (AGENT_DIR / "itam_agent.ps1").read_text(encoding="ascii")
    if "\n'@" in body:
        raise RuntimeError("agent script cannot be embedded in a here-string")
    return f"$agent = [scriptblock]::Create(@'\n{body}\n'@)\n& $agent -DryRun\n"


def _port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _choose_transport(host: str, cred: CredentialInput) -> tuple[int, bool]:
    mode = cred.params.get("transport", "auto")
    if mode == "https":
        return HTTPS_PORT, True
    if mode == "http":
        return HTTP_PORT, False
    if _port_open(host, HTTPS_PORT):
        return HTTPS_PORT, True
    if _port_open(host, HTTP_PORT):
        return HTTP_PORT, False
    raise CollectorError("unreachable", f"WinRM ports {HTTP_PORT}/{HTTPS_PORT} closed")


def _execute(host: str, cred: CredentialInput, script: str) -> str:
    port, ssl = _choose_transport(host, cred)
    client = Client(
        host, port=port, ssl=ssl, username=cred.username, password=cred.secret.get("password"),
        auth="negotiate", encryption="auto",
        cert_validation=cred.params.get("verify_tls", "yes") == "yes",
        connection_timeout=10, operation_timeout=60, read_timeout=90,
    )
    try:
        output, streams, had_errors = client.execute_ps(script)
    except AuthenticationError as exc:
        raise CollectorError("auth_failed", str(exc)[:200])
    except requests.exceptions.SSLError as exc:
        raise CollectorError("tls_untrusted", str(exc)[:200])
    except (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout):
        raise CollectorError("timeout", f"port {port}")
    except requests.exceptions.ConnectionError:
        raise CollectorError("unreachable", f"port {port}")
    except WinRMTransportError as exc:
        if getattr(exc, "code", None) == 401:
            raise CollectorError("auth_failed", f"HTTP 401 on port {port}")
        if getattr(exc, "code", None) == 403:
            raise CollectorError("access_denied", f"HTTP 403 on port {port}")
        raise CollectorError("collector_failed", str(exc)[:200])
    except WSManFaultError as exc:
        text = str(exc)
        if "Access is denied" in text or getattr(exc, "code", None) == 5:
            raise CollectorError("access_denied", "WinRM refused the session")
        raise CollectorError("collector_failed", text[:200])
    if not output.strip():
        errors = "; ".join(str(e) for e in streams.error[:3]) if had_errors else "no output"
        raise CollectorError("collector_failed", errors[:300])
    return output


def _parse_json(output: str) -> dict:
    start = output.find("{")
    try:
        return json.loads(output[start:]) if start >= 0 else {}
    except ValueError as exc:
        raise CollectorError("collector_failed", f"unreadable output: {exc}")


async def collect(host: str, cred: CredentialInput) -> InventoryReport:
    if cred.cred_type != "windows":
        raise CollectorError("not_supported", cred.cred_type)
    script = _agent_script()
    try:
        output = await asyncio.wait_for(asyncio.to_thread(_execute, host, cred, script), TIMEOUT_S)
    except asyncio.TimeoutError:
        raise CollectorError("timeout", f"no result within {TIMEOUT_S}s")
    data = _parse_json(output)
    if not data.get("schema_version"):
        raise CollectorError("collector_failed", "output is not an inventory report")
    return InventoryReport.model_validate(data)


async def test(host: str, cred: CredentialInput) -> dict:
    """Sign in and run a tiny query; nothing is stored."""
    try:
        output = await asyncio.wait_for(asyncio.to_thread(_execute, host, cred, TEST_SCRIPT), 60)
    except asyncio.TimeoutError:
        raise CollectorError("timeout", "no answer within 60s")
    data = _parse_json(output)
    if data.get("admin") is False:
        raise CollectorError("access_denied", f"signed in to {data.get('hostname')} without admin rights")
    return {"hostname": data.get("hostname"), "os": data.get("os")}
