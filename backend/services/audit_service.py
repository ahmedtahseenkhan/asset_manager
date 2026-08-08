"""
Thin helper for writing audit log entries.

Usage inside a route handler:
    await AuditService.log(db, request, user, "connector.config_saved",
                           resource_type="connector", resource_id="crowdstrike",
                           detail={"enabled": True})

Entries form a tamper-evident hash chain:
    row_hash = sha256(prev_hash ‖ canonical_json(row_fields))
A Postgres advisory lock serialises writers so the chain never forks.
Verify with AuditService.verify_chain (exposed at GET /api/admin/audit-verify).
"""
from __future__ import annotations
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.audit_log import AuditLog
from backend.models.user import User

logger = logging.getLogger(__name__)

# Arbitrary but fixed key for pg_advisory_xact_lock (released at tx end)
_CHAIN_LOCK_KEY = 815551

_GENESIS = "0" * 64


def _canonical(entry: AuditLog) -> str:
    """Stable serialisation of the hashed fields. created_at must be set client-side."""
    return json.dumps({
        "user_id": entry.user_id,
        "username": entry.username,
        "action": entry.action,
        "resource_type": entry.resource_type,
        "resource_id": entry.resource_id,
        "detail": entry.detail,
        "ip_address": entry.ip_address,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }, sort_keys=True, separators=(",", ":"))


def _compute_hash(prev_hash: str, entry: AuditLog) -> str:
    return hashlib.sha256((prev_hash + _canonical(entry)).encode()).hexdigest()


class AuditService:
    @staticmethod
    async def log(
        db: AsyncSession,
        request: Request | None,
        user: User | None,
        action: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        detail: Dict[str, Any] | None = None,
    ) -> None:
        try:
            ip = None
            if request:
                forwarded = request.headers.get("X-Forwarded-For")
                ip = forwarded.split(",")[0].strip() if forwarded else (
                    request.client.host if request.client else None
                )

            entry = AuditLog(
                user_id=user.id if user else None,
                username=user.username if user else None,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                detail=detail,
                ip_address=ip,
                created_at=datetime.now(timezone.utc),   # client-side so it can be hashed
            )

            # Serialise chain writers until this transaction commits.
            await db.execute(text("SELECT pg_advisory_xact_lock(:k)"),
                             {"k": _CHAIN_LOCK_KEY})
            last = (await db.execute(
                select(AuditLog.row_hash).order_by(AuditLog.id.desc()).limit(1)
            )).scalar()
            entry.prev_hash = last or _GENESIS
            entry.row_hash = _compute_hash(entry.prev_hash, entry)

            db.add(entry)
            await db.commit()
        except Exception as exc:
            # Audit log must never crash the caller
            logger.error(f"AuditService.log failed: {exc}", exc_info=True)

    @staticmethod
    async def verify_chain(db: AsyncSession) -> Dict[str, Any]:
        """Recompute every hash in order; report the first break, if any."""
        rows = (await db.execute(
            select(AuditLog).order_by(AuditLog.id.asc())
        )).scalars().all()

        prev = _GENESIS
        legacy = 0   # rows written before hashing existed (both hash columns null)
        for row in rows:
            if row.row_hash is None and row.prev_hash is None:
                legacy += 1
                continue
            if row.prev_hash != prev or row.row_hash != _compute_hash(row.prev_hash, row):
                return {
                    "intact": False,
                    "checked": len(rows),
                    "legacy_unhashed": legacy,
                    "first_broken_id": row.id,
                    "detail": f"Hash mismatch at audit entry {row.id} "
                              f"({row.action} @ {row.created_at})",
                }
            prev = row.row_hash
        return {"intact": True, "checked": len(rows), "legacy_unhashed": legacy,
                "first_broken_id": None, "detail": "Audit chain verified"}
