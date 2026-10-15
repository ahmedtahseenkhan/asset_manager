"""
Credential types the scanner understands, and which fields each needs.

Fields are split three ways:
- `username` is stored in clear (shown in the UI, needed to identify the account)
- params are non-secret settings, shown in the UI
- secrets are encrypted at rest and never returned by the API
"""
from __future__ import annotations

from typing import Any, Dict, Tuple

# type -> (label, required secrets, optional secrets, params with allowed values or None for free text)
CREDENTIAL_TYPES: Dict[str, dict] = {
    "windows": {
        "label": "Windows (WinRM)",
        "username": "required",           # DOMAIN\\user or user@domain
        "secrets": {"password": True},
        # auto: HTTPS (5986) when open, else HTTP (5985) with NTLM/Kerberos message encryption
        "params": {"transport": ("auto", "https", "http"), "verify_tls": ("yes", "no")},
    },
    "ssh_password": {
        "label": "SSH (password)",
        "username": "required",
        "secrets": {"password": True},
        "params": {"port": None, "sudo": ("no", "yes")},   # sudo -n: needs NOPASSWD for python3
    },
    "ssh_key": {
        "label": "SSH (private key)",
        "username": "required",
        "secrets": {"private_key": True, "passphrase": False},
        "params": {"port": None, "sudo": ("no", "yes")},
    },
    "snmp_v2c": {
        "label": "SNMP v1/v2c",
        "username": "none",
        "secrets": {"community": True},
        "params": {"version": ("1", "2c")},
    },
    "snmp_v3": {
        "label": "SNMP v3",
        "username": "required",           # SNMPv3 security name
        "secrets": {"auth_password": False, "priv_password": False},
        "params": {
            "security_level": ("noAuthNoPriv", "authNoPriv", "authPriv"),
            "auth_protocol": ("MD5", "SHA", "SHA224", "SHA256", "SHA384", "SHA512"),
            "priv_protocol": ("DES", "3DES", "AES128", "AES192", "AES256"),
        },
    },
    "vmware": {
        "label": "VMware vCenter / ESXi",
        "username": "required",
        "secrets": {"password": True},
        "params": {"port": None},
    },
}


class CredentialError(ValueError):
    pass


def validate(cred_type: str, username: str | None, params: Dict[str, Any],
             secret: Dict[str, Any], *, partial_secret: bool = False) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return cleaned (params, secret). With partial_secret (updates), missing
    secrets are allowed — the stored values are kept."""
    spec = CREDENTIAL_TYPES.get(cred_type)
    if spec is None:
        raise CredentialError(f"Unknown credential type {cred_type!r}")
    if spec["username"] == "required" and not (username or "").strip():
        raise CredentialError("A username is required for this credential type")

    clean_params: Dict[str, Any] = {}
    for key, value in (params or {}).items():
        if key not in spec["params"]:
            raise CredentialError(f"Unknown setting {key!r} for {cred_type}")
        allowed = spec["params"][key]
        if allowed is not None and value not in allowed:
            raise CredentialError(f"{key} must be one of {', '.join(allowed)}")
        if key == "port":
            try:
                value = int(value)
            except (TypeError, ValueError):
                raise CredentialError("port must be a number")
            if not 1 <= value <= 65535:
                raise CredentialError("port must be between 1 and 65535")
        clean_params[key] = value

    clean_secret: Dict[str, Any] = {}
    for key, value in (secret or {}).items():
        if key not in spec["secrets"]:
            raise CredentialError(f"Unknown secret {key!r} for {cred_type}")
        if value not in (None, ""):
            clean_secret[key] = value
    if not partial_secret:
        missing = [k for k, required in spec["secrets"].items() if required and k not in clean_secret]
        if missing:
            raise CredentialError(f"Missing: {', '.join(missing)}")

    if cred_type == "snmp_v3":
        level = clean_params.get("security_level", "authPriv")
        clean_params["security_level"] = level
        if level in ("authNoPriv", "authPriv") and not partial_secret and "auth_password" not in clean_secret:
            raise CredentialError("auth_password is required for this security level")
        if level == "authPriv" and not partial_secret and "priv_password" not in clean_secret:
            raise CredentialError("priv_password is required for authPriv")
    return clean_params, clean_secret


def public_view(cred) -> Dict[str, Any]:
    """API representation: everything except secret values."""
    spec = CREDENTIAL_TYPES.get(cred.cred_type, {})
    stored = cred.secret or {}
    return {
        "id": cred.id,
        "name": cred.name,
        "cred_type": cred.cred_type,
        "type_label": spec.get("label", cred.cred_type),
        "username": cred.username,
        "params": cred.params or {},
        "secrets_set": sorted(k for k in spec.get("secrets", {}) if stored.get(k)),
        "description": cred.description,
        "created_at": cred.created_at,
        "updated_at": cred.updated_at,
        "last_used_at": cred.last_used_at,
        "last_success_at": cred.last_success_at,
    }
