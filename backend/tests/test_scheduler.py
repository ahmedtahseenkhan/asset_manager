"""Scheduled jobs must be storable by the persistent job store (module-level
callables), and must follow targets/connectors being enabled or disabled."""
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from backend.models.connector_config import ConnectorConfig
from backend.services.scheduler_service import SchedulerService


def _service():
    svc = SchedulerService()
    svc.scheduler = AsyncIOScheduler()   # in-memory store; not started
    return svc


async def test_jobs_follow_targets_and_connectors(api):
    async with api.session_factory() as s:
        s.add(ConnectorConfig(connector_name="network_scan", enabled=True,
                              config={}, schedule_cron="0 */6 * * *"))
        await s.commit()
    target = (await api.post("/api/scan/targets", json={
        "name": "HQ", "target_type": "cidr", "value": "10.0.0.0/30", "schedule_cron": "30 2 * * *",
    })).json()["data"]

    svc = _service()
    async with api.session_factory() as s:
        await svc.reload_jobs(s)
    jobs = {j.id: j for j in svc.scheduler.get_jobs()}
    assert set(jobs) == {"sync_network_scan", f"scan_target_{target['id']}"}
    # A textual reference is what the SQLAlchemy job store pickles.
    assert jobs[f"scan_target_{target['id']}"].func_ref == \
        "backend.services.scheduler_service:run_scan_target"
    assert jobs[f"scan_target_{target['id']}"].args == (target["id"],)

    await api.patch(f"/api/scan/targets/{target['id']}", json={"enabled": False})
    async with api.session_factory() as s:
        await svc.reload_jobs(s)
    assert {j.id for j in svc.scheduler.get_jobs()} == {"sync_network_scan"}
