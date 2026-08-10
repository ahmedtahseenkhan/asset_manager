from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey
from sqlalchemy.sql import func
from backend.database import Base


class AgentToken(Base):
    """Enrollment token an agent presents (X-Agent-Token) to POST inventory."""
    __tablename__ = "agent_tokens"

    id = Column(Integer, primary_key=True)
    token = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)          # label, e.g. "laptops-2026"
    active = Column(Boolean, nullable=False, default=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    reports_count = Column(Integer, nullable=False, default=0)
