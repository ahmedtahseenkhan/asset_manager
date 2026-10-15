"""
Executes scan targets in the background and records each run.

A run: expand the target's addresses → sweep them (ping/ARP + name/port/SNMP
probes from the network-scan connector) → merge each responsive host through
the correlator → if the target has credentialed methods and credentials,
inventory each responsive host over WinRM / SSH / SNMP (scanning.credentialed)
→ store a per-host result with the outcome.

Runs execute as asyncio tasks inside the API process; their state lives in
scan_runs, so the UI can follow progress and a restart leaves an honest record.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import select, update

from backend.connectors.network_scan.connector import NetworkScanConnector
from backend.correlator.correlator import Correlator
from backend.models.scan_credential import ScanCredential
from backend.models.scan_run import ScanHostResult, ScanRun
from backend.models.scan_target import ScanTarget
from backend.scanning.collectors import CredentialInput
from backend.scanning.credentialed import METHOD_ORDER, HostKeyStore, inventory_host
from backend.scanning.targets import TargetSpecError, resolve
from backend.services.inventory_service import InventoryService

logger = logging.getLogger(__name__)

SWEEP_SOURCE = "network_scan"   # devices found by a sweep merge with the connector's
MAX_PARALLEL_INVENTORY = 16


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
                    addresses = await resolve(db, target.target_type, target.value, target.exclusions or "")
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

                # Credentialed collection is heavier than a ping: cap parallel sessions.
                concurrency = max(1, min(target.concurrency or 16, MAX_PARALLEL_INVENTORY))
                methods = [m for m in (target.methods or []) if m in METHOD_ORDER]
                credentials = [CredentialInput.from_model(link.credential) for link in target.credential_links
                               if link.credential is not None]

            records = await NetworkScanConnector().fetch_devices(config)

            hosts = []   # (result id, ip, device id) of every responsive address
            async with self._sessions()() as db:
                for raw in records:
                    device, _ = await Correlator.upsert_device(db, SWEEP_SOURCE, raw)
                    result = ScanHostResult(
                        run_id=run_id,
                        ip=(raw.get("ip_addresses") or ["?"])[0],
                        hostname=raw.get("hostname"),
                        status="alive",
                        method="ping",
                        device_id=device.id,
                    )
                    db.add(result)
                    await db.flush()
                    hosts.append((result.id, result.ip, device.id))
                await db.execute(update(ScanRun).where(ScanRun.id == run_id).values(hosts_alive=len(hosts)))
                await db.commit()

            if methods and credentials and hosts:
                await self._inventory_hosts(run_id, hosts, methods, credentials, concurrency)
            await self._finish(run_id, "completed")
        except asyncio.CancelledError:
            await self._finish(run_id, "cancelled")
            raise
        except Exception as exc:
            logger.error("Scan run %s failed: %s", run_id, exc, exc_info=True)
            await self._finish(run_id, "failed", str(exc) or type(exc).__name__)

    async def _inventory_hosts(self, run_id: int, hosts: list, methods: List[str],
                               credentials: List[CredentialInput], concurrency: int) -> None:
        keys = HostKeyStore(self._sessions())
        sem = asyncio.Semaphore(concurrency)
        counts = {"inventoried": 0, "failed": 0}

        async def one(result_id: int, ip: str, device_id: int) -> None:
            async with sem:
                async with self._sessions()() as db:
                    preferred = (await db.execute(
                        select(ScanHostResult.credential_id)
                        .where(ScanHostResult.device_id == device_id, ScanHostResult.status == "inventoried",
                               ScanHostResult.credential_id.isnot(None))
                        .order_by(ScanHostResult.id.desc()).limit(1)
                    )).scalar()
                outcome = await inventory_host(ip, methods, credentials, keys, preferred)
                if not outcome.attempts:
                    return            # no applicable method answered: stays a sweep-only result
                async with self._sessions()() as db:
                    result = await db.get(ScanHostResult, result_id)
                    now = _now()
                    tried = {a.credential_id for a in outcome.attempts}
                    for cred in (await db.execute(select(ScanCredential).where(ScanCredential.id.in_(tried)))).scalars():
                        cred.last_used_at = now
                        if outcome.report is not None and cred.id == outcome.credential_id:
                            cred.last_success_at = now
                    result.method, result.credential_id = outcome.method, outcome.credential_id
                    result.error_code, result.error_message = outcome.error_code, outcome.error_message
                    result.duration_ms = outcome.duration_ms
                    if outcome.report is not None:
                        ingested = await InventoryService.ingest(db, outcome.method, outcome.report,
                                                                 fallback_device_id=device_id)
                        result.status = "inventoried"
                        result.device_id = ingested["device_id"]
                        result.hostname = ingested["hostname"] or result.hostname
                        counts["inventoried"] += 1
                    else:
                        result.status = "failed"
                        counts["failed"] += 1
                    await db.commit()

        await asyncio.gather(*(one(*h) for h in hosts))
        async with self._sessions()() as db:
            await db.execute(update(ScanRun).where(ScanRun.id == run_id).values(
                hosts_inventoried=counts["inventoried"], hosts_failed=counts["failed"]))
            await db.commit()

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
