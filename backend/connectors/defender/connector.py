import logging
from typing import List, Dict, Any
from datetime import datetime

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from backend.connectors.base import BaseConnector, RawDeviceRecord

logger = logging.getLogger(__name__)

_TOKEN_URL    = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
_MACHINES_URL = "https://api.securitycenter.microsoft.com/api/machines"
_SCOPE        = "https://api.securitycenter.microsoft.com/.default"
_PAGE_SIZE    = 1000


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


class DefenderConnector(BaseConnector):
    name = "defender"
    display_name = "Microsoft Defender for Endpoint"

    # ------------------------------------------------------------------ auth

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(httpx.TransportError),
        reraise=True,
    )
    async def _get_token(self, client: httpx.AsyncClient, config: Dict[str, Any]) -> str:
        url = _TOKEN_URL.format(tenant_id=config["tenant_id"])
        resp = await client.post(
            url,
            data={
                "grant_type":    "client_credentials",
                "client_id":     config["client_id"],
                "client_secret": config["client_secret"],
                "scope":         _SCOPE,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        token = data.get("access_token")
        if not token:
            raise ValueError(
                f"Defender token exchange failed: {data.get('error_description', data)}"
            )
        return token

    # ---------------------------------------------------------- pagination

    async def _fetch_all_machines(
        self, client: httpx.AsyncClient, headers: Dict[str, str]
    ) -> List[Dict[str, Any]]:
        machines: List[Dict[str, Any]] = []
        url: str | None = f"{_MACHINES_URL}?$top={_PAGE_SIZE}"

        while url:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            body = resp.json()
            machines.extend(body.get("value") or [])
            url = body.get("@odata.nextLink")

        logger.info(f"Defender: collected {len(machines)} machines")
        return machines

    # ------------------------------------------------------------- public

    async def test_connection(self, config: Dict[str, Any]) -> bool:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                token = await self._get_token(client, config)
                return bool(token)
        except Exception as exc:
            logger.warning(f"Defender connection test failed: {exc}")
            return False

    async def fetch_devices(self, config: Dict[str, Any]) -> List[RawDeviceRecord]:
        records: List[RawDeviceRecord] = []

        async with httpx.AsyncClient(timeout=60.0) as client:
            token = await self._get_token(client, config)
            headers = {"Authorization": f"Bearer {token}"}
            machines = await self._fetch_all_machines(client, headers)

        for m in machines:
            ips: List[str] = []
            if m.get("lastIpAddress"):
                ips.append(m["lastIpAddress"])
            ext = m.get("lastExternalIpAddress")
            if ext and ext not in ips:
                ips.append(ext)

            # computerDnsName is typically the FQDN from Defender
            fqdn     = m.get("computerDnsName")
            hostname = fqdn.split(".")[0] if fqdn else None

            records.append({
                "source_uid":    m.get("id", ""),
                "hostname":      hostname,
                "fqdn":          fqdn,
                "ip_addresses":  ips,
                "mac_addresses": [],
                "os_name":       m.get("osPlatform"),
                "os_version":    m.get("osVersion"),
                "domain":        None,
                "ou":            None,
                "last_seen":     _parse_dt(m.get("lastSeen")),
                "extra": {
                    "aad_device_id":      m.get("aadDeviceId"),
                    "agent_version":      m.get("agentVersion"),
                    "health_status":      m.get("healthStatus"),
                    "onboarding_status":  m.get("onboardingStatus"),
                    "risk_score":         m.get("riskScore"),
                    "exposure_level":     m.get("exposureLevel"),
                    "os_build":           m.get("osBuild"),
                    "device_value":       m.get("deviceValue"),
                    "rbac_group_name":    m.get("rbacGroupName"),
                },
            })

        logger.info(f"Defender: fetched {len(records)} device records")
        return records

    def get_config_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "required": ["tenant_id", "client_id", "client_secret"],
            "properties": {
                "tenant_id": {
                    "type": "string",
                    "title": "Azure Tenant ID",
                    "description": "Found in Azure AD → App registrations → Overview",
                },
                "client_id": {
                    "type": "string",
                    "title": "Azure App Client ID",
                },
                "client_secret": {
                    "type": "string",
                    "title": "Azure App Client Secret",
                    "format": "password",
                    "description": "Requires WindowsDefenderATP → Machine.Read.All permission",
                },
            },
        }
