"""
Expiry alerting over an on-prem SMTP relay. No external service dependency:
plain smtplib against the configured relay, run in a worker thread.

A daily scheduler job calls run_checks(); each enabled rule sends at most one
email per day (deduped via notification_log), and only when items match.
"""
from __future__ import annotations

import asyncio
import logging
import smtplib
from datetime import date, datetime, time, timedelta, timezone
from email.message import EmailMessage
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.licensing.state import license_manager
from backend.models.asset import Asset
from backend.models.contract import Contract
from backend.models.entitlement import Entitlement
from backend.models.notification import ALERT_RULE_TYPES, AlertRule, NotificationLog, SmtpSettings

logger = logging.getLogger(__name__)


def _send_sync(smtp: SmtpSettings, subject: str, body: str, recipients: List[str]) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp.from_address
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)

    with smtplib.SMTP(smtp.host, smtp.port, timeout=15) as client:
        if smtp.use_starttls:
            client.starttls()
        if smtp.username:
            client.login(smtp.username, smtp.password or "")
        client.send_message(msg)


class NotificationService:
    @staticmethod
    async def get_smtp(db: AsyncSession) -> Optional[SmtpSettings]:
        return (await db.execute(select(SmtpSettings).where(SmtpSettings.id == 1))).scalars().first()

    @staticmethod
    async def ensure_default_rules(db: AsyncSession) -> List[AlertRule]:
        existing = {r.rule_type: r for r in (await db.execute(select(AlertRule))).scalars().all()}
        changed = False
        for rule_type in ALERT_RULE_TYPES:
            if rule_type not in existing:
                rule = AlertRule(rule_type=rule_type, days_before=30, recipients=[], enabled=False)
                db.add(rule)
                existing[rule_type] = rule
                changed = True
        if changed:
            await db.commit()
        return [existing[t] for t in ALERT_RULE_TYPES]

    @staticmethod
    async def send_email(db: AsyncSession, subject: str, body: str, recipients: List[str]) -> None:
        """Raises on failure; caller decides whether to log."""
        smtp = await NotificationService.get_smtp(db)
        if not smtp or not smtp.enabled:
            raise RuntimeError("SMTP relay is not configured or disabled")
        if not recipients:
            raise RuntimeError("No recipients configured")
        await asyncio.to_thread(_send_sync, smtp, subject, body, recipients)

    # ── item collectors, one per rule type ────────────────────────────────

    @staticmethod
    async def _contract_items(db: AsyncSession, _days: int) -> List[str]:
        today = date.today()
        rows = (await db.execute(
            select(Contract).where(Contract.end_date.isnot(None))
        )).scalars().all()
        items = []
        for c in rows:
            days_left = (c.end_date - today).days
            if days_left <= (c.notice_days or 30):
                status = f"expired {-days_left}d ago" if days_left < 0 else f"{days_left}d left"
                items.append(f"- {c.name} ({c.contract_type}, {c.vendor or 'n/a'}): "
                             f"ends {c.end_date} — {status}"
                             f"{' [auto-renews]' if c.auto_renews else ''}")
        return items

    @staticmethod
    async def _warranty_items(db: AsyncSession, days: int) -> List[str]:
        today = date.today()
        cutoff = today + timedelta(days=days)
        rows = (await db.execute(
            select(Asset).where(Asset.warranty_end.isnot(None), Asset.warranty_end <= cutoff)
        )).scalars().all()
        return [
            f"- {a.asset_tag} {a.name}: warranty ends {a.warranty_end} "
            f"({'expired' if a.warranty_end < today else f'{(a.warranty_end - today).days}d left'})"
            for a in rows
        ]

    @staticmethod
    async def _entitlement_items(db: AsyncSession, days: int) -> List[str]:
        today = date.today()
        cutoff = today + timedelta(days=days)
        rows = (await db.execute(
            select(Entitlement).where(Entitlement.expires_on.isnot(None),
                                      Entitlement.expires_on <= cutoff)
        )).scalars().all()
        return [
            f"- {e.product} ({e.vendor or 'n/a'}): expires {e.expires_on} "
            f"({'expired' if e.expires_on < today else f'{(e.expires_on - today).days}d left'})"
            for e in rows
        ]

    @staticmethod
    async def _license_items(_db: AsyncSession, days: int) -> List[str]:
        info = license_manager.current
        if not info.claims:
            return [f"- Application license problem: {info.status.value} — {info.reason}"]
        try:
            expires = date.fromisoformat(info.claims["expires_at"])
        except (KeyError, ValueError):
            return [f"- Application license problem: {info.status.value} — {info.reason}"]
        days_left = (expires - date.today()).days
        if info.status.value != "valid" or days_left <= days:
            state = f"status={info.status.value}" + (f", {info.reason}" if info.reason else "")
            return [f"- Application license expires {expires} ({days_left}d left; {state})"]
        return []

    _COLLECTORS = {
        "contract_expiry": ("Contract renewals due", _contract_items),
        "warranty_expiry": ("Asset warranties expiring", _warranty_items),
        "entitlement_expiry": ("Software licenses expiring", _entitlement_items),
        "license_expiry": ("Application license expiring", _license_items),
    }

    @staticmethod
    async def _already_sent_today(db: AsyncSession, rule_type: str) -> bool:
        midnight = datetime.combine(date.today(), time.min, tzinfo=timezone.utc)
        row = (await db.execute(
            select(NotificationLog.id).where(
                NotificationLog.rule_type == rule_type,
                NotificationLog.status == "sent",
                NotificationLog.created_at >= midnight,
            ).limit(1)
        )).first()
        return row is not None

    @staticmethod
    async def run_checks(db: AsyncSession, force: bool = False) -> dict:
        """Evaluate every enabled rule; send one digest email per rule with matches."""
        rules = await NotificationService.ensure_default_rules(db)
        summary = {}
        for rule in rules:
            if not rule.enabled:
                summary[rule.rule_type] = "disabled"
                continue
            if not force and await NotificationService._already_sent_today(db, rule.rule_type):
                summary[rule.rule_type] = "already sent today"
                continue

            title, collector = NotificationService._COLLECTORS[rule.rule_type]
            items = await collector.__func__(db, rule.days_before)
            if not items:
                summary[rule.rule_type] = "no matches"
                continue

            subject = f"[IT Asset Manager] {title}: {len(items)} item(s)"
            body = (f"{title} (threshold: {rule.days_before} days)\n"
                    f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC\n\n"
                    + "\n".join(items)
                    + "\n\nThis is an automated alert from your on-premises IT Asset Manager.")
            try:
                await NotificationService.send_email(db, subject, body, rule.recipients)
                status, error = "sent", None
                summary[rule.rule_type] = f"sent ({len(items)} items)"
            except Exception as exc:  # log failures, keep processing other rules
                status, error = "failed", str(exc)
                summary[rule.rule_type] = f"failed: {exc}"
                logger.error("Alert %s failed: %s", rule.rule_type, exc)

            db.add(NotificationLog(rule_type=rule.rule_type, subject=subject,
                                   recipients=rule.recipients, item_count=len(items),
                                   status=status, error=error))
            await db.commit()
        return summary
