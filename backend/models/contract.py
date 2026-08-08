from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Table,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from backend.database import Base

CONTRACT_TYPES = ["lease", "support", "maintenance", "subscription"]

# m:n contract <-> asset
contract_assets = Table(
    "contract_assets",
    Base.metadata,
    Column("contract_id", Integer,
           ForeignKey("contracts.id", ondelete="CASCADE"), primary_key=True),
    Column("asset_id", Integer,
           ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True),
)


class Contract(Base):
    __tablename__ = "contracts"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    contract_type = Column(String(32), nullable=False, index=True)
    vendor = Column(String(255))
    reference_no = Column(String(128))
    start_date = Column(Date)
    end_date = Column(Date, index=True)          # drives renewal alerts (Phase 6)
    notice_days = Column(Integer, default=30)
    cost = Column(Numeric(12, 2))
    currency = Column(String(3), default="USD")
    auto_renews = Column(Boolean, default=False)
    custom_fields = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    assets = relationship("Asset", secondary=contract_assets, lazy="selectin")
    entitlements = relationship("Entitlement", back_populates="contract")

    __table_args__ = (
        CheckConstraint(f"contract_type IN {tuple(CONTRACT_TYPES)}", name="ck_contracts_type"),
    )
