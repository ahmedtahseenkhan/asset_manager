"""
Thin helper for writing audit log entries.

Usage inside a route handler:
    await AuditService.log(db, request, user, "connector.config_saved",
                           resource_type="connector", resource_id="crowdstrike",
                           detail={"enabled": True})
"""
from __future__ import annotations
import logging
from typing import Any, Dict, Optional

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.audit_log import AuditLog
from backend.models.user import User

logger = logging.getLogger(__name__)


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
            )
            db.add(entry)
            await db.commit()
        except Exception as exc:
            # Audit log must never crash the caller
            logger.error(f"AuditService.log failed: {exc}", exc_info=True)
