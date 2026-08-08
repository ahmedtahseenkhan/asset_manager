from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from backend.models.contract import CONTRACT_TYPES
from backend.schemas.asset import RelatedAssetSummary


class ContractBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    contract_type: str
    vendor: Optional[str] = None
    reference_no: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    notice_days: int = Field(default=30, ge=0, le=365)
    cost: Optional[Decimal] = None
    currency: str = Field(default="USD", min_length=3, max_length=3)
    auto_renews: bool = False
    custom_fields: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("contract_type")
    @classmethod
    def type_allowed(cls, v: str) -> str:
        if v not in CONTRACT_TYPES:
            raise ValueError(f"contract_type must be one of {CONTRACT_TYPES}")
        return v


class ContractCreate(ContractBase):
    pass


class ContractUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    vendor: Optional[str] = None
    reference_no: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    notice_days: Optional[int] = Field(default=None, ge=0, le=365)
    cost: Optional[Decimal] = None
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
    auto_renews: Optional[bool] = None
    custom_fields: Optional[Dict[str, Any]] = None


class EntitlementSummary(BaseModel):
    id: int
    product: str
    license_model: str
    seats_purchased: Optional[int]
    expires_on: Optional[date]


class ContractOut(ContractBase):
    id: int
    asset_count: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ContractDetailOut(ContractOut):
    assets: List[RelatedAssetSummary] = []
    entitlements: List[EntitlementSummary] = []


class ContractListOut(BaseModel):
    items: List[ContractOut]
    total: int
    page: int
    size: int


class AttachAssetRequest(BaseModel):
    asset_id: int
