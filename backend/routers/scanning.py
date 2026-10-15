"""
Credential vault, scan targets and scan runs (licence module: discovery_plus).
Admin-only; every change is written to the audit log. Secrets are accepted on
create/update and never returned.
"""
import asyncio
from typing import Any, Dict, List, Optional

from apscheduler.triggers.cron import CronTrigger
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.licensing.enforcement import require_module
from backend.middleware.auth import require_admin
from backend.models.scan_credential import ScanCredential
from backend.models.scan_run import ScanHostResult, ScanRun
from backend.models.scan_target import ScanTarget, ScanTargetCredential
from backend.models.user import User
from backend.scanning.credentials import CREDENTIAL_TYPES, CredentialError, public_view, validate
from backend.scanning.runner import ScanAlreadyRunning, scan_runner
from backend.scanning.collectors import CollectorError, CredentialInput
from backend.scanning.credentialed import HostKeyStore, test_credential
from backend.scanning.targets import TARGET_TYPES, TargetSpecError, resolve
from backend.models.ssh_host_key import SshHostKey
from backend.schemas.common import APIResponse
from backend.services.audit_service import AuditService
from backend.services.scheduler_service import scheduler

router = APIRouter(prefix="/scan", tags=["Scanning"], dependencies=[require_module("discovery_plus")])

# Methods a target can enable: the sweep plus credentialed inventory.
SCAN_METHODS = ("ping", "winrm", "ssh", "snmp")
_RETIRED_METHODS = {"wmi"}      # planned WMI-over-DCOM was replaced by WinRM


# ── Credentials ─────────────────────────────────────────────────────────────
class CredentialIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    cred_type: str
    username: Optional[str] = Field(default=None, max_length=255)
    params: Dict[str, Any] = Field(default_factory=dict)
    secret: Dict[str, Any] = Field(default_factory=dict)
    description: Optional[str] = None


class CredentialUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    username: Optional[str] = Field(default=None, max_length=255)
    params: Optional[Dict[str, Any]] = None
    secret: Dict[str, Any] = Field(default_factory=dict)   # only keys sent are replaced
    description: Optional[str] = None


async def _get_credential(db: AsyncSession, cred_id: int) -> ScanCredential:
    cred = await db.get(ScanCredential, cred_id)
    if cred is None:
        raise HTTPException(404, "Credential not found")
    return cred


@router.get("/credential-types", response_model=APIResponse[Dict[str, Any]])
async def credential_types(admin: User = Depends(require_admin)):
    return APIResponse(data={
        t: {"label": s["label"], "username": s["username"],
            "secrets": [{"name": k, "required": r} for k, r in s["secrets"].items()],
            "params": {k: (list(v) if v else None) for k, v in s["params"].items()}}
        for t, s in CREDENTIAL_TYPES.items()
    })


@router.get("/credentials", response_model=APIResponse[List[Dict[str, Any]]])
async def list_credentials(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    rows = (await db.execute(select(ScanCredential).order_by(ScanCredential.name))).scalars().all()
    usage = dict((await db.execute(
        select(ScanTargetCredential.credential_id, func.count())
        .group_by(ScanTargetCredential.credential_id)
    )).all())
    return APIResponse(data=[{**public_view(c), "target_count": usage.get(c.id, 0)} for c in rows])


@router.post("/credentials", response_model=APIResponse[Dict[str, Any]])
async def create_credential(body: CredentialIn, request: Request,
                            db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    try:
        params, secret = validate(body.cred_type, body.username, body.params, body.secret)
    except CredentialError as exc:
        raise HTTPException(400, str(exc))
    cred = ScanCredential(name=body.name.strip(), cred_type=body.cred_type,
                          username=(body.username or "").strip() or None, params=params,
                          secret=secret, description=body.description, created_by=admin.id)
    db.add(cred)
    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(409, f"A credential named {body.name!r} already exists")
    await AuditService.log(db, request, admin, "scan.credential_created", resource_type="scan_credential",
                           resource_id=str(cred.id), detail={"name": cred.name, "type": cred.cred_type})
    await db.commit()
    await db.refresh(cred)
    return APIResponse(data=public_view(cred), message="Credential saved")


@router.patch("/credentials/{cred_id}", response_model=APIResponse[Dict[str, Any]])
async def update_credential(cred_id: int, body: CredentialUpdate, request: Request,
                            db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    cred = await _get_credential(db, cred_id)
    username = body.username if body.username is not None else cred.username
    params = body.params if body.params is not None else (cred.params or {})
    try:
        params, new_secret = validate(cred.cred_type, username, params, body.secret, partial_secret=True)
    except CredentialError as exc:
        raise HTTPException(400, str(exc))
    if body.name is not None:
        cred.name = body.name.strip()
    cred.username = (username or "").strip() or None
    cred.params = params
    if new_secret:
        cred.secret = {**(cred.secret or {}), **new_secret}
    if body.description is not None:
        cred.description = body.description
    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(409, f"A credential named {body.name!r} already exists")
    await AuditService.log(db, request, admin, "scan.credential_updated", resource_type="scan_credential",
                           resource_id=str(cred.id),
                           detail={"name": cred.name, "secrets_changed": sorted(new_secret)})
    await db.commit()
    await db.refresh(cred)
    return APIResponse(data=public_view(cred), message="Credential updated")


@router.delete("/credentials/{cred_id}", response_model=APIResponse[bool])
async def delete_credential(cred_id: int, request: Request,
                            db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    cred = await _get_credential(db, cred_id)
    await db.execute(delete(ScanTargetCredential).where(ScanTargetCredential.credential_id == cred_id))
    await db.delete(cred)
    await AuditService.log(db, request, admin, "scan.credential_deleted", resource_type="scan_credential",
                           resource_id=str(cred_id), detail={"name": cred.name})
    await db.commit()
    return APIResponse(data=True, message="Credential deleted")


# ── Targets ─────────────────────────────────────────────────────────────────
class TargetSpec(BaseModel):
    target_type: str
    value: str = Field(min_length=1)
    exclusions: str = ""


class TargetIn(TargetSpec):
    name: str = Field(min_length=1, max_length=255)
    enabled: bool = True
    schedule_cron: Optional[str] = None
    methods: List[str] = Field(default_factory=lambda: ["ping"])
    concurrency: int = Field(default=32, ge=1, le=128)
    timeout_ms: int = Field(default=1000, ge=200, le=10_000)
    deep_probe: bool = True
    credential_ids: List[int] = Field(default_factory=list)


class TargetUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    enabled: Optional[bool] = None
    target_type: Optional[str] = None
    value: Optional[str] = None
    exclusions: Optional[str] = None
    schedule_cron: Optional[str] = None
    clear_schedule: bool = False
    methods: Optional[List[str]] = None
    concurrency: Optional[int] = Field(default=None, ge=1, le=128)
    timeout_ms: Optional[int] = Field(default=None, ge=200, le=10_000)
    deep_probe: Optional[bool] = None
    credential_ids: Optional[List[int]] = None


async def _expand_or_400(db: AsyncSession, target_type: str, value: str, exclusions: str) -> List[str]:
    try:
        return await resolve(db, target_type, value, exclusions)
    except TargetSpecError as exc:
        raise HTTPException(400, str(exc))


def _check_cron(cron: Optional[str]) -> Optional[str]:
    cron = (cron or "").strip() or None
    if cron:
        try:
            CronTrigger.from_crontab(cron)
        except ValueError as exc:
            raise HTTPException(400, f"Invalid schedule {cron!r}: {exc}")
    return cron


def _check_methods(methods: List[str]) -> List[str]:
    methods = [m for m in methods if m not in _RETIRED_METHODS]
    unknown = set(methods) - set(SCAN_METHODS)
    if unknown:
        raise HTTPException(400, f"Unknown scan method(s): {', '.join(sorted(unknown))}")
    # The sweep finds the hosts every other method then talks to.
    return ["ping", *[m for m in SCAN_METHODS if m in methods and m != "ping"]]


async def _set_credentials(db: AsyncSession, target: ScanTarget, credential_ids: List[int]) -> None:
    if len(set(credential_ids)) != len(credential_ids):
        raise HTTPException(400, "A credential is listed twice")
    if credential_ids:
        found = set((await db.execute(
            select(ScanCredential.id).where(ScanCredential.id.in_(credential_ids)))).scalars())
        missing = set(credential_ids) - found
        if missing:
            raise HTTPException(400, f"Unknown credential id(s): {sorted(missing)}")
    if target.id is not None:
        # Delete first: re-inserting a kept credential before the old row is
        # gone would violate uq_target_credential.
        await db.execute(delete(ScanTargetCredential).where(ScanTargetCredential.target_id == target.id))
        await db.refresh(target, attribute_names=["credential_links"])
    for i, cid in enumerate(credential_ids):
        target.credential_links.append(ScanTargetCredential(credential_id=cid, position=i))


def _target_view(t: ScanTarget) -> Dict[str, Any]:
    return {
        "id": t.id, "name": t.name, "enabled": t.enabled,
        "target_type": t.target_type, "value": t.value, "exclusions": t.exclusions,
        "schedule_cron": t.schedule_cron, "methods": t.methods or ["ping"],
        "concurrency": t.concurrency, "timeout_ms": t.timeout_ms, "deep_probe": t.deep_probe,
        "credential_ids": [link.credential_id for link in t.credential_links],
        "last_run_at": t.last_run_at, "last_status": t.last_status,
        "running": scan_runner.is_running(t.id),
        "created_at": t.created_at, "updated_at": t.updated_at,
    }


async def _get_target(db: AsyncSession, target_id: int) -> ScanTarget:
    target = await db.get(ScanTarget, target_id)
    if target is None:
        raise HTTPException(404, "Scan target not found")
    return target


@router.post("/targets/preview", response_model=APIResponse[Dict[str, Any]])
async def preview_target(body: TargetSpec, db: AsyncSession = Depends(get_db),
                         admin: User = Depends(require_admin)):
    """Validate a spec and show what it expands to, before saving."""
    addrs = await _expand_or_400(db, body.target_type, body.value, body.exclusions)
    return APIResponse(data={"count": len(addrs), "sample": addrs[:10]})


@router.get("/targets", response_model=APIResponse[List[Dict[str, Any]]])
async def list_targets(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    rows = (await db.execute(select(ScanTarget).order_by(ScanTarget.name))).scalars().all()
    return APIResponse(data=[_target_view(t) for t in rows])


@router.post("/targets", response_model=APIResponse[Dict[str, Any]])
async def create_target(body: TargetIn, request: Request,
                        db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    if body.target_type not in TARGET_TYPES:
        raise HTTPException(400, f"target_type must be one of {', '.join(TARGET_TYPES)}")
    await _expand_or_400(db, body.target_type, body.value, body.exclusions)
    target = ScanTarget(
        name=body.name.strip(), enabled=body.enabled, target_type=body.target_type,
        value=body.value.strip(), exclusions=body.exclusions.strip(),
        schedule_cron=_check_cron(body.schedule_cron), methods=_check_methods(body.methods),
        concurrency=body.concurrency, timeout_ms=body.timeout_ms, deep_probe=body.deep_probe,
    )
    db.add(target)
    await _set_credentials(db, target, body.credential_ids)
    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(409, f"A scan target named {body.name!r} already exists")
    await AuditService.log(db, request, admin, "scan.target_created", resource_type="scan_target",
                           resource_id=str(target.id), detail={"name": target.name, "value": target.value})
    await db.commit()
    await db.refresh(target)
    await scheduler.reload_jobs(db)
    return APIResponse(data=_target_view(target), message="Scan target saved")


@router.patch("/targets/{target_id}", response_model=APIResponse[Dict[str, Any]])
async def update_target(target_id: int, body: TargetUpdate, request: Request,
                        db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    target = await _get_target(db, target_id)
    target_type = body.target_type or target.target_type
    if target_type not in TARGET_TYPES:
        raise HTTPException(400, f"target_type must be one of {', '.join(TARGET_TYPES)}")
    value = body.value if body.value is not None else target.value
    exclusions = body.exclusions if body.exclusions is not None else target.exclusions
    await _expand_or_400(db, target_type, value, exclusions or "")

    target.target_type, target.value, target.exclusions = target_type, value.strip(), (exclusions or "").strip()
    for field in ("enabled", "concurrency", "timeout_ms", "deep_probe"):
        if getattr(body, field) is not None:
            setattr(target, field, getattr(body, field))
    if body.name is not None:
        target.name = body.name.strip()
    if body.clear_schedule:
        target.schedule_cron = None
    elif body.schedule_cron is not None:
        target.schedule_cron = _check_cron(body.schedule_cron)
    if body.methods is not None:
        target.methods = _check_methods(body.methods)
    if body.credential_ids is not None:
        await _set_credentials(db, target, body.credential_ids)
    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(409, f"A scan target named {body.name!r} already exists")
    await AuditService.log(db, request, admin, "scan.target_updated", resource_type="scan_target",
                           resource_id=str(target.id),
                           detail=body.model_dump(exclude_none=True, exclude={"clear_schedule"}))
    await db.commit()
    await db.refresh(target)
    await scheduler.reload_jobs(db)
    return APIResponse(data=_target_view(target), message="Scan target updated")


@router.delete("/targets/{target_id}", response_model=APIResponse[bool])
async def delete_target(target_id: int, request: Request,
                        db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    target = await _get_target(db, target_id)
    if scan_runner.is_running(target_id):
        raise HTTPException(409, "Target is being scanned; cancel the run first")
    await db.delete(target)
    await AuditService.log(db, request, admin, "scan.target_deleted", resource_type="scan_target",
                           resource_id=str(target_id), detail={"name": target.name})
    await db.commit()
    await scheduler.reload_jobs(db)
    return APIResponse(data=True, message="Scan target deleted")


@router.post("/targets/{target_id}/run", response_model=APIResponse[Dict[str, Any]])
async def run_target(target_id: int, request: Request,
                     db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    target = await _get_target(db, target_id)
    try:
        run_id = await scan_runner.start(target_id, trigger="manual", user_id=admin.id)
    except ScanAlreadyRunning:
        raise HTTPException(409, "This target is already being scanned")
    await AuditService.log(db, request, admin, "scan.run_started", resource_type="scan_target",
                           resource_id=str(target_id), detail={"name": target.name, "run_id": run_id})
    await db.commit()
    return APIResponse(data={"run_id": run_id}, message="Scan started")


# ── Runs ────────────────────────────────────────────────────────────────────
def _run_view(r: ScanRun) -> Dict[str, Any]:
    return {
        "id": r.id, "target_id": r.target_id, "target_name": r.target_name,
        "trigger": r.trigger, "status": r.status, "error": r.error,
        "created_at": r.created_at, "started_at": r.started_at, "finished_at": r.finished_at,
        "hosts_total": r.hosts_total, "hosts_alive": r.hosts_alive,
        "hosts_inventoried": r.hosts_inventoried, "hosts_failed": r.hosts_failed,
    }


@router.get("/runs", response_model=APIResponse[List[Dict[str, Any]]])
async def list_runs(target_id: Optional[int] = None, limit: int = Query(50, ge=1, le=500),
                    db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    q = select(ScanRun).order_by(ScanRun.id.desc()).limit(limit)
    if target_id is not None:
        q = q.where(ScanRun.target_id == target_id)
    return APIResponse(data=[_run_view(r) for r in (await db.execute(q)).scalars()])


@router.get("/runs/{run_id}", response_model=APIResponse[Dict[str, Any]])
async def get_run(run_id: int, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    run = await db.get(ScanRun, run_id)
    if run is None:
        raise HTTPException(404, "Scan run not found")
    hosts = (await db.execute(
        select(ScanHostResult).where(ScanHostResult.run_id == run_id).order_by(ScanHostResult.id)
    )).scalars().all()
    cred_names = dict((await db.execute(select(ScanCredential.id, ScanCredential.name))).all())
    return APIResponse(data={**_run_view(run), "hosts": [
        {"id": h.id, "ip": h.ip, "hostname": h.hostname, "status": h.status, "method": h.method,
         "credential_id": h.credential_id, "credential_name": cred_names.get(h.credential_id),
         "device_id": h.device_id, "error_code": h.error_code,
         "error_message": h.error_message, "duration_ms": h.duration_ms}
        for h in hosts
    ]})


@router.post("/runs/{run_id}/cancel", response_model=APIResponse[bool])
async def cancel_run(run_id: int, request: Request,
                     db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    if not scan_runner.cancel(run_id):
        raise HTTPException(409, "Run is not active")
    await AuditService.log(db, request, admin, "scan.run_cancelled", resource_type="scan_run",
                           resource_id=str(run_id))
    await db.commit()
    return APIResponse(data=True, message="Cancelling")


# ── Credential test ─────────────────────────────────────────────────────────
class CredentialTestIn(BaseModel):
    host: str = Field(min_length=1, max_length=255)


async def _host_ip(host: str) -> str:
    import ipaddress
    import socket
    try:
        return str(ipaddress.IPv4Address(host.strip()))
    except ValueError:
        try:
            infos = await asyncio.to_thread(socket.getaddrinfo, host.strip(), None, socket.AF_INET)
        except socket.gaierror:
            raise HTTPException(400, f"Cannot resolve {host!r}")
        return infos[0][4][0]


@router.post("/credentials/{cred_id}/test", response_model=APIResponse[Dict[str, Any]])
async def test_scan_credential(cred_id: int, body: CredentialTestIn, request: Request,
                               db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    """Sign in to one host with one credential and run a harmless query.

    Only allowed for hosts inside an enabled scan target this credential is
    assigned to — the same scope scans use — so it can't be pointed at
    arbitrary machines."""
    cred = await _get_credential(db, cred_id)
    ip = await _host_ip(body.host)
    targets = (await db.execute(
        select(ScanTarget).join(ScanTargetCredential, ScanTargetCredential.target_id == ScanTarget.id)
        .where(ScanTargetCredential.credential_id == cred_id, ScanTarget.enabled == True)  # noqa: E712
    )).scalars().all()
    in_scope = False
    for t in targets:
        try:
            if ip in await resolve(db, t.target_type, t.value, t.exclusions or ""):
                in_scope = True
                break
        except TargetSpecError:
            continue
    if not in_scope:
        raise HTTPException(400, f"{ip} is not inside an enabled scan target that uses this credential. "
                                 "Assign the credential to a target covering this host first.")

    try:
        info = await test_credential(ip, CredentialInput.from_model(cred), HostKeyStore(scan_runner._sessions()))
        result = {"ok": True, "host": ip, **info}
    except CollectorError as exc:
        result = {"ok": False, "host": ip, "error_code": exc.code, "message": exc.message}
    await AuditService.log(db, request, admin, "scan.credential_tested", resource_type="scan_credential",
                           resource_id=str(cred_id), detail={"host": ip, "ok": result["ok"],
                                                             "error_code": result.get("error_code")})
    await db.commit()
    return APIResponse(data=result, message="Credential works" if result["ok"] else "Credential test failed")


# ── Trusted SSH host keys ───────────────────────────────────────────────────
@router.get("/ssh-host-keys", response_model=APIResponse[List[Dict[str, Any]]])
async def list_ssh_host_keys(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    rows = (await db.execute(select(SshHostKey).order_by(SshHostKey.host, SshHostKey.port))).scalars().all()
    return APIResponse(data=[{"id": k.id, "host": k.host, "port": k.port, "key_type": k.key_type,
                              "fingerprint": k.fingerprint, "first_seen": k.first_seen,
                              "last_seen": k.last_seen} for k in rows])


@router.delete("/ssh-host-keys/{key_id}", response_model=APIResponse[bool])
async def forget_ssh_host_key(key_id: int, request: Request,
                              db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    """Forget a trusted key (e.g. the host was rebuilt). The next scan trusts
    whatever key the host then presents."""
    key = await db.get(SshHostKey, key_id)
    if key is None:
        raise HTTPException(404, "Host key not found")
    await db.delete(key)
    await AuditService.log(db, request, admin, "scan.ssh_host_key_forgotten", resource_type="ssh_host_key",
                           resource_id=str(key_id),
                           detail={"host": key.host, "port": key.port, "fingerprint": key.fingerprint})
    await db.commit()
    return APIResponse(data=True, message="Host key forgotten")
