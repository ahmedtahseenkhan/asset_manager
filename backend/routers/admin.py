"""
Admin-only endpoints:
  GET  /api/admin/audit-logs          — paginated audit trail
  GET  /api/admin/users               — list all users
  PATCH /api/admin/users/{id}/status  — activate / deactivate a user
  POST /api/admin/retention/run       — run retention policy immediately
"""
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from typing import List, Optional
from datetime import datetime

from backend.database import get_db
from backend.middleware.auth import require_admin
from backend.models.audit_log import AuditLog
from backend.models.user import User
from backend.schemas.common import APIResponse
from backend.services.audit_service import AuditService
from backend.services.retention_service import RetentionService

router = APIRouter(prefix="/admin", tags=["Admin"])


# ── Audit log ────────────────────────────────────────────────────────────────

@router.get("/audit-logs", response_model=APIResponse[dict])
async def list_audit_logs(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    action: Optional[str] = None,
    username: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
):
    query = select(AuditLog).order_by(AuditLog.created_at.desc())

    if action:
        query = query.where(AuditLog.action.ilike(f"%{action}%"))
    if username:
        query = query.where(AuditLog.username.ilike(f"%{username}%"))

    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    result = await db.execute(query.offset((page - 1) * size).limit(size))
    entries = result.scalars().all()

    return APIResponse(data={
        "items": [
            {
                "id":            e.id,
                "username":      e.username,
                "action":        e.action,
                "resource_type": e.resource_type,
                "resource_id":   e.resource_id,
                "detail":        e.detail,
                "ip_address":    e.ip_address,
                "created_at":    e.created_at.isoformat() if e.created_at else None,
            }
            for e in entries
        ],
        "total": total or 0,
        "page":  page,
        "size":  size,
    })


# ── User management ──────────────────────────────────────────────────────────

@router.get("/users", response_model=APIResponse[List[dict]])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
):
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()
    return APIResponse(data=[
        {
            "id":         u.id,
            "username":   u.username,
            "email":      u.email,
            "role":       u.role,
            "is_active":  u.is_active,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in users
    ])


@router.patch("/users/{user_id}/status", response_model=APIResponse[dict])
async def set_user_status(
    user_id: int,
    active: bool,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin=Depends(require_admin),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(404, "User not found")
    if user.id == admin.id:
        raise HTTPException(400, "Cannot change your own active status")

    user.is_active = active
    await db.commit()

    action = "user.activated" if active else "user.deactivated"
    await AuditService.log(db, request, admin, action,
                           resource_type="user", resource_id=user.username,
                           detail={"target_user_id": user.id})
    return APIResponse(data={"id": user.id, "username": user.username, "is_active": user.is_active},
                       message=f"User {'activated' if active else 'deactivated'}")


# ── Audit chain integrity ─────────────────────────────────────────────────────

@router.get("/audit-verify", response_model=APIResponse[dict])
async def verify_audit_chain(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Recompute the audit-log hash chain and report tampering, if any."""
    return APIResponse(data=await AuditService.verify_chain(db))


# ── Retention ─────────────────────────────────────────────────────────────────

@router.post("/retention/run", response_model=APIResponse[dict])
async def run_retention(
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
):
    result = await RetentionService.run(db)
    return APIResponse(data=result, message="Retention policy executed")
