from sqlalchemy import Column, Integer, String, DateTime, JSON, ForeignKey
from sqlalchemy.sql import func
from backend.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id            = Column(Integer, primary_key=True, index=True)
    user_id       = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    username      = Column(String(255), nullable=True)           # denormalised — survives user deletion
    action        = Column(String(100), nullable=False, index=True)
    resource_type = Column(String(100), nullable=True)           # "connector", "user", "sync", "auth"
    resource_id   = Column(String(255), nullable=True)           # name / id of the affected resource
    detail        = Column(JSON, nullable=True)                  # arbitrary extra context
    ip_address    = Column(String(64),  nullable=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
