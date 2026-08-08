from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from backend.database import Base

# Lifecycle state machine: requested → ordered → in_stock → deployed ⇄ maintenance → retired
LIFECYCLE_STATES = ["requested", "ordered", "in_stock", "deployed", "maintenance", "retired"]
ALLOWED_TRANSITIONS = {
    "requested":   ["ordered", "retired"],           # retired = request cancelled
    "ordered":     ["in_stock", "deployed"],
    "in_stock":    ["deployed", "retired"],
    "deployed":    ["maintenance", "retired"],
    "maintenance": ["deployed", "retired"],
    "retired":     [],
}

ASSET_CATEGORIES = ["hardware", "software", "cloud", "peripheral"]

# Controlled vocabularies for the security/CMDB fields (all nullable).
CRITICALITY = ["critical", "high", "medium", "low"]
DATA_CLASSIFICATION = ["restricted", "confidential", "internal", "public"]
LOG_SOURCE_STATUS = ["onboarded", "not_onboarded", "inactive"]
MONITORING_STATUS = ["monitored", "not_monitored", "degraded"]
BACKUP_STATUS = ["protected", "unprotected", "failed", "unknown"]


class Asset(Base):
    """Canonical managed ITAM record. Discovered `devices` link in via device_id."""
    __tablename__ = "assets"

    id = Column(Integer, primary_key=True)
    asset_tag = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    category = Column(String(32), nullable=False, index=True)
    asset_type = Column(String(64))                  # laptop, server, vm, saas-instance…
    lifecycle_state = Column(String(32), nullable=False, default="requested", index=True)

    serial_number = Column(String(255), index=True)
    vendor = Column(String(255))
    model = Column(String(255))
    location = Column(String(255))
    department = Column(String(255))
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True)

    purchase_date = Column(Date)
    purchase_cost = Column(Numeric(12, 2))
    currency = Column(String(3), default="USD")
    warranty_end = Column(Date)

    # ── Technical identity (auto-filled from the linked device when adopted) ──
    firmware_version = Column(String(128))
    ip_address = Column(String(64))
    mac_address = Column(String(64))
    os_name = Column(String(255))
    os_version = Column(String(128))
    applications = Column(Text)                 # Applications / Services (free text/CSV)

    # ── Network & ownership ──
    network_zone = Column(String(128))          # Network Zone / VLAN
    point_of_contact = Column(String(255))

    # ── Security / compliance posture ──
    criticality = Column(String(16))            # critical | high | medium | low
    data_classification = Column(String(16))    # restricted | confidential | internal | public
    compliance = Column(String(255))            # e.g. "PCI-DSS, ISO 27001"

    # ── Log source / monitoring (SIEM onboarding) ──
    log_source_status = Column(String(16))      # onboarded | not_onboarded | inactive
    log_source_type = Column(String(128))       # Syslog, WinEventLog, CEF…
    log_forwarding_destination = Column(String(255))
    last_log_received = Column(DateTime(timezone=True))
    monitoring_status = Column(String(16))      # monitored | not_monitored | degraded
    backup_status = Column(String(16))          # protected | unprotected | failed | unknown
    last_vulnerability_scan = Column(Date)

    # ── Lifecycle / governance ──
    eol_eos_date = Column(Date)                 # End of Life / End of Support
    last_reviewed_date = Column(Date)
    reviewer = Column(String(255))

    custom_fields = Column(JSON, nullable=False, default=dict)
    notes = Column(Text)

    # Reconciliation link to auto-discovered device (one asset per device)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="SET NULL"),
                       unique=True, nullable=True)

    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    lifecycle_events = relationship(
        "AssetLifecycleEvent", back_populates="asset",
        cascade="all, delete-orphan", order_by="AssetLifecycleEvent.occurred_at",
    )
    outgoing_relationships = relationship(
        "AssetRelationship", foreign_keys="AssetRelationship.source_asset_id",
        back_populates="source", cascade="all, delete-orphan",
    )
    incoming_relationships = relationship(
        "AssetRelationship", foreign_keys="AssetRelationship.target_asset_id",
        back_populates="target", cascade="all, delete-orphan",
    )
    assignee = relationship("User", foreign_keys=[assigned_to], lazy="joined")
    device = relationship("Device", foreign_keys=[device_id], lazy="joined")

    __table_args__ = (
        CheckConstraint(f"category IN {tuple(ASSET_CATEGORIES)}", name="ck_assets_category"),
        CheckConstraint(f"lifecycle_state IN {tuple(LIFECYCLE_STATES)}", name="ck_assets_state"),
        CheckConstraint(f"criticality IS NULL OR criticality IN {tuple(CRITICALITY)}",
                        name="ck_assets_criticality"),
        CheckConstraint(
            f"data_classification IS NULL OR data_classification IN {tuple(DATA_CLASSIFICATION)}",
            name="ck_assets_data_class"),
        CheckConstraint(
            f"log_source_status IS NULL OR log_source_status IN {tuple(LOG_SOURCE_STATUS)}",
            name="ck_assets_log_status"),
        CheckConstraint(
            f"monitoring_status IS NULL OR monitoring_status IN {tuple(MONITORING_STATUS)}",
            name="ck_assets_monitoring"),
        CheckConstraint(f"backup_status IS NULL OR backup_status IN {tuple(BACKUP_STATUS)}",
                        name="ck_assets_backup"),
        Index("ix_assets_category_state", "category", "lifecycle_state"),
    )


class AssetLifecycleEvent(Base):
    """Append-only history of lifecycle transitions."""
    __tablename__ = "asset_lifecycle_events"

    id = Column(Integer, primary_key=True)
    asset_id = Column(Integer, ForeignKey("assets.id", ondelete="CASCADE"),
                      nullable=False, index=True)
    from_state = Column(String(32), nullable=True)   # null = creation
    to_state = Column(String(32), nullable=False)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    note = Column(Text)
    occurred_at = Column(DateTime(timezone=True), server_default=func.now())

    asset = relationship("Asset", back_populates="lifecycle_events")
    actor = relationship("User", foreign_keys=[actor_id], lazy="joined")
