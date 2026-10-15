from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.sql import func

from backend.database import Base

RUN_STATUSES = ("queued", "running", "completed", "failed", "cancelled")


class ScanRun(Base):
    """One execution of a scan target (Lansweeper's scan queue entry)."""
    __tablename__ = "scan_runs"

    id = Column(Integer, primary_key=True)
    target_id = Column(Integer, ForeignKey("scan_targets.id", ondelete="SET NULL"), index=True)
    target_name = Column(String(255), nullable=False)       # kept if the target is deleted
    trigger = Column(String(16), nullable=False)            # manual | schedule
    status = Column(String(16), nullable=False, default="queued", index=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    hosts_total = Column(Integer, nullable=False, default=0)
    hosts_alive = Column(Integer, nullable=False, default=0)
    hosts_inventoried = Column(Integer, nullable=False, default=0)
    hosts_failed = Column(Integer, nullable=False, default=0)
    error = Column(Text)


class ScanHostResult(Base):
    """Per-host outcome within a run. Only responsive or failed hosts are
    stored; silent addresses are counted on the run, not given rows."""
    __tablename__ = "scan_host_results"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("scan_runs.id", ondelete="CASCADE"), nullable=False)
    ip = Column(String(45), nullable=False)
    hostname = Column(String(255))
    status = Column(String(16), nullable=False)              # alive | inventoried | failed
    method = Column(String(16))                              # ping | winrm | wmi | ssh | snmp
    credential_id = Column(Integer, ForeignKey("scan_credentials.id", ondelete="SET NULL"))
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="SET NULL"))
    error_code = Column(String(64))
    error_message = Column(Text)
    duration_ms = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_scan_host_results_run_status", "run_id", "status"),)
