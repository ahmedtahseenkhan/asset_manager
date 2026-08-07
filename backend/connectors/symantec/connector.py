"""
Symantec Endpoint Protection Manager (SEPM) connector.

Uses the SEPM REST API v1:
  https://<host>:<port>/sepm/api/v1/

Two auth modes are supported:
  1. Bearer token (pre-generated) — supply `access_token` in config.
  2. Username / password — supply `username` and `password`; the connector
     will call /identity/authenticate to get a token automatically.

Required config keys (one of the two sets):
  - api_url + access_token
  - api_url + username + password
Optional:
  - verify_ssl (default true)
"""
import logging
from typing import List, Dict, Any
from datetime import datetime, timezone

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from backend.connectors.base import BaseConnector, RawDeviceRecord

logger = logging.getLogger(__name__)

_PAGE_SIZE = 100


def _parse_dt(value: str | None) -> datetime | None:
    """SEPM timestamps are epoch-milliseconds (int) or ISO strings."""
    if value is None:
        return None
    try:
        ms = int(value)
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


class SymantecConnector(BaseConnector):
    name = "symantec"
    display_name = "Symantec / Broadcom SEP Manager"

    # ------------------------------------------------------------------ auth

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(httpx.TransportError),
        reraise=True,
    )
    async def _get_token(
        self, client: httpx.AsyncClient, config: Dict[str, Any]
    ) -> str:
        # Prefer a pre-supplied token
        if config.get("access_token"):
            return config["access_token"]

        base = config["api_url"].rstrip("/")
        resp = await client.post(
            f"{base}/sepm/api/v1/identity/authenticate",
            json={
                "username": config["username"],
                "password": config["password"],
                "domain":   config.get("domain", ""),
            },
        )
        resp.raise_for_status()
        body = resp.json()
        token = body.get("token")
        if not token:
            raise ValueError(f"SEPM authentication failed: {body}")
        return token

    # ------------------------------------------------------------- public

    async def test_connection(self, config: Dict[str, Any]) -> bool:
        verify = config.get("verify_ssl", True)
        try:
            async with httpx.AsyncClient(timeout=15.0, verify=verify) as client:
                token = await self._get_token(client, config)
                return bool(token)
        except Exception as exc:
            logger.warning(f"SEPM connection test failed: {exc}")
            return False

    async def fetch_devices(self, config: Dict[str, Any]) -> List[RawDeviceRecord]:
        base   = config["api_url"].rstrip("/")
        verify = config.get("verify_ssl", True)
        records: List[RawDeviceRecord] = []

        async with httpx.AsyncClient(timeout=60.0, verify=verify) as client:
            token   = await self._get_token(client, config)
            headers = {"Authorization": f"Bearer {token}"}

            page_index = 1
            while True:
                resp = await client.get(
                    f"{base}/sepm/api/v1/computers",
                    headers=headers,
                    params={
                        "pageIndex": page_index,
                        "pageSize":  _PAGE_SIZE,
                    },
                )
                resp.raise_for_status()
                body = resp.json()

                computers: List[Dict[str, Any]] = body.get("content") or []
                if not computers:
                    break

                for c in computers:
                    ips: List[str] = []
                    for iface in c.get("ipAddresses") or []:
                        if iface and iface not in ips:
                            ips.append(iface)

                    macs: List[str] = []
                    for mac in c.get("macAddresses") or []:
                        if mac:
                            macs.append(mac.upper().replace("-", ":"))

                    os_raw = c.get("operatingSystem") or {}
                    os_name    = os_raw.get("name") if isinstance(os_raw, dict) else str(os_raw)
                    os_version = os_raw.get("version") if isinstance(os_raw, dict) else None

                    records.append({
                        "source_uid":    c.get("uniqueId", ""),
                        "hostname":      c.get("computerName"),
                        "fqdn":          c.get("computerName"),
                        "ip_addresses":  ips,
                        "mac_addresses": macs,
                        "os_name":       os_name,
                        "os_version":    os_version,
                        "domain":        c.get("domainOrWorkgroup"),
                        "ou":            None,
                        "last_seen":     _parse_dt(c.get("lastUpdateTime")),
                        "extra": {
                            "agent_version":      c.get("agentVersion"),
                            "av_engine_version":  c.get("avEngineOnDemandVersion"),
                            "av_def_date":        c.get("avDefDate"),
                            "group_name":         c.get("group", {}).get("name") if isinstance(c.get("group"), dict) else None,
                            "infection_status":   c.get("infectionStatus"),
                            "online":             c.get("online"),
                        },
                    })

                total_pages = body.get("totalPages", 1)
                if page_index >= total_pages:
                    break
                page_index += 1

        logger.info(f"Symantec SEP: fetched {len(records)} device records")
        return records

    def get_config_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "required": ["api_url"],
            "properties": {
                "api_url": {
                    "type": "string",
                    "title": "SEPM Server URL",
                    "description": "e.g. https://sepm.corp.local:8446",
                },
                "access_token": {
                    "type": "string",
                    "title": "Pre-generated Access Token (optional)",
                    "format": "password",
                    "description": "If provided, username/password are ignored",
                },
                "username": {
                    "type": "string",
                    "title": "SEPM Username",
                },
                "password": {
                    "type": "string",
                    "title": "SEPM Password",
                    "format": "password",
                },
                "domain": {
                    "type": "string",
                    "title": "SEPM Domain (optional)",
                    "description": "Leave blank for the default domain",
                },
                "verify_ssl": {
                    "type": "boolean",
                    "title": "Verify SSL Certificate",
                    "default": True,
                },
            },
        }
