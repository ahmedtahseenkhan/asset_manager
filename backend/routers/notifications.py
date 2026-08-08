from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.licensing.enforcement import require_module
from backend.middleware.auth import require_admin
from backend.models.notification import ALERT_RULE_TYPES, AlertRule, NotificationLog, SmtpSettings
from backend.models.user import User
from backend.schemas.common import APIResponse
from backend.services.audit_service import AuditService
from backend.services.notification_service import NotificationService

router = APIRouter(prefix="/notifications", tags=["Notifications"],
                   dependencies=[require_module("notifications")])


class SmtpIn(BaseModel):
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=25, ge=1, le=65535)
    username: Optional[str] = None
    password: Optional[str] = None      # write-only; blank = keep current
    from_address: str = Field(min_length=3, max_length=255)
    use_starttls: bool = False
    enabled: bool = True


class SmtpTestIn(BaseModel):
    recipient: str = Field(min_length=3, max_length=255)


class RuleIn(BaseModel):
    days_before: int = Field(ge=1, le=365)
    recipients: List[str] = Field(default_factory=list, max_length=50)
    enabled: bool

    @field_validator("recipients")
    @classmethod
    def emails_plausible(cls, v: List[str]) -> List[str]:
        for addr in v:
            if "@" not in addr or len(addr) > 255:
                raise ValueError(f"Invalid email address: {addr!r}")
        return v


def _smtp_out(s: Optional[SmtpSettings]) -> Dict[str, Any]:
    if not s:
        return {"configured": False}
    return {
        "configured": True,
        "host": s.host, "port": s.port, "username": s.username,
        "has_password": s.password is not None,
        "from_address": s.from_address, "use_starttls": s.use_starttls,
        "enabled": s.enabled,
    }


def _rule_out(r: AlertRule) -> Dict[str, Any]:
    return {"rule_type": r.rule_type, "days_before": r.days_before,
            "recipients": r.recipients, "enabled": r.enabled}


@router.get("/smtp", response_model=APIResponse[Dict[str, Any]])
async def get_smtp(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    return APIResponse(data=_smtp_out(await NotificationService.get_smtp(db)))


@router.put("/smtp", response_model=APIResponse[Dict[str, Any]])
async def save_smtp(
    body: SmtpIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    smtp = await NotificationService.get_smtp(db)
    if not smtp:
        smtp = SmtpSettings(id=1)
        db.add(smtp)
    smtp.host = body.host
    smtp.port = body.port
    smtp.username = body.username or None
    if body.password:                      # blank keeps the stored secret
        smtp.password = body.password
    smtp.from_address = body.from_address
    smtp.use_starttls = body.use_starttls
    smtp.enabled = body.enabled
    await AuditService.log(db, request, admin, "notifications.smtp_saved",
                           resource_type="smtp",
                           detail={"host": body.host, "port": body.port})
    await db.commit()
    return APIResponse(data=_smtp_out(smtp), message="SMTP settings saved")


@router.post("/smtp/test", response_model=APIResponse[bool])
async def test_smtp(
    body: SmtpTestIn,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    try:
        await NotificationService.send_email(
            db,
            "[IT Asset Manager] SMTP test",
            f"SMTP relay test triggered by {admin.username} at {datetime.now():%Y-%m-%d %H:%M}.",
            [body.recipient],
        )
    except Exception as exc:
        raise HTTPException(400, f"Test send failed: {exc}")
    return APIResponse(data=True, message=f"Test email sent to {body.recipient}")


@router.get("/rules", response_model=APIResponse[List[Dict[str, Any]]])
async def list_rules(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    rules = await NotificationService.ensure_default_rules(db)
    return APIResponse(data=[_rule_out(r) for r in rules])


@router.patch("/rules/{rule_type}", response_model=APIResponse[Dict[str, Any]])
async def update_rule(
    rule_type: str,
    body: RuleIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if rule_type not in ALERT_RULE_TYPES:
        raise HTTPException(404, f"Unknown rule type. Valid: {ALERT_RULE_TYPES}")
    await NotificationService.ensure_default_rules(db)
    rule = (await db.execute(
        select(AlertRule).where(AlertRule.rule_type == rule_type)
    )).scalars().first()
    rule.days_before = body.days_before
    rule.recipients = body.recipients
    rule.enabled = body.enabled
    await AuditService.log(db, request, admin, "notifications.rule_updated",
                           resource_type="alert_rule", resource_id=rule_type,
                           detail={"enabled": body.enabled, "days_before": body.days_before,
                                   "recipient_count": len(body.recipients)})
    await db.commit()
    return APIResponse(data=_rule_out(rule), message="Rule updated")


@router.post("/run", response_model=APIResponse[Dict[str, str]])
async def run_now(
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    summary = await NotificationService.run_checks(db, force=True)
    await AuditService.log(db, request, admin, "notifications.manual_run",
                           resource_type="notifications", detail=summary)
    await db.commit()
    return APIResponse(data=summary, message="Notification checks completed")


@router.get("/log", response_model=APIResponse[List[Dict[str, Any]]])
async def get_log(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    rows = (await db.execute(
        select(NotificationLog).order_by(NotificationLog.created_at.desc())
        .limit(min(max(1, limit), 200))
    )).scalars().all()
    return APIResponse(data=[
        {"id": r.id, "rule_type": r.rule_type, "subject": r.subject,
         "recipients": r.recipients, "item_count": r.item_count,
         "status": r.status, "error": r.error, "created_at": r.created_at}
        for r in rows
    ])
