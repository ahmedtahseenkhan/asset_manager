import asyncio
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from backend.models.connector_config import ConnectorConfig
from backend.models.sync_log import SyncLog
from backend.connectors.registry import registry
from backend.correlator.correlator import Correlator
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Per-connector locks: prevents concurrent syncs for the same connector
_sync_locks: dict[str, asyncio.Lock] = {}


def _get_lock(connector_name: str) -> asyncio.Lock:
    if connector_name not in _sync_locks:
        _sync_locks[connector_name] = asyncio.Lock()
    return _sync_locks[connector_name]


class SyncService:
    @staticmethod
    async def run_sync_for_connector(db: AsyncSession, connector_id: int):
        """Runs the entire sync pipeline for a specific connector config."""
        from sqlalchemy.future import select
        result = await db.execute(select(ConnectorConfig).where(ConnectorConfig.id == connector_id))
        config = result.scalars().first()

        if not config or not config.enabled:
            logger.info(f"Sync skipped for connector {connector_id}: disabled or not found.")
            return

        lock = _get_lock(config.connector_name)
        if lock.locked():
            logger.warning(f"Sync already running for {config.connector_name} — skipping duplicate run.")
            return

        async with lock:
            logger.info(f"Starting sync for connector {config.connector_name}")

            sync_log = SyncLog(connector_name=config.connector_name, status="running")
            db.add(sync_log)
            await db.commit()
            await db.refresh(sync_log)

            try:
                connector = registry.get_connector(config.connector_name)
                raw_devices = await connector.fetch_devices(config.config)
                sync_log.records_fetched = len(raw_devices)

                sync_start = datetime.now(timezone.utc)
                created, updated = await Correlator.process_batch(db, config.connector_name, raw_devices)
                stale_count = await Correlator.mark_stale_devices(db, config.connector_name, sync_start)

                sync_log.records_created = created
                sync_log.records_updated = updated
                sync_log.status = f"success (staled {stale_count})"

            except Exception as e:
                logger.error(f"Sync failed for {config.connector_name}: {e}", exc_info=True)
                sync_log.status = "failed"
                sync_log.errors = [str(e)]

            finally:
                sync_log.finished_at = datetime.now(timezone.utc)
                config.last_run = sync_log.finished_at
                config.last_status = sync_log.status
                db.add(sync_log)
                db.add(config)
                await db.commit()

            logger.info(f"Sync finished for {config.connector_name}. Status: {sync_log.status}")
