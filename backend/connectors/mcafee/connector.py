"""
McAfee ePolicy Orchestrator (ePO) connector.

Uses the ePO Remote API (on-premise) which is accessible at:
  https://<host>:<port>/remote/<command>

Authentication: session cookie obtained via session.login.
All requests use HTTPS; certificate verification can be disabled for self-signed
certs by setting `verify_ssl: false` in the connector config.

Required config keys: api_url, username, password
Optional:            verify_ssl (default true)
"""
import logging
from typing import List, Dict, Any
from datetime import datetime, timezone

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from backend.connectors.base import BaseConnector, RawDeviceRecord

logger = logging.getLogger(__name__)

_PAGE_SIZE = 1000


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
    return None


class McAfeeConnector(BaseConnector):
    name = "mcafee"
    display_name = "McAfee / Trellix ePO"

    # ------------------------------------------------------------------ auth

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(httpx.TransportError),
        reraise=True,
    )
    async def _login(
        self, client: httpx.AsyncClient, config: Dict[str, Any]
    ) -> httpx.Cookies:
        base = config["api_url"].rstrip("/")
        resp = await client.post(
            f"{base}/remote/session.login",
            params={
                "username": config["username"],
                "password": config["password"],
                "output":   "json",
            },
        )
        resp.raise_for_status()
        body = resp.json()
        # ePO returns {"result": "OK"} or {"result": "error:..."}
        result = body.get("result", "")
        if isinstance(result, str) and result.startswith("error"):
            raise ValueError(f"ePO login failed: {result}")
        return client.cookies

    # ------------------------------------------------------- list systems

    async def _list_systems(
        self,
        client: httpx.AsyncClient,
        base: str,
        offset: int = 0,
    ) -> Dict[str, Any]:
        resp = await client.get(
            f"{base}/remote/core.listSystems",
            params={
                "output":        "json",
                "startIndex":    offset,
                "searchText":    "",
                "searchNameOnly": "false",
            },
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------- public

    async def test_connection(self, config: Dict[str, Any]) -> bool:
        verify = config.get("verify_ssl", True)
        try:
            async with httpx.AsyncClient(timeout=15.0, verify=verify) as client:
                await self._login(client, config)
                return True
        except Exception as exc:
            logger.warning(f"ePO connection test failed: {exc}")
            return False

    async def fetch_devices(self, config: Dict[str, Any]) -> List[RawDeviceRecord]:
        base   = config["api_url"].rstrip("/")
        verify = config.get("verify_ssl", True)
        records: List[RawDeviceRecord] = []

        async with httpx.AsyncClient(timeout=60.0, verify=verify) as client:
            await self._login(client, config)

            offset = 0
            while True:
                body = await self._list_systems(client, base, offset)

                # ePO wraps results differently depending on version;
                # try both common shapes.
                rows: List[Dict[str, Any]] = (
                    body.get("result") or
                    body.get("data", {}).get("rows", {}).get("row", []) or
                    []
                )
                if isinstance(rows, dict):
                    # Single-row result can be a dict instead of list
                    rows = [rows]

                if not rows:
                    break

                for row in rows:
                    # ePO uses dot-notation keys like "EPOComputerProperties.NodeName"
                    props = row if not any("." in k for k in row) else {
                        k.split(".")[-1]: v for k, v in row.items()
                    }

                    ip_raw = props.get("IPAddress") or props.get("IPHostName", "")
                    ips = [ip_raw] if ip_raw else []

                    mac_raw = props.get("EthernetAddress", "")
                    macs = [mac_raw.upper().replace("-", ":")] if mac_raw else []

                    records.append({
                        "source_uid":    props.get("AgentGUID") or props.get("NodeName", ""),
                        "hostname":      props.get("NodeName") or props.get("ComputerName"),
                        "fqdn":          props.get("NodeName"),
                        "ip_addresses":  ips,
                        "mac_addresses": macs,
                        "os_name":       props.get("OSType"),
                        "os_version":    props.get("OSVersion") or props.get("OsVersion"),
                        "domain":        props.get("DomainName"),
                        "ou":            props.get("ParentID"),
                        "last_seen":     _parse_dt(props.get("LastUpdate") or props.get("LastCommunication")),
                        "extra": {
                            "agent_version": props.get("AgentVersion"),
                            "dat_version":   props.get("DATVersion"),
                            "engine_version": props.get("EngineVersion"),
                            "managed_state": props.get("ManagedState"),
                            "tags":          props.get("Tags"),
                        },
                    })

                offset += len(rows)
                total = (
                    body.get("totalRowCount") or
                    body.get("data", {}).get("totalRowCount") or
                    0
                )
                if not total or offset >= int(total):
                    break

        logger.info(f"McAfee ePO: fetched {len(records)} device records")
        return records

    def get_config_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "required": ["api_url", "username", "password"],
            "properties": {
                "api_url": {
                    "type": "string",
                    "title": "ePO Server URL",
                    "description": "e.g. https://epo.corp.local:8443",
                },
                "username": {
                    "type": "string",
                    "title": "ePO Username",
                },
                "password": {
                    "type": "string",
                    "title": "ePO Password",
                    "format": "password",
                },
                "verify_ssl": {
                    "type": "boolean",
                    "title": "Verify SSL Certificate",
                    "default": True,
                    "description": "Disable for self-signed certificates (not recommended in production)",
                },
            },
        }
