"""
Executes scan targets in the background and records each run.

A run: expand the target's addresses → sweep them (ping/ARP + name/port/SNMP
probes from the network-scan connector) → merge each responsive host through
the correlator → store a per-host result. Credentialed methods (WinRM, WMI,
SSH, SNMP with credentials) plug in here in Phase 2.

Runs execute as asyncio tasks inside the API process; their state lives in
scan_runs, so the UI can follow progress and a restart leaves an honest record.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from sqlalchemy import update

from backend.connectors.network_scan.connector import NetworkScanConnector
from backend.correlator.correlator import Correlator
from backend.models.scan_run import ScanHostResult, ScanRun
from backend.models.scan_target import ScanTarget
from backend.scanning.targets import TargetSpecError, expand

logger = logging.getLogger(__name__)

SWEEP_SOURCE = "network_scan"   # devices found by a sweep merge with the connector's


class ScanAlreadyRunning(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ScanRunner:
    def __init__(self) -> None:
        self._tasks: Dict[int, asyncio.Task] = {}      # run_id -> task
        self._targets: Dict[int, int] = {}             # target_id -> active run_id
        self.session_factory = None                    # tests inject their own

    def _sessions(self):
        if self.session_factory is None:
            from backend.database import async_session
            return async_session
        return self.session_factory

    def is_running(self, target_id: int) -> bool:
        return target_id in self._targets

    async def start(self, target_id: int, trigger: str, user_id: Optional[int] = None) -> int:
        """Queue a run and start it in the background. Returns the run id."""
        if self.is_running(target_id):
            raise ScanAlreadyRunning(f"Target {target_id} is already being scanned")
        async with self._sessions()() as db:
            target = await db.get(ScanTarget, target_id)
            if target is None:
                raise LookupError(f"Scan target {target_id} not found")
            run = ScanRun(target_id=target.id, target_name=target.name, trigger=trigger,
                          status="queued", created_by=user_id)
            db.add(run)
            await db.commit()
            run_id = run.id

        self._targets[target_id] = run_id
        task = asyncio.create_task(self._execute(run_id, target_id), name=f"scan-run-{run_id}")
        self._tasks[run_id] = task
        task.add_done_callback(lambda _t: self._forget(run_id, target_id))
        return run_id

    def _forget(self, run_id: int, target_id: int) -> None:
        self._tasks.pop(run_id, None)
        if self._targets.get(target_id) == run_id:
            self._targets.pop(target_id, None)

    def cancel(self, run_id: int) -> bool:
        task = self._tasks.get(run_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    async def wait(self, run_id: int) -> None:
        """Block until a run finishes (tests, CLI)."""
        task = self._tasks.get(run_id)
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    async def _finish(self, run_id: int, status: str, error: Optional[str] = None) -> None:
        async with self._sessions()() as db:
            run = await db.get(ScanRun, run_id)
            run.status = status
            run.error = error
            run.finished_at = _now()
            if run.target_id:
                target = await db.get(ScanTarget, run.target_id)
                if target:
                    target.last_run_at = run.finished_at
                    target.last_status = status
            await db.commit()

    async def _execute(self, run_id: int, target_id: int) -> None:
        try:
            async with self._sessions()() as db:
                target = await db.get(ScanTarget, target_id)
                run = await db.get(ScanRun, run_id)
                try:
                    addresses = await asyncio.to_thread(
                        expand, target.target_type, target.value, target.exclusions or "")
                except TargetSpecError as exc:
                    await db.rollback()
                    await self._finish(run_id, "failed", str(exc))
                    return
                run.status = "running"
                run.started_at = _now()
                run.hosts_total = len(addresses)
                config = {
                    "addresses": addresses,
                    "timeout_ms": target.timeout_ms,
                    "deep_probe": target.deep_probe,
                    "concurrency": target.concurrency,
                }
                await db.commit()

            records = await NetworkScanConnector().fetch_devices(config)

            async with self._sessions()() as db:
                alive = 0
                for raw in records:
                    device, _ = await Correlator.upsert_device(db, SWEEP_SOURCE, raw)
                    alive += 1
                    db.add(ScanHostResult(
                        run_id=run_id,
                        ip=(raw.get("ip_addresses") or ["?"])[0],
                        hostname=raw.get("hostname"),
                        status="alive",
                        method="ping",
                        device_id=device.id,
                    ))
                await db.execute(update(ScanRun).where(ScanRun.id == run_id).values(hosts_alive=alive))
                await db.commit()
            await self._finish(run_id, "completed")
        except asyncio.CancelledError:
            await self._finish(run_id, "cancelled")
            raise
        except Exception as exc:
            logger.error("Scan run %s failed: %s", run_id, exc, exc_info=True)
            await self._finish(run_id, "failed", str(exc) or type(exc).__name__)

    async def recover_interrupted(self) -> int:
        """Runs left queued/running by a restart can never finish: close them."""
        async with self._sessions()() as db:
            result = await db.execute(
                update(ScanRun)
                .where(ScanRun.status.in_(("queued", "running")))
                .values(status="failed", error="Interrupted by a server restart", finished_at=_now())
            )
            await db.commit()
            return result.rowcount or 0


scan_runner = ScanRunner()
