from sqlalchemy import JSON, Column, Date, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.sql import func

from backend.database import Base


class DeviceLifecycle(Base):
    """A device's OS release, or an installed software version, matched against
    the end-of-life catalogue. Rebuilt on each inventory report and whenever
    the catalogue changes; status (unsupported / ending soon) is derived from
    `eol` at query time, so it never goes stale."""
    __tablename__ = "device_lifecycle"

    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(16), nullable=False)            # os | software
    product_id = Column(String(64), nullable=False)      # catalogue product id
    product = Column(String(128), nullable=False)        # "Windows 10"
    cycle = Column(String(64), nullable=False)           # "22H2"
    title = Column(String(255), nullable=False)          # "Windows 10 22H2 (Enterprise/Education)"
    eol = Column(Date, index=True)                       # null: supported, no end announced
    support_end = Column(Date)
    extended = Column(Date)                              # paid extended support (ESU/ESM/ELS)
    detail = Column(String(500))                         # the OS string / installed title that matched
    catalog_version = Column(String(32))

    __table_args__ = (
        UniqueConstraint("device_id", "kind", "product_id", "cycle", name="uq_device_lifecycle_item"),
        Index("ix_device_lifecycle_product", "kind", "product_id", "cycle"),
    )


class LifecycleCatalog(Base):
    """An end-of-life catalogue uploaded by an administrator. The newest of
    these and the bundled catalogue (by publication date) is the one in use."""
    __tablename__ = "lifecycle_catalogs"

    id = Column(Integer, primary_key=True)
    version = Column(String(32), nullable=False)
    published = Column(Date, nullable=False)
    content = Column(JSON, nullable=False)
    uploaded_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
