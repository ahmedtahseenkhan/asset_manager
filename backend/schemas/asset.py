from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from backend.models.asset import ASSET_CATEGORIES, LIFECYCLE_STATES


class AssetBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    category: str
    asset_type: Optional[str] = Field(default=None, max_length=64)
    serial_number: Optional[str] = None
    vendor: Optional[str] = None
    model: Optional[str] = None
    location: Optional[str] = None
    department: Optional[str] = None
    assigned_to: Optional[int] = None
    purchase_date: Optional[date] = None
    purchase_cost: Optional[Decimal] = None
    currency: str = Field(default="USD", min_length=3, max_length=3)
    warranty_end: Optional[date] = None
    custom_fields: Dict[str, Any] = Field(default_factory=dict)
    notes: Optional[str] = None
    device_id: Optional[int] = None

    @field_validator("category")
    @classmethod
    def category_allowed(cls, v: str) -> str:
        if v not in ASSET_CATEGORIES:
            raise ValueError(f"category must be one of {ASSET_CATEGORIES}")
        return v


class AssetCreate(AssetBase):
    asset_tag: Optional[str] = Field(default=None, max_length=64)  # auto-generated if omitted


class AssetUpdate(BaseModel):
    """Partial update — lifecycle_state is intentionally excluded; use /transition."""
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    asset_type: Optional[str] = None
    serial_number: Optional[str] = None
    vendor: Optional[str] = None
    model: Optional[str] = None
    location: Optional[str] = None
    department: Optional[str] = None
    assigned_to: Optional[int] = None
    purchase_date: Optional[date] = None
    purchase_cost: Optional[Decimal] = None
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
    warranty_end: Optional[date] = None
    custom_fields: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None
    device_id: Optional[int] = None


class LifecycleTransition(BaseModel):
    to_state: str
    note: Optional[str] = None

    @field_validator("to_state")
    @classmethod
    def state_allowed(cls, v: str) -> str:
        if v not in LIFECYCLE_STATES:
            raise ValueError(f"to_state must be one of {LIFECYCLE_STATES}")
        return v


class LifecycleEventOut(BaseModel):
    id: int
    from_state: Optional[str]
    to_state: str
    actor: Optional[str] = None
    note: Optional[str]
    occurred_at: datetime

    class Config:
        from_attributes = True


class AssetOut(AssetBase):
    id: int
    asset_tag: str
    lifecycle_state: str
    assignee_username: Optional[str] = None
    device_hostname: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RelatedAssetSummary(BaseModel):
    id: int
    asset_tag: str
    name: str
    category: str
    lifecycle_state: str


class RelationshipEdgeOut(BaseModel):
    id: int
    type: str
    label: str
    asset: RelatedAssetSummary


class RelationshipsOut(BaseModel):
    outgoing: List[RelationshipEdgeOut] = []
    incoming: List[RelationshipEdgeOut] = []


class RelationshipCreate(BaseModel):
    target_asset_id: int
    relationship_type: str

    @field_validator("relationship_type")
    @classmethod
    def type_allowed(cls, v: str) -> str:
        from backend.models.asset_relationship import RELATIONSHIP_TYPES
        if v not in RELATIONSHIP_TYPES:
            raise ValueError(f"relationship_type must be one of {sorted(RELATIONSHIP_TYPES)}")
        return v


class AssetDetailOut(AssetOut):
    lifecycle_events: List[LifecycleEventOut] = []
    allowed_transitions: List[str] = []
    relationships: RelationshipsOut = RelationshipsOut()


class AssetListOut(BaseModel):
    items: List[AssetOut]
    total: int
    page: int
    size: int
