from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from backend.database import Base

# Directed edge types with display labels for the reverse direction.
RELATIONSHIP_TYPES = {
    "depends_on":   "required by",
    "installed_on": "runs",
    "connected_to": "connected to",   # effectively symmetric
    "hosts":        "hosted on",
    "part_of":      "contains",
    "backs_up":     "backed up by",
}


class AssetRelationship(Base):
    """CMDB edge: <source> --type--> <target> (e.g. app A depends_on db B)."""
    __tablename__ = "asset_relationships"

    id = Column(Integer, primary_key=True)
    source_asset_id = Column(Integer, ForeignKey("assets.id", ondelete="CASCADE"),
                             nullable=False, index=True)
    target_asset_id = Column(Integer, ForeignKey("assets.id", ondelete="CASCADE"),
                             nullable=False, index=True)
    relationship_type = Column(String(32), nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    source = relationship("Asset", foreign_keys=[source_asset_id],
                          back_populates="outgoing_relationships")
    target = relationship("Asset", foreign_keys=[target_asset_id],
                          back_populates="incoming_relationships")

    __table_args__ = (
        UniqueConstraint("source_asset_id", "target_asset_id", "relationship_type",
                         name="uq_asset_rel_edge"),
        CheckConstraint("source_asset_id <> target_asset_id", name="ck_asset_rel_no_self"),
        CheckConstraint(
            f"relationship_type IN {tuple(RELATIONSHIP_TYPES)}",
            name="ck_asset_rel_type",
        ),
    )
