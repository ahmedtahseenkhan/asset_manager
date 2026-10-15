from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from backend.database import Base


class ScanTarget(Base):
    """A set of addresses scanned together, on a schedule, with an ordered
    list of credentials to try."""
    __tablename__ = "scan_targets"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    target_type = Column(String(16), nullable=False)        # cidr | range | hosts
    value = Column(Text, nullable=False)
    exclusions = Column(Text, nullable=False, default="")
    schedule_cron = Column(String(100))                     # NULL = manual only
    methods = Column(JSON, nullable=False, default=list)    # e.g. ["ping", "winrm", "ssh"]
    concurrency = Column(Integer, nullable=False, default=32)
    timeout_ms = Column(Integer, nullable=False, default=1000)
    deep_probe = Column(Boolean, nullable=False, default=True)
    last_run_at = Column(DateTime(timezone=True))
    last_status = Column(String(32))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    credential_links = relationship(
        "ScanTargetCredential", order_by="ScanTargetCredential.position",
        cascade="all, delete-orphan", lazy="selectin",
    )


class ScanTargetCredential(Base):
    """Ordered credential list per target: tried in `position` order."""
    __tablename__ = "scan_target_credentials"

    id = Column(Integer, primary_key=True)
    target_id = Column(Integer, ForeignKey("scan_targets.id", ondelete="CASCADE"), nullable=False, index=True)
    credential_id = Column(Integer, ForeignKey("scan_credentials.id", ondelete="CASCADE"), nullable=False, index=True)
    position = Column(Integer, nullable=False, default=0)

    credential = relationship("ScanCredential", lazy="selectin")

    __table_args__ = (UniqueConstraint("target_id", "credential_id", name="uq_target_credential"),)
