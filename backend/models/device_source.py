from sqlalchemy import Column, Index, Integer, String, DateTime, JSON, ForeignKey, UniqueConstraint
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from backend.database import Base

class DeviceSource(Base):
    """Stores the raw data from each connector for a specific device."""
    __tablename__ = "device_sources"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    source_name = Column(String(100), nullable=False)
    source_uid = Column(String(255), nullable=True)
    raw_data = Column(JSON, default=dict, nullable=False)
    last_synced = Column(DateTime(timezone=True), server_default=func.now())

    device = relationship("Device", back_populates="sources")

    __table_args__ = (
        # UniqueConstraint already creates an index on (device_id, source_name);
        # no need for a separate Index on the same columns.
        UniqueConstraint("device_id", "source_name", name="uq_device_source"),
        Index("ix_device_sources_source_name", "source_name"),
        Index("ix_device_sources_last_synced", "source_name", "last_synced"),
    )
