from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.sql import func

from backend.database import Base


class VmPlacement(Base):
    """Which hypervisor host a virtual machine runs on, with its allocation.
    One row per VM device; rewritten each time the host reports its guests."""
    __tablename__ = "vm_placements"

    id = Column(Integer, primary_key=True)
    vm_device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, unique=True)
    host_device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True)
    platform = Column(String(16), nullable=False)        # vmware | hyperv
    vm_name = Column(String(255), nullable=False)
    instance_id = Column(String(64))
    power_state = Column(String(16), index=True)
    guest_os = Column(String(255))
    vcpus = Column(Integer)
    memory_gb = Column(Float)
    disk_gb = Column(Float)
    tools_status = Column(String(64))
    cluster = Column(String(255), index=True)
    datacenter = Column(String(255))
    last_seen = Column(DateTime(timezone=True), server_default=func.now())
