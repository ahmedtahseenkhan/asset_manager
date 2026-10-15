"""
Credentialed collectors: read inventory from a host with an administrator-
supplied credential and return an InventoryReport for InventoryService.

Every failure is raised as CollectorError with a stable code, so the scan
history can say what went wrong and how to fix it.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[3] / "agent"

# code -> (summary, how to fix). Shown on failed hosts in the scan history.
ERRORS = {
    "unreachable": (
        "Could not connect",
        "The port is closed or filtered. Check that the service is running on the host and that "
        "firewalls allow this server to reach it.",
    ),
    "timeout": (
        "Timed out",
        "The host stopped responding. It may be overloaded, asleep, or a firewall may be dropping traffic.",
    ),
    "auth_failed": (
        "Sign-in rejected",
        "Check the username and password (Windows: DOMAIN\\user or user@domain), that the account is "
        "enabled, and that it may sign in remotely.",
    ),
    "access_denied": (
        "Signed in, but not allowed",
        "The account needs administrator rights on the host. Windows: a member of the local "
        "Administrators group, allowed to use WinRM. Linux/macOS with 'sudo' on the credential: a "
        "sudoers rule letting it run python3 without a password (NOPASSWD).",
    ),
    "tls_untrusted": (
        "Certificate not trusted",
        "The host's HTTPS certificate isn't trusted by this server. Install the issuing CA on the "
        "server, or set the credential's 'Verify TLS' to 'no' for self-signed certificates.",
    ),
    "host_key_changed": (
        "SSH host key changed",
        "The host presented a different key than the one trusted earlier, so no credentials were sent. "
        "If the host was rebuilt, clear its stored key in Scanning and scan again; otherwise investigate.",
    ),
    "no_python": (
        "Python 3 not found",
        "Full inventory over SSH needs python3 on the host. Basic details were collected instead.",
    ),
    "snmp_no_response": (
        "No SNMP response",
        "Wrong community string or SNMPv3 credentials, SNMP disabled on the device, or its access list "
        "doesn't include this server. Wrong credentials look the same as no SNMP at all.",
    ),
    "collector_failed": (
        "Inventory script failed",
        "The host accepted the credential but the inventory script failed. See the details.",
    ),
    "not_supported": (
        "Not supported",
        "This credential type can't be used for this kind of scan yet.",
    ),
}

AUTH_CODES = {"auth_failed", "access_denied"}   # trying another credential may help
STOP_CODES = {"unreachable", "timeout", "tls_untrusted", "host_key_changed"}  # another credential won't


class CollectorError(Exception):
    def __init__(self, code: str, detail: str = ""):
        self.code = code if code in ERRORS else "collector_failed"
        self.detail = detail
        summary, _ = ERRORS[self.code]
        super().__init__(f"{summary}: {detail}" if detail else summary)

    @property
    def message(self) -> str:
        summary, hint = ERRORS[self.code]
        detail = f" ({self.detail})" if self.detail else ""
        return f"{summary}{detail}. {hint}"


@dataclass
class CredentialInput:
    """What a collector needs from a stored ScanCredential (decrypted)."""
    id: int
    cred_type: str
    username: str | None
    params: dict
    secret: dict

    @classmethod
    def from_model(cls, cred) -> "CredentialInput":
        return cls(id=cred.id, cred_type=cred.cred_type, username=cred.username,
                   params=dict(cred.params or {}), secret=dict(cred.secret or {}))
