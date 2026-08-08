from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from backend.database import Base
from backend.utils.encryption import EncryptedString

# per_seat: consumed by user assignments; per_device: by asset assignments;
# site / subscription: unlimited assignments (tracking only).
LICENSE_MODELS = ["per_seat", "per_device", "site", "subscription"]


class Entitlement(Base):
    """A software license the CUSTOMER owns (separate from this app's own license)."""
    __tablename__ = "entitlements"

    id = Column(Integer, primary_key=True)
    product = Column(String(255), nullable=False)
    vendor = Column(String(255))
    license_model = Column(String(32), nullable=False)
    seats_purchased = Column(Integer)                    # null = unlimited
    license_key = Column(EncryptedString(), nullable=True)   # encrypted at rest (Fernet)
    contract_id = Column(Integer, ForeignKey("contracts.id", ondelete="SET NULL"),
                         nullable=True, index=True)
    expires_on = Column(Date, index=True)                # drives expiry alerts (Phase 6)
    custom_fields = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    contract = relationship("Contract", back_populates="entitlements", lazy="joined")
    assignments = relationship("EntitlementAssignment", back_populates="entitlement",
                               cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        CheckConstraint(f"license_model IN {tuple(LICENSE_MODELS)}", name="ck_entitlements_model"),
    )


class EntitlementAssignment(Base):
    """One consumed seat: an entitlement assigned to an asset and/or a user."""
    __tablename__ = "entitlement_assignments"

    id = Column(Integer, primary_key=True)
    entitlement_id = Column(Integer, ForeignKey("entitlements.id", ondelete="CASCADE"),
                            nullable=False, index=True)
    asset_id = Column(Integer, ForeignKey("assets.id", ondelete="CASCADE"),
                      nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                     nullable=True, index=True)
    assigned_at = Column(DateTime(timezone=True), server_default=func.now())

    entitlement = relationship("Entitlement", back_populates="assignments")
    asset = relationship("Asset", lazy="joined")
    user = relationship("User", lazy="joined")

    __table_args__ = (
        CheckConstraint("asset_id IS NOT NULL OR user_id IS NOT NULL",
                        name="ck_ent_assign_target"),
    )
