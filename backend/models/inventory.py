"""
Per-device inventory collected by agents and credentialed scans.

`device_inventory` is a 1:1 summary (hardware, OS, security posture flags) that
reports and dashboards can filter on directly. List-shaped sections get their
own table so they can be queried ("devices missing KB…", "local admins").
`device_changes` is the change history written by InventoryService.
"""
from sqlalchemy import (
    JSON, Boolean, Column, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from backend.database import Base


def _device_fk():
    return Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True)


class DeviceInventory(Base):
    __tablename__ = "device_inventory"

    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, unique=True)
    source = Column(String(32))                    # collector of the latest report
    collector_version = Column(String(32))
    collected_at = Column(DateTime(timezone=True), index=True)
    # Sections ever collected for this device. A section's first report is a
    # baseline: stored, but not turned into hundreds of "added" changes.
    sections_collected = Column(JSON, nullable=False, default=list)

    # Hardware
    manufacturer = Column(String(255))
    model = Column(String(255))
    chassis_type = Column(String(32))
    is_virtual = Column(Boolean)
    cpu = Column(String(255))
    cpu_cores = Column(Integer)
    cpu_logical = Column(Integer)
    ram_gb = Column(Float)
    disk_gb = Column(Float)
    bios_vendor = Column(String(255))
    bios_version = Column(String(255))
    bios_date = Column(String(32))
    motherboard = Column(String(255))

    # OS / session
    os_name = Column(String(255))
    os_version = Column(String(255))
    os_build = Column(String(64))
    architecture = Column(String(32))
    last_boot = Column(DateTime(timezone=True))
    logged_in_user = Column(String(255))
    pending_reboot = Column(Boolean)

    # Security posture (None = unknown / not collected)
    tpm_present = Column(Boolean)
    tpm_ready = Column(Boolean)
    secure_boot = Column(Boolean)
    firewall_profiles = Column(JSON)               # [{"profile": "domain", "enabled": true}, …]
    firewall_ok = Column(Boolean, index=True)      # every profile enabled
    antivirus_ok = Column(Boolean, index=True)     # some product enabled (and up to date where known)
    disk_encrypted = Column(Boolean, index=True)   # every fixed volume protected
    local_admin_count = Column(Integer)


class DevicePatch(Base):
    __tablename__ = "device_patches"

    id = Column(Integer, primary_key=True)
    device_id = _device_fk()
    patch_id = Column(String(128), nullable=False, index=True)    # KB5034441
    description = Column(String(255))
    installed_on = Column(Date)
    first_seen = Column(DateTime(timezone=True), server_default=func.now())
    last_seen = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("device_id", "patch_id", name="uq_device_patch"),)


class DeviceService(Base):
    __tablename__ = "device_services"

    id = Column(Integer, primary_key=True)
    device_id = _device_fk()
    name = Column(String(255), nullable=False, index=True)
    display_name = Column(String(255))
    state = Column(String(32))
    start_mode = Column(String(32))
    account = Column(String(255))
    last_seen = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("device_id", "name", name="uq_device_service"),)


class DeviceLocalAccount(Base):
    __tablename__ = "device_local_accounts"

    id = Column(Integer, primary_key=True)
    device_id = _device_fk()
    name = Column(String(255), nullable=False)
    enabled = Column(Boolean)
    is_admin = Column(Boolean, index=True)
    last_logon = Column(DateTime(timezone=True))
    last_seen = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("device_id", "name", name="uq_device_account"),)


class DeviceAntivirus(Base):
    __tablename__ = "device_antivirus"

    id = Column(Integer, primary_key=True)
    device_id = _device_fk()
    name = Column(String(255), nullable=False)
    enabled = Column(Boolean)
    up_to_date = Column(Boolean)
    definitions_date = Column(Date)
    last_seen = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("device_id", "name", name="uq_device_antivirus"),)


class DeviceVolume(Base):
    """A fixed volume: capacity from the disks section, protection from the
    encryption section, merged on the volume name (C:, /, /home)."""
    __tablename__ = "device_volumes"

    id = Column(Integer, primary_key=True)
    device_id = _device_fk()
    name = Column(String(255), nullable=False)
    filesystem = Column(String(32))
    size_gb = Column(Float)
    free_gb = Column(Float)
    encryption_method = Column(String(64))      # BitLocker, FileVault, LUKS
    encrypted = Column(Boolean)
    encryption_status = Column(String(64))
    last_seen = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("device_id", "name", name="uq_device_volume"),)


class DeviceNetworkAdapter(Base):
    __tablename__ = "device_network_adapters"

    id = Column(Integer, primary_key=True)
    device_id = _device_fk()
    name = Column(String(255), nullable=False)
    mac = Column(String(32), index=True)
    ip_addresses = Column(JSON, nullable=False, default=list)
    speed_mbps = Column(Integer)
    dhcp = Column(Boolean)
    gateway = Column(String(64))
    dns_servers = Column(JSON, nullable=False, default=list)
    last_seen = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("device_id", "name", name="uq_device_nic"),)


class DeviceMonitor(Base):
    __tablename__ = "device_monitors"

    id = Column(Integer, primary_key=True)
    device_id = _device_fk()
    manufacturer = Column(String(255))
    model = Column(String(255))
    serial_number = Column(String(255), index=True)
    last_seen = Column(DateTime(timezone=True), server_default=func.now())


class DevicePrinter(Base):
    __tablename__ = "device_printers"

    id = Column(Integer, primary_key=True)
    device_id = _device_fk()
    name = Column(String(255), nullable=False)
    driver = Column(String(255))
    port = Column(String(255))
    is_network = Column(Boolean)
    is_default = Column(Boolean)
    last_seen = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("device_id", "name", name="uq_device_printer"),)


CHANGE_CATEGORIES = ("software", "patch", "hardware", "os", "account", "security", "service", "monitor")
CHANGE_SEVERITIES = ("info", "warning")


class DeviceChange(Base):
    """One detected change between consecutive inventory reports."""
    __tablename__ = "device_changes"

    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    category = Column(String(16), nullable=False, index=True)
    change_type = Column(String(16), nullable=False)       # added | removed | changed
    item = Column(String(500), nullable=False)             # "Zoom", "KB5034441", "RAM"
    field = Column(String(64))                             # for "changed": which attribute
    old_value = Column(Text)
    new_value = Column(Text)
    severity = Column(String(16), nullable=False, default="info", index=True)
    source = Column(String(32))
    detected_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    notified_at = Column(DateTime(timezone=True))          # included in a sent risky-changes email

    __table_args__ = (
        Index("ix_device_changes_device_time", "device_id", "detected_at"),
        Index("ix_device_changes_time", "detected_at"),
    )
