from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from backend.models.asset import (
    ASSET_CATEGORIES,
    BACKUP_STATUS,
    CRITICALITY,
    DATA_CLASSIFICATION,
    LIFECYCLE_STATES,
    LOG_SOURCE_STATUS,
    MONITORING_STATUS,
)


def _enum_validator(field_name: str, allowed: List[str]):
    """Build a reusable optional-enum validator (empty string → None)."""
    def _check(cls, v):
        if v is None or v == "":
            return None
        if v not in allowed:
            raise ValueError(f"{field_name} must be one of {allowed}")
        return v
    return _check


class _AssetFields(BaseModel):
    """Every editable asset attribute (all optional except where noted)."""
    # Identity
    asset_type: Optional[str] = Field(default=None, max_length=64)
    serial_number: Optional[str] = None
    vendor: Optional[str] = None
    model: Optional[str] = None
    firmware_version: Optional[str] = None
    # Technical (auto-filled from linked device on adopt)
    ip_address: Optional[str] = None
    mac_address: Optional[str] = None
    os_name: Optional[str] = None
    os_version: Optional[str] = None
    applications: Optional[str] = None
    # Network & ownership
    network_zone: Optional[str] = None
    location: Optional[str] = None
    department: Optional[str] = None
    assigned_to: Optional[int] = None
    point_of_contact: Optional[str] = None
    # Security / compliance
    criticality: Optional[str] = None
    data_classification: Optional[str] = None
    compliance: Optional[str] = None
    # Log source / monitoring
    log_source_status: Optional[str] = None
    log_source_type: Optional[str] = None
    log_forwarding_destination: Optional[str] = None
    last_log_received: Optional[datetime] = None
    monitoring_status: Optional[str] = None
    backup_status: Optional[str] = None
    last_vulnerability_scan: Optional[date] = None
    # Procurement / lifecycle / governance
    purchase_date: Optional[date] = None
    purchase_cost: Optional[Decimal] = None
    currency: Optional[str] = Field(default="USD", min_length=3, max_length=3)
    warranty_end: Optional[date] = None
    eol_eos_date: Optional[date] = None
    last_reviewed_date: Optional[date] = None
    reviewer: Optional[str] = None
    # Misc
    custom_fields: Dict[str, Any] = Field(default_factory=dict)
    notes: Optional[str] = None
    device_id: Optional[int] = None

    _v_crit = field_validator("criticality")(_enum_validator("criticality", CRITICALITY))
    _v_data = field_validator("data_classification")(_enum_validator("data_classification", DATA_CLASSIFICATION))
    _v_log = field_validator("log_source_status")(_enum_validator("log_source_status", LOG_SOURCE_STATUS))
    _v_mon = field_validator("monitoring_status")(_enum_validator("monitoring_status", MONITORING_STATUS))
    _v_bak = field_validator("backup_status")(_enum_validator("backup_status", BACKUP_STATUS))


class AssetBase(_AssetFields):
    name: str = Field(min_length=1, max_length=255)
    category: str

    @field_validator("category")
    @classmethod
    def category_allowed(cls, v: str) -> str:
        if v not in ASSET_CATEGORIES:
            raise ValueError(f"category must be one of {ASSET_CATEGORIES}")
        return v


class AssetCreate(AssetBase):
    asset_tag: Optional[str] = Field(default=None, max_length=64)  # auto-generated if omitted


class AssetUpdate(_AssetFields):
    """Partial update — lifecycle_state is excluded (use /transition); name/category optional."""
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)


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
