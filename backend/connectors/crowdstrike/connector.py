import logging
from typing import List, Dict, Any
from datetime import datetime, timezone

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from backend.connectors.base import BaseConnector, RawDeviceRecord

logger = logging.getLogger(__name__)

_BATCH_SIZE = 100   # CrowdStrike max IDs per entity fetch request
_PAGE_SIZE  = 5000  # max device IDs per query page


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _normalise_mac(mac: str | None) -> str | None:
    if not mac:
        return None
    return mac.upper().replace("-", ":").replace(".", ":")


class CrowdStrikeConnector(BaseConnector):
    name = "crowdstrike"
    display_name = "CrowdStrike Falcon"

    # ------------------------------------------------------------------ auth

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(httpx.TransportError),
        reraise=True,
    )
    async def _get_token(self, client: httpx.AsyncClient, config: Dict[str, Any]) -> str:
        base = config["base_url"].rstrip("/")
        resp = await client.post(
            f"{base}/oauth2/token",
            data={
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        data = resp.json()
        token = data.get("access_token")
        if not token:
            errors = data.get("errors", [])
            raise ValueError(f"CrowdStrike token exchange failed: {errors}")
        return token

    # ---------------------------------------------------------- pagination

    async def _get_all_device_ids(
        self, client: httpx.AsyncClient, base: str, headers: Dict[str, str]
    ) -> List[str]:
        device_ids: List[str] = []
        offset = 0

        while True:
            resp = await client.get(
                f"{base}/devices/queries/devices/v1",
                headers=headers,
                params={"limit": _PAGE_SIZE, "offset": offset},
            )
            resp.raise_for_status()
            body = resp.json()

            batch = body.get("resources") or []
            device_ids.extend(batch)

            pagination = body.get("meta", {}).get("pagination", {})
            total = pagination.get("total", 0)
            offset += len(batch)

            if not batch or offset >= total:
                break

        logger.info(f"CrowdStrike: collected {len(device_ids)} device IDs")
        return device_ids

    async def _get_device_details(
        self,
        client: httpx.AsyncClient,
        base: str,
        headers: Dict[str, str],
        device_ids: List[str],
    ) -> List[Dict[str, Any]]:
        results = []
        for i in range(0, len(device_ids), _BATCH_SIZE):
            batch = device_ids[i : i + _BATCH_SIZE]
            resp = await client.post(
                f"{base}/devices/entities/devices/v2",
                headers=headers,
                json={"ids": batch},
            )
            resp.raise_for_status()
            results.extend(resp.json().get("resources") or [])
        return results

    # ------------------------------------------------------------- public

    async def test_connection(self, config: Dict[str, Any]) -> bool:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                token = await self._get_token(client, config)
                return bool(token)
        except Exception as exc:
            logger.warning(f"CrowdStrike connection test failed: {exc}")
            return False

    async def fetch_devices(self, config: Dict[str, Any]) -> List[RawDeviceRecord]:
        base = config["base_url"].rstrip("/")
        records: List[RawDeviceRecord] = []

        async with httpx.AsyncClient(timeout=60.0) as client:
            token = await self._get_token(client, config)
            headers = {"Authorization": f"Bearer {token}"}

            device_ids = await self._get_all_device_ids(client, base, headers)
            if not device_ids:
                logger.info("CrowdStrike: no devices found")
                return []

            raw_devices = await self._get_device_details(client, base, headers, device_ids)

        for dev in raw_devices:
            ips: List[str] = []
            if dev.get("local_ip"):
                ips.append(dev["local_ip"])
            ext = dev.get("external_ip")
            if ext and ext not in ips:
                ips.append(ext)

            mac = _normalise_mac(dev.get("mac_address"))
            macs = [mac] if mac else []

            records.append({
                "source_uid":    dev.get("device_id", ""),
                "hostname":      dev.get("hostname"),
                "fqdn":          None,
                "ip_addresses":  ips,
                "mac_addresses": macs,
                "os_name":       dev.get("platform_name"),
                "os_version":    dev.get("os_version"),
                "domain":        dev.get("machine_domain"),
                "ou":            dev.get("ou"),
                "last_seen":     _parse_dt(dev.get("last_seen")),
                "extra": {
                    "aid":                  dev.get("device_id"),
                    "agent_version":        dev.get("agent_version"),
                    "status":               dev.get("status"),
                    "product_type_desc":    dev.get("product_type_desc"),
                    "groups":               dev.get("groups", []),
                    "tags":                 dev.get("tags", []),
                    "kernel_version":       dev.get("kernel_version"),
                    "bios_version":         dev.get("bios_version"),
                    "system_manufacturer":  dev.get("system_manufacturer"),
                    "system_product_name":  dev.get("system_product_name"),
                    "reduced_functionality_mode": dev.get("reduced_functionality_mode"),
                },
            })

        logger.info(f"CrowdStrike: fetched {len(records)} device records")
        return records

    def get_config_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "required": ["base_url", "client_id", "client_secret"],
            "properties": {
                "base_url": {
                    "type": "string",
                    "title": "API Base URL",
                    "description": "e.g. https://api.crowdstrike.com or https://api.us-2.crowdstrike.com",
                },
                "client_id": {
                    "type": "string",
                    "title": "OAuth2 Client ID",
                },
                "client_secret": {
                    "type": "string",
                    "title": "OAuth2 Client Secret",
                    "format": "password",
                },
            },
        }
