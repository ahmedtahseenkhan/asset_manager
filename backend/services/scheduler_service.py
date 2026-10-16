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


async def daily_notifications():
    # Module-level function: the SQLAlchemy jobstore needs a picklable reference.
    from backend.services.notification_service import NotificationService
    async for session in get_db():
        summary = await NotificationService.run_checks(session)
        logger.info("Daily notification run: %s", summary)


async def daily_lifecycle():
    # End-of-life status and software categories: picks up devices only
    # connectors know, and keeps up with an uploaded catalogue.
    from backend.services.lifecycle_service import LifecycleService
    async for session in get_db():
        await LifecycleService.load_catalog(session)
        await LifecycleService.refresh_all(session)


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
        # Daily end-of-life / software catalogue refresh at 03:00 UTC
        self.scheduler.add_job(
            daily_lifecycle,
            trigger="cron",
            hour=3, minute=0,
            id="daily_lifecycle",
            replace_existing=True,
        )
        # Daily expiry alerts at 08:00 UTC
        self.scheduler.add_job(
            daily_notifications,
            trigger="cron",
            hour=8, minute=0,
            id="daily_notifications",
            replace_existing=True,
        )
        self.scheduler.start()
        logger.info("Scheduler started.")

    def stop(self):
        self.scheduler.shutdown()
        logger.info("Scheduler stopped.")

    async def reload_jobs(self, db: AsyncSession):
        """Register a cron job per enabled connector, scan target and scheduled
        report, and drop jobs whose item was disabled, unscheduled or deleted.

        Jobs reference module-level functions by name: the SQLAlchemy job store
        pickles the callable, so closures cannot be scheduled."""
        from sqlalchemy.future import select
        from backend.models.connector_config import ConnectorConfig
        from backend.models.scan_target import ScanTarget

        wanted: dict[str, tuple] = {}
        for c in (await db.execute(select(ConnectorConfig).where(ConnectorConfig.enabled == True))).scalars():
            if c.schedule_cron:
                wanted[f"sync_{c.connector_name}"] = (run_connector_sync, c.id, c.schedule_cron)
        for t in (await db.execute(select(ScanTarget).where(ScanTarget.enabled == True))).scalars():
            if t.schedule_cron:
                wanted[f"scan_target_{t.id}"] = (run_scan_target, t.id, t.schedule_cron)
        from backend.models.saved_report import SavedReport
        for r in (await db.execute(select(SavedReport).where(SavedReport.schedule_cron.isnot(None)))).scalars():
            wanted[f"report_{r.id}"] = (run_scheduled_report, r.id, r.schedule_cron)

        for job in self.scheduler.get_jobs():
            if job.id.startswith(("sync_", "scan_target_", "report_")) and job.id not in wanted:
                job.remove()
                logger.info("Removed scheduled job %s", job.id)

        for job_id, (func, arg, cron) in wanted.items():
            try:
                self.scheduler.add_job(func, trigger=CronTrigger.from_crontab(cron), args=[arg],
                                       id=job_id, replace_existing=True)
                logger.info("Scheduled %s with cron %r", job_id, cron)
            except Exception as e:
                logger.error("Failed to schedule %s: %s", job_id, e)


async def run_connector_sync(config_id: int):
    try:
        async for session in get_db():
            await SyncService.run_sync_for_connector(session, config_id)
    except Exception as e:
        logger.error("Scheduled sync failed for connector config %s: %s", config_id, e)


async def run_scheduled_report(report_id: int):
    from backend.models.saved_report import SavedReport
    from backend.reporting.service import send_report
    try:
        async for session in get_db():
            report = await session.get(SavedReport, report_id)
            if report is None or not report.schedule_cron:
                return
            logger.info("Scheduled report %s: %s", report_id, await send_report(session, report))
    except Exception as e:
        logger.error("Scheduled report %s failed: %s", report_id, e)


async def run_scan_target(target_id: int):
    from backend.scanning.runner import ScanAlreadyRunning, scan_runner
    try:
        run_id = await scan_runner.start(target_id, trigger="schedule")
        await scan_runner.wait(run_id)
    except ScanAlreadyRunning:
        logger.info("Skipping scheduled scan of target %s: previous run still active", target_id)
    except Exception as e:
        logger.error("Scheduled scan of target %s failed to start: %s", target_id, e)


# Global scheduler
scheduler = SchedulerService()
