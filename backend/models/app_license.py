from sqlalchemy import Column, Integer, String, DateTime, JSON, ForeignKey
from sqlalchemy.sql import func
from backend.database import Base


class AppLicenseActivation(Base):
    """History of license files applied to this installation (audit trail)."""
    __tablename__ = "app_license_activations"

    id = Column(Integer, primary_key=True)
    license_id = Column(String(64), nullable=False, index=True)
    payload = Column(JSON, nullable=False)          # decoded claims, for display
    file_sha256 = Column(String(64), nullable=False)
    activated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    activated_at = Column(DateTime(timezone=True), server_default=func.now())
