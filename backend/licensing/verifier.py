"""
Offline license verification.

A license file is a JSON envelope:
    {"format": 1, "payload": "<base64 JSON claims>", "signature": "<base64 Ed25519 sig>"}

The signature is verified against the vendor public key baked into this package
(public_key.pem). No network access is ever performed — safe for air-gapped sites.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

_PUBLIC_KEY_PATH = Path(__file__).resolve().parent / "public_key.pem"

REQUIRED_CLAIMS = {
    "license_id", "customer", "issued_at", "expires_at",
    "grace_days", "max_assets", "max_users", "modules",
}


class LicenseError(Exception):
    """Raised when a license file cannot be parsed or its signature is invalid."""


class LicenseStatus(str, Enum):
    VALID = "valid"          # in force
    GRACE = "grace"          # expired but within grace window; warn, keep working
    EXPIRED = "expired"      # past grace; writes blocked
    INVALID = "invalid"      # bad signature / malformed / clock tamper
    MISSING = "missing"      # no license file installed


@dataclass
class LicenseInfo:
    status: LicenseStatus
    reason: str = ""
    claims: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_operational(self) -> bool:
        """Whether write operations are permitted."""
        return self.status in (LicenseStatus.VALID, LicenseStatus.GRACE)

    def module_enabled(self, module: str) -> bool:
        return self.is_operational and module in self.claims.get("modules", [])


def _load_public_key() -> Ed25519PublicKey:
    key = serialization.load_pem_public_key(_PUBLIC_KEY_PATH.read_bytes())
    if not isinstance(key, Ed25519PublicKey):
        raise LicenseError("Embedded public key is not an Ed25519 key")
    return key


def verify_license_bytes(data: bytes) -> Dict[str, Any]:
    """Parse + cryptographically verify a license file. Returns claims or raises LicenseError."""
    try:
        envelope = json.loads(data)
        if envelope.get("format") != 1:
            raise LicenseError(f"Unsupported license format: {envelope.get('format')!r}")
        payload_bytes = base64.b64decode(envelope["payload"], validate=True)
        signature = base64.b64decode(envelope["signature"], validate=True)
    except LicenseError:
        raise
    except Exception as exc:
        raise LicenseError(f"Malformed license file: {exc}") from exc

    try:
        _load_public_key().verify(signature, payload_bytes)
    except InvalidSignature:
        raise LicenseError("License signature verification failed") from None

    try:
        claims = json.loads(payload_bytes)
    except Exception as exc:
        raise LicenseError(f"License payload is not valid JSON: {exc}") from exc

    missing = REQUIRED_CLAIMS - claims.keys()
    if missing:
        raise LicenseError(f"License is missing required claims: {sorted(missing)}")
    return claims


def evaluate(claims: Dict[str, Any], today: date | None = None) -> LicenseInfo:
    """Turn verified claims into a status based on today's date."""
    today = today or date.today()
    try:
        expires = date.fromisoformat(claims["expires_at"])
        issued = date.fromisoformat(claims["issued_at"])
        grace_days = int(claims["grace_days"])
    except (ValueError, TypeError) as exc:
        return LicenseInfo(LicenseStatus.INVALID, f"Bad date/grace claims: {exc}", claims)

    if today < issued:
        # Clock rolled back before issuance — treat as tampering.
        return LicenseInfo(
            LicenseStatus.INVALID,
            f"System date {today} is before license issue date {issued}", claims,
        )
    if today <= expires:
        return LicenseInfo(LicenseStatus.VALID, "", claims)
    if today <= expires + timedelta(days=grace_days):
        remaining = (expires + timedelta(days=grace_days) - today).days
        return LicenseInfo(
            LicenseStatus.GRACE,
            f"License expired on {expires}; {remaining} day(s) of grace remaining", claims,
        )
    return LicenseInfo(LicenseStatus.EXPIRED, f"License expired on {expires} (grace period over)", claims)


def verify_and_evaluate_file(path: Path) -> LicenseInfo:
    if not path.exists():
        return LicenseInfo(LicenseStatus.MISSING, f"No license file at {path}")
    try:
        claims = verify_license_bytes(path.read_bytes())
    except LicenseError as exc:
        return LicenseInfo(LicenseStatus.INVALID, str(exc))
    return evaluate(claims)
