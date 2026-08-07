"""
Retention / archival policy for devices.

Two-stage lifecycle managed by configurable environment variables:
  RETIRE_INACTIVE_AFTER_DAYS  (default 90)  inactive  → retired
  PURGE_RETIRED_AFTER_DAYS    (default 365) retired   → deleted

Both stages run in a single pass so one scheduler job covers everything.
The service is also exposed via POST /api/admin/retention/run for manual runs.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from backend.models.device import Device

logger = logging.getLogger(__name__)

_RETIRE_DAYS = 90
_PURGE_DAYS  = 365


class RetentionService:
    @staticmethod
    async def run(
        db: AsyncSession,
        retire_after_days: int = _RETIRE_DAYS,
        purge_after_days:  int = _PURGE_DAYS,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        retire_cutoff = now - timedelta(days=retire_after_days)
        purge_cutoff  = now - timedelta(days=purge_after_days)

        # Stage 1: inactive → retired (last_seen older than retire_cutoff)
        inactive_result = await db.execute(
            select(Device)
            .where(Device.status == "inactive")
            .where(Device.last_seen < retire_cutoff)
        )
        inactive_devices = inactive_result.scalars().all()
        retired_count = 0
        for device in inactive_devices:
            device.status = "retired"
            retired_count += 1

        # Stage 2: retired → purged (last_seen older than purge_cutoff)
        retired_result = await db.execute(
            select(Device)
            .where(Device.status == "retired")
            .where(Device.last_seen < purge_cutoff)
        )
        retired_devices = retired_result.scalars().all()
        purged_count = 0
        for device in retired_devices:
            await db.delete(device)
            purged_count += 1

        await db.commit()

        summary = {
            "retired": retired_count,
            "purged":  purged_count,
            "retire_after_days": retire_after_days,
            "purge_after_days":  purge_after_days,
            "ran_at": now.isoformat(),
        }
        logger.info(f"Retention run: {summary}")
        return summary
