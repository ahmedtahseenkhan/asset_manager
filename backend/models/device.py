from sqlalchemy import Column, Index, Integer, String, DateTime, JSON
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from backend.database import Base

class Device(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, index=True)
    hostname = Column(String(255), index=True)
    fqdn = Column(String(255), index=True, unique=True)
    ip_addresses = Column(JSON, default=list)
    mac_addresses = Column(JSON, default=list)
    os_name = Column(String(255), index=True)
    os_version = Column(String(255))
    domain = Column(String(255))
    ou = Column(String(1024))
    first_seen = Column(DateTime(timezone=True), server_default=func.now())
    last_seen = Column(DateTime(timezone=True), index=True)
    status = Column(String(50), default="active", index=True)  # active, inactive, retired

    # Relationships
    sources = relationship("DeviceSource", back_populates="device", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_devices_hostname_status", "hostname", "status"),
    )
