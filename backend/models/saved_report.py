from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from backend.database import Base


class SavedReport(Base):
    """A report definition (see backend.reporting) saved by a user, optionally
    shared, pinned to the dashboard, and emailed on a schedule."""
    __tablename__ = "saved_reports"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    definition = Column(JSON, nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    shared = Column(Boolean, nullable=False, default=False)     # visible to every user
    pinned = Column(Boolean, nullable=False, default=False)     # shown on the dashboard

    # Scheduled email (admin-managed)
    schedule_cron = Column(String(100))
    recipients = Column(JSON, nullable=False, default=list)
    export_format = Column(String(8), nullable=False, default="xlsx")   # xlsx | csv
    last_sent_at = Column(DateTime(timezone=True))
    last_status = Column(String(255))

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
