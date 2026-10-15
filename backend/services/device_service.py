from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, or_, not_, exists
from sqlalchemy.orm import selectinload
from typing import Dict, Any, List

from backend.models.device import Device
from backend.models.device_source import DeviceSource
from backend.schemas.device import DeviceFilter

class DeviceService:
    @staticmethod
    async def get_dashboard_summary(db: AsyncSession) -> Dict[str, Any]:
        """Provides high-level stats for the dashboard."""
        total_devices = await db.scalar(select(func.count(Device.id)))
        active_devices = await db.scalar(select(func.count(Device.id)).where(Device.status == "active"))
        stale_devices = await db.scalar(select(func.count(Device.id)).where(Device.status == "inactive"))

        os_stats_result = await db.execute(select(Device.os_name, func.count(Device.id)).group_by(Device.os_name))
        os_dist = [{"name": row[0] or "Unknown", "value": row[1]} for row in os_stats_result]

        source_stats_result = await db.execute(select(DeviceSource.source_name, func.count(DeviceSource.id)).group_by(DeviceSource.source_name))
        source_dist = [{"name": row[0], "value": row[1]} for row in source_stats_result]

        # Quick coverage gap count: active devices missing from at least one source
        # We use a subquery to count distinct device_ids that have sources,
        # then subtract from active count to get those with NO sources at all,
        # plus those that have fewer sources than the total enabled connectors.
        # For the summary widget we just count devices that have < max(sources) per device.
        from sqlalchemy import func as _func
        # Count active devices that appear in device_sources at all vs total active

        covered = await db.scalar(
            select(_func.count()).select_from(
                select(Device.id)
                .where(Device.status == "active")
                .join(DeviceSource, DeviceSource.device_id == Device.id)
                .distinct()
                .subquery()
            )
        )
        gap_count = (active_devices or 0) - (covered or 0)

        return {
            "total_devices":      total_devices or 0,
            "active_devices":     active_devices or 0,
            "stale_devices":      stale_devices or 0,
            "coverage_gap_count": max(gap_count, 0),
            "os_distribution":    os_dist,
            "source_distribution": source_dist,
        }

    @staticmethod
    async def get_coverage_gaps(db: AsyncSession, enabled_sources: List[str]) -> Dict[str, Any]:
        """
        Returns devices missing from one or more enabled connector sources.
        A gap means: device is active but has NO DeviceSource record for that connector.
        """
        if not enabled_sources:
            # Must return the full shape — clients rely on every key being present.
            return {
                "enabled_sources": [],
                "total_active_devices": await db.scalar(
                    select(func.count(Device.id)).where(Device.status == "active")
                ) or 0,
                "devices_with_gaps": 0,
                "missing_per_source": [],
                "gaps": [],
            }

        # Fetch all active devices with their sources
        result = await db.execute(
            select(Device)
            .options(selectinload(Device.sources))
            .where(Device.status == "active")
        )
        devices = result.scalars().all()

        gaps = []
        for device in devices:
            device_sources = {s.source_name for s in device.sources}
            missing = sorted(set(enabled_sources) - device_sources)
            if missing:
                gaps.append({
                    "device_id": device.id,
                    "hostname": device.hostname,
                    "fqdn": device.fqdn,
                    "ip_addresses": device.ip_addresses,
                    "os_name": device.os_name,
                    "known_sources": sorted(device_sources),
                    "missing_sources": missing,
                })

        # Summary counts per missing source
        missing_counts: Dict[str, int] = {s: 0 for s in enabled_sources}
        for gap in gaps:
            for src in gap["missing_sources"]:
                missing_counts[src] = missing_counts.get(src, 0) + 1

        return {
            "enabled_sources": enabled_sources,
            "total_active_devices": len(devices),
            "devices_with_gaps": len(gaps),
            "missing_per_source": [{"source": k, "count": v} for k, v in missing_counts.items()],
            "gaps": gaps,
        }

    @staticmethod
    async def get_devices(db: AsyncSession, page: int = 1, size: int = 50, filter_params: DeviceFilter = None) -> tuple[int, list]:
        """Returns paginated and filtered devices."""
        query = select(Device).options(selectinload(Device.sources))
        
        if filter_params:
            if filter_params.search:
                search_term = f"%{filter_params.search}%"
                query = query.where(or_(
                    Device.hostname.ilike(search_term),
                    Device.fqdn.ilike(search_term),
                    Device.ip_addresses.cast(str).ilike(search_term)
                ))
            if filter_params.os_name:
                query = query.where(Device.os_name.ilike(f"%{filter_params.os_name}%"))
            if filter_params.status:
                query = query.where(Device.status == filter_params.status)
            if filter_params.health:
                from backend.models.inventory import DeviceInventory
                from backend.services.endpoint_health import health_conditions
                cond = health_conditions().get(filter_params.health)
                if cond is None:
                    raise ValueError(f"Unknown health filter {filter_params.health!r}")
                query = query.join(DeviceInventory, DeviceInventory.device_id == Device.id).where(cond)
                
        # Total count
        count_query = select(func.count()).select_from(query.subquery())
        total = await db.scalar(count_query)
        
        # Pagination
        query = query.order_by(Device.last_seen.desc().nullslast(), Device.id.desc()).offset((page - 1) * size).limit(size)
        result = await db.execute(query)
        devices = result.scalars().all()
        
        return total, devices

    @staticmethod
    async def get_device_by_id(db: AsyncSession, device_id: int) -> Device | None:
        result = await db.execute(select(Device).options(selectinload(Device.sources)).where(Device.id == device_id))
        return result.scalars().first()
