from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Integer,
    String,
    Text,
)
from sqlalchemy.sql import func

from backend.database import Base
from backend.utils.encryption import EncryptedString

ALERT_RULE_TYPES = [
    "contract_expiry",      # per-contract notice_days window
    "warranty_expiry",      # assets: warranty_end within days_before
    "entitlement_expiry",   # entitlements: expires_on within days_before
    "license_expiry",       # this application's own license
    "security_changes",     # risky device changes (new local admin, AV/encryption off, …)
]


class SmtpSettings(Base):
    """Single-row table (id=1): on-prem SMTP relay used for all outgoing mail."""
    __tablename__ = "smtp_settings"

    id = Column(Integer, primary_key=True, default=1)
    host = Column(String(255), nullable=False)
    port = Column(Integer, nullable=False, default=25)
    username = Column(String(255), nullable=True)
    password = Column(EncryptedString(), nullable=True)   # encrypted at rest
    from_address = Column(String(255), nullable=False)
    use_starttls = Column(Boolean, nullable=False, default=False)
    enabled = Column(Boolean, nullable=False, default=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AlertRule(Base):
    """One row per alert type; recipients + threshold are admin-configurable."""
    __tablename__ = "alert_rules"

    id = Column(Integer, primary_key=True)
    rule_type = Column(String(32), nullable=False, unique=True)
    days_before = Column(Integer, nullable=False, default=30)
    recipients = Column(JSON, nullable=False, default=list)   # list[str] email addresses
    enabled = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(f"rule_type IN {tuple(ALERT_RULE_TYPES)}", name="ck_alert_rules_type"),
    )


class NotificationLog(Base):
    """Append-only history of alert emails (sent or failed)."""
    __tablename__ = "notification_log"

    id = Column(Integer, primary_key=True)
    rule_type = Column(String(32), nullable=False, index=True)
    subject = Column(String(500), nullable=False)
    recipients = Column(JSON, nullable=False, default=list)
    item_count = Column(Integer, nullable=False, default=0)
    status = Column(String(16), nullable=False)               # sent | failed
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
