import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncSession
from backend.services.sync_service import SyncService
from backend.services.retention_service import RetentionService
from backend.database import get_db
from backend.config import settings

logger = logging.getLogger(__name__)

jobstores = {
    'default': SQLAlchemyJobStore(url=settings.database_url.replace('+asyncpg', ''))
}

async def daily_retention():
    async for session in get_db():
        await RetentionService.run(session)


class SchedulerService:
    def __init__(self):
        self.scheduler = AsyncIOScheduler(jobstores=jobstores)

    def start(self):
        # Daily retention run at 02:00 UTC
        self.scheduler.add_job(
            daily_retention,
            trigger="cron",
            hour=2, minute=0,
            id="daily_retention",
            replace_existing=True,
        )
        self.scheduler.start()
        logger.info("Scheduler started.")

    def stop(self):
        self.scheduler.shutdown()
        logger.info("Scheduler stopped.")

    async def reload_jobs(self, db: AsyncSession):
        """Fetches active configurations and registers them as cron jobs."""
        from sqlalchemy.future import select
        from backend.models.connector_config import ConnectorConfig
        
        result = await db.execute(select(ConnectorConfig).where(ConnectorConfig.enabled == True))
        configs = result.scalars().all()
        
        # Clear existing
        # Relying on replace_existing=True for updates

            
        for config in configs:
            if not config.schedule_cron: continue
            
            job_id = f"sync_{config.connector_name}"
            # Need a wrapper to grab a fresh DB session each time the job runs
            async def sync_job(config_id=config.id):
                try:
                    # apscheduler doesn't have request context, so we manually get a session generator
                    async for session in get_db():
                        await SyncService.run_sync_for_connector(session, config_id)
                except Exception as e:
                    logger.error(f"Scheduled sync failed for config {config_id}: {e}")

            try:
                trigger = CronTrigger.from_crontab(config.schedule_cron)
                job = self.scheduler.add_job(sync_job, trigger=trigger, id=job_id, replace_existing=True)
                logger.info(f"Added scheduled job for {config.connector_name} with cron: {config.schedule_cron}")
            except Exception as e:
                logger.error(f"Failed to add job for {config.connector_name}: {e}")

# Global scheduler
scheduler = SchedulerService()
