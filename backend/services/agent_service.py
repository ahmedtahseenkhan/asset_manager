"""
Agent inventory ingestion. An enrolled agent POSTs a full inventory report;
we feed the device through the correlator (source_name='agent'), store the
installed-software list, and push rich fields onto a linked asset if present.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.connectors.base import RawDeviceRecord
from backend.correlator.correlator import Correlator
from backend.models.agent import AgentToken
from backend.models.asset import Asset
from backend.models.device import Device
from backend.models.software import InstalledSoftware
from backend.services.software_normalizer import normalize_software

AGENT_SOURCE = "agent"


class AgentService:
    @staticmethod
    async def validate_token(db: AsyncSession, token: str) -> Optional[AgentToken]:
        if not token:
            return None
        row = (await db.execute(
            select(AgentToken).where(AgentToken.token == token, AgentToken.active == True)
        )).scalars().first()
        return row

    @staticmethod
    async def ingest(db: AsyncSession, token_row: AgentToken, report: Dict[str, Any]) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)

        # Stable identity: prefer serial, else machine_id, else hostname.
        serial = report.get("serial_number")
        uid = serial or report.get("machine_id") or report.get("hostname") or "unknown"

        software: List[Dict[str, Any]] = report.get("software") or []
        raw: RawDeviceRecord = {
            "source_uid": f"agent-{uid}",
            "hostname": report.get("hostname"),
            "fqdn": report.get("fqdn"),
            "ip_addresses": report.get("ip_addresses") or [],
            "mac_addresses": report.get("mac_addresses") or [],
            "os_name": report.get("os_name"),
            "os_version": report.get("os_version"),
            "domain": report.get("domain"),
            "ou": None,
            "last_seen": now,
            "extra": {
                "method": "agent",
                "serial_number": serial,
                "manufacturer": report.get("manufacturer"),
                "model": report.get("model"),
                "cpu": report.get("cpu"),
                "ram_gb": report.get("ram_gb"),
                "disk_gb": report.get("disk_gb"),
                "logged_in_user": report.get("logged_in_user"),
                "software_count": len(software),
            },
        }

        await Correlator.process_batch(db, AGENT_SOURCE, [raw])

        # Resolve the device we just wrote (by our agent source_uid).
        device = (await db.execute(
            select(Device)
            .join(Device.sources)
            .where(Device.sources.any(source_uid=raw["source_uid"]))
        )).scalars().first()
        if device is None:
            device = (await db.execute(
                select(Device).where(Device.hostname == report.get("hostname"))
            )).scalars().first()

        sw_written = 0
        if device is not None:
            # Replace this device's software list (full snapshot each report).
            await db.execute(delete(InstalledSoftware).where(InstalledSoftware.device_id == device.id))
            seen = set()
            for item in software:
                name = (item.get("name") or "").strip()
                if not name:
                    continue
                version = (item.get("version") or "").strip() or None
                key = (name, version)
                if key in seen:
                    continue
                seen.add(key)
                db.add(InstalledSoftware(
                    device_id=device.id,
                    name=name[:500],
                    normalized_name=normalize_software(name)[:500],
                    version=version[:128] if version else None,
                    publisher=(item.get("publisher") or None),
                ))
                sw_written += 1

            # Push rich fields onto a linked asset (agent is authoritative for these).
            asset = (await db.execute(
                select(Asset).where(Asset.device_id == device.id)
            )).scalars().first()
            if asset is not None:
                ex = raw["extra"]
                if serial:
                    asset.serial_number = serial
                if ex.get("model"):
                    asset.model = ex["model"]
                if ex.get("manufacturer") and not asset.vendor:
                    asset.vendor = ex["manufacturer"]
                if report.get("os_name"):
                    asset.os_name = report["os_name"]
                if report.get("os_version"):
                    asset.os_version = report["os_version"]
                if raw["ip_addresses"]:
                    asset.ip_address = raw["ip_addresses"][0]
                if raw["mac_addresses"]:
                    asset.mac_address = raw["mac_addresses"][0]

        token_row.last_used_at = now
        token_row.reports_count = (token_row.reports_count or 0) + 1
        await db.commit()

        return {
            "device_id": device.id if device else None,
            "hostname": report.get("hostname"),
            "software_recorded": sw_written,
        }
