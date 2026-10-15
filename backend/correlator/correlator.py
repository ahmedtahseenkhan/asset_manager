import logging
from typing import List, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import cast, String
from datetime import date, datetime, timezone

from backend.connectors.base import RawDeviceRecord
from backend.normalizer.normalizer import Normalizer
from backend.models.device import Device
from backend.models.device_source import DeviceSource

logger = logging.getLogger(__name__)

# Source authority: which connector "wins" for each field.
# Lower index = higher authority. Last-writer-wins when source is not listed.
# Sources that read the machine itself (agent, credentialed scans) know its OS
# exactly; AD stays authoritative for directory identity (name, domain, OU).
_HOST_SOURCES = ["agent", "winrm", "wmi", "ssh"]
_EDR_SOURCES = ["crowdstrike", "defender", "mcafee", "symantec"]
_FIELD_AUTHORITY: dict[str, list[str]] = {
    "hostname":   ["ad", *_HOST_SOURCES, *_EDR_SOURCES, "snmp"],
    "fqdn":       ["ad", *_HOST_SOURCES, *_EDR_SOURCES, "snmp"],
    "domain":     ["ad", *_HOST_SOURCES],
    "ou":         ["ad"],
    "os_name":    [*_HOST_SOURCES, *_EDR_SOURCES, "ad", "snmp"],
    "os_version": [*_HOST_SOURCES, *_EDR_SOURCES, "ad", "snmp"],
}

# Placeholder values firmware ships when the OEM never set a real one. Matching
# on these would merge unrelated machines.
_JUNK_SERIALS = {
    "", "0", "none", "null", "n/a", "na", "unknown", "invalid", "default string",
    "to be filled by o.e.m.", "system serial number", "chassis serial number",
    "not specified", "not applicable", "123456789", "0123456789", "serial",
}
_JUNK_UUIDS = {
    "00000000-0000-0000-0000-000000000000",
    "ffffffff-ffff-ffff-ffff-ffffffffffff",
    "03000200-0400-0500-0006-000700080009",
}


def hardware_identity(raw: RawDeviceRecord) -> Tuple[str | None, str | None]:
    """(serial_number, hardware_uuid) from a raw record, or None for placeholders."""
    extra = raw.get("extra") or {}
    serial = (raw.get("serial_number") or extra.get("serial_number") or "").strip()
    hw_uuid = (raw.get("hardware_uuid") or extra.get("hardware_uuid") or "").strip().lower()
    if serial.lower() in _JUNK_SERIALS or len(set(serial)) == 1:  # e.g. "00000000"
        serial = ""
    if hw_uuid in _JUNK_UUIDS:
        hw_uuid = ""
    return serial or None, hw_uuid or None


def _source_priority(source_name: str, field: str) -> int:
    """Lower return value = higher priority. Sources not in list get lowest priority."""
    authority = _FIELD_AUTHORITY.get(field, [])
    try:
        return authority.index(source_name)
    except ValueError:
        return len(authority)


class Correlator:
    @staticmethod
    def _json_safe(value):
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, dict):
            return {k: Correlator._json_safe(v) for k, v in value.items()}
        if isinstance(value, list):
            return [Correlator._json_safe(v) for v in value]
        return value

    # Sources whose identity is the IP/source_uid (one record per address), not the
    # host itself. These must never be merged by MAC: on proxy-ARP / routed networks
    # every address answers with the same gateway MAC, which would collapse a whole
    # subnet into one device.
    _IP_IDENTITY_SOURCES = {"network_scan"}

    @staticmethod
    async def _find_existing_device(
        db: AsyncSession, source_name: str, source_uid: str | None,
        fqdn: str, hostname: str, macs: List[str],
        serial: str | None = None, hw_uuid: str | None = None,
    ) -> Device | None:
        """
        Finds an existing device to merge into, in priority order:
        0. Same connector already tracks this exact source_uid  — definitive for re-syncs
        0b. Hardware UUID, then serial number — same physical/virtual machine even
            when it was renamed or is seen by a different source
        1. FQDN exact match  — most specific; avoids hostname collisions across domains
        2. Hostname match    — fallback when FQDN is unavailable (e.g. CrowdStrike)
        3. MAC address match — last resort for nameless devices (skipped for IP-identity
                               sources like network_scan)
        """
        # 0. A DeviceSource with this (source_name, source_uid) is the same logical
        #    entity from this connector — return its device (correct re-sync updates).
        if source_uid:
            result = await db.execute(
                select(Device)
                .join(DeviceSource, DeviceSource.device_id == Device.id)
                .where(DeviceSource.source_name == source_name,
                       DeviceSource.source_uid == source_uid)
            )
            dev = result.scalars().first()
            if dev:
                return dev

        if hw_uuid:
            dev = (await db.execute(select(Device).where(Device.hardware_uuid == hw_uuid))).scalars().first()
            if dev:
                return dev
        if serial:
            dev = (await db.execute(select(Device).where(Device.serial_number == serial))).scalars().first()
            if dev:
                return dev

        if fqdn:
            result = await db.execute(select(Device).where(Device.fqdn == fqdn))
            dev = result.scalars().first()
            if dev:
                return dev

        if hostname:
            result = await db.execute(select(Device).where(Device.hostname == hostname))
            dev = result.scalars().first()
            if dev:
                return dev

        # MAC-address fallback — only when the record carries NO name-based identity,
        # and never for IP-identity sources (proxy-ARP would mass-merge a subnet).
        if not fqdn and not hostname and source_name not in Correlator._IP_IDENTITY_SOURCES:
            _SKIP_MACS = {"00:00:00:00:00:00", "FF:FF:FF:FF:FF:FF"}
            for mac in macs:
                if not mac or mac.upper() in _SKIP_MACS:
                    continue
                normalised = mac.upper().replace("-", ":").replace(".", ":")
                result = await db.execute(
                    select(Device).where(
                        cast(Device.mac_addresses, String).contains(f'"{normalised}"')
                    )
                )
                dev = result.scalars().first()
                if dev:
                    return dev

        return None

    @staticmethod
    def _should_update_field(existing_sources: List[DeviceSource], new_source: str, field: str) -> bool:
        """
        Returns True if new_source has equal or higher authority than any existing source
        that already provides this field.
        """
        new_priority = _source_priority(new_source, field)
        for src in existing_sources:
            if src.source_name != new_source:
                existing_priority = _source_priority(src.source_name, field)
                if existing_priority < new_priority:
                    return False
        return True

    @staticmethod
    async def process_batch(db: AsyncSession, source_name: str, raw_devices: List[RawDeviceRecord]) -> Tuple[int, int]:
        """Processes a batch of raw records. Returns (created_cnt, updated_cnt)."""
        created = 0
        updated = 0
        for raw in raw_devices:
            _, is_new = await Correlator.upsert_device(db, source_name, raw)
            if is_new:
                created += 1
            else:
                updated += 1
        await db.commit()
        return created, updated

    @staticmethod
    async def upsert_device(db: AsyncSession, source_name: str, raw: RawDeviceRecord) -> Tuple[Device, bool]:
        """Merge one raw record into the device table. Flushes, does not commit.
        Returns (device, created)."""
        now = datetime.now(timezone.utc)
        unified = Normalizer.normalize(source_name, raw)
        raw_source_uid = raw.get("source_uid")
        serial, hw_uuid = hardware_identity(raw)

        device = await Correlator._find_existing_device(
            db, source_name, raw_source_uid,
            unified.fqdn, unified.hostname, unified.mac_addresses,
            serial=serial, hw_uuid=hw_uuid,
        )

        created = device is None
        if created:
            device = Device(
                hostname=unified.hostname,
                fqdn=unified.fqdn,
                ip_addresses=unified.ip_addresses,
                mac_addresses=unified.mac_addresses,
                os_name=unified.os_family,
                os_version=unified.os_version,
                domain=unified.domain,
                ou=unified.ou,
                serial_number=serial,
                hardware_uuid=hw_uuid,
                last_seen=unified.last_seen or now,
                first_seen=now,
                status="active",
            )
            db.add(device)
            await db.flush()
        else:
            # Respect source authority when merging fields
            src_result = await db.execute(
                select(DeviceSource).where(DeviceSource.device_id == device.id)
            )
            existing_sources: List[DeviceSource] = src_result.scalars().all()

            if unified.hostname and Correlator._should_update_field(existing_sources, source_name, "hostname"):
                device.hostname = unified.hostname
            if unified.fqdn and Correlator._should_update_field(existing_sources, source_name, "fqdn"):
                device.fqdn = unified.fqdn
            if unified.os_family and Correlator._should_update_field(existing_sources, source_name, "os_name"):
                device.os_name = unified.os_family
            if unified.os_version and Correlator._should_update_field(existing_sources, source_name, "os_version"):
                device.os_version = unified.os_version
            if unified.domain and Correlator._should_update_field(existing_sources, source_name, "domain"):
                device.domain = unified.domain
            if unified.ou and Correlator._should_update_field(existing_sources, source_name, "ou"):
                device.ou = unified.ou
            # Hardware identity never changes for a machine: fill, don't overwrite.
            if serial and not device.serial_number:
                device.serial_number = serial
            if hw_uuid and not device.hardware_uuid:
                device.hardware_uuid = hw_uuid
            # IPs & MACs: always merge (union), not overwrite
            if unified.ip_addresses:
                existing_ips = set(device.ip_addresses or [])
                existing_ips.update(unified.ip_addresses)
                device.ip_addresses = sorted(existing_ips)
            if unified.mac_addresses:
                existing_macs = set(device.mac_addresses or [])
                existing_macs.update(unified.mac_addresses)
                device.mac_addresses = sorted(existing_macs)

            incoming_last_seen = unified.last_seen or now
            device_last_seen = device.last_seen.replace(tzinfo=timezone.utc) if device.last_seen else None
            if not device_last_seen or incoming_last_seen > device_last_seen:
                device.last_seen = incoming_last_seen

            device.status = "active"

        # Upsert DeviceSource
        result = await db.execute(
            select(DeviceSource)
            .where(DeviceSource.device_id == device.id)
            .where(DeviceSource.source_name == source_name)
        )
        device_source = result.scalars().first()

        source_uid = raw.get("source_uid") or str(device.id)
        if not device_source:
            db.add(DeviceSource(
                device_id=device.id,
                source_name=source_name,
                source_uid=source_uid,
                raw_data=Correlator._json_safe(raw),
                last_synced=now,
            ))
        else:
            device_source.source_uid = source_uid
            device_source.raw_data = Correlator._json_safe(raw)
            device_source.last_synced = now
        await db.flush()
        return device, created

    @staticmethod
    async def mark_stale_devices(
        db: AsyncSession,
        source_name: str,
        sync_start_time: datetime,
        stale_days: int = 30,
    ) -> int:
        """
        Finds DeviceSource records for `source_name` that were NOT refreshed in the
        current sync run (last_synced < sync_start_time). For each affected device,
        checks whether ANY of its sources (across all connectors) was seen within
        `stale_days`. If no source is fresh, the device is marked inactive.

        Using the global stale window rather than "touched in this run" ensures that a
        device stays active as long as at least one connector has seen it recently,
        even if other connectors haven't run yet.
        """
        from datetime import timedelta
        stale_threshold = timedelta(days=stale_days)
        now = datetime.now(timezone.utc)

        # DeviceSources for this connector that the current sync did not touch
        missed_result = await db.execute(
            select(DeviceSource)
            .where(DeviceSource.source_name == source_name)
            .where(DeviceSource.last_synced < sync_start_time)
        )
        missed_sources = missed_result.scalars().all()

        affected_device_ids = {s.device_id for s in missed_sources}
        count = 0

        for device_id in affected_device_ids:
            all_sources_result = await db.execute(
                select(DeviceSource).where(DeviceSource.device_id == device_id)
            )
            all_sources = all_sources_result.scalars().all()

            # Stay active if at least one source has synced within the stale window
            any_fresh = any(
                s.last_synced is not None
                and (now - s.last_synced.replace(tzinfo=timezone.utc)) < stale_threshold
                for s in all_sources
            )

            if not any_fresh:
                device_result = await db.execute(select(Device).where(Device.id == device_id))
                device = device_result.scalars().first()
                if device and device.status == "active":
                    device.status = "inactive"
                    count += 1

        await db.commit()
        return count
