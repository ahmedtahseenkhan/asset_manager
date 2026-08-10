from sqlalchemy import (
    Column, Integer, String, Date, DateTime, ForeignKey, UniqueConstraint, Index,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from backend.database import Base


class InstalledSoftware(Base):
    """A software title installed on a device (reported by the agent)."""
    __tablename__ = "installed_software"

    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"),
                       nullable=False, index=True)
    name = Column(String(500), nullable=False, index=True)
    normalized_name = Column(String(500), index=True)   # for SAM matching
    version = Column(String(128))
    publisher = Column(String(255))
    install_date = Column(Date)
    last_seen = Column(DateTime(timezone=True), server_default=func.now())

    device = relationship("Device")

    __table_args__ = (
        UniqueConstraint("device_id", "name", "version", name="uq_software_device_title"),
        Index("ix_software_normalized", "normalized_name"),
    )
