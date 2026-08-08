from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.models.entitlement import LICENSE_MODELS


class EntitlementBase(BaseModel):
    product: str = Field(min_length=1, max_length=255)
    vendor: Optional[str] = None
    license_model: str
    seats_purchased: Optional[int] = Field(default=None, ge=1)
    contract_id: Optional[int] = None
    expires_on: Optional[date] = None
    custom_fields: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("license_model")
    @classmethod
    def model_allowed(cls, v: str) -> str:
        if v not in LICENSE_MODELS:
            raise ValueError(f"license_model must be one of {LICENSE_MODELS}")
        return v


class EntitlementCreate(EntitlementBase):
    license_key: Optional[str] = None   # stored encrypted; never echoed back in full


class EntitlementUpdate(BaseModel):
    product: Optional[str] = Field(default=None, min_length=1, max_length=255)
    vendor: Optional[str] = None
    seats_purchased: Optional[int] = Field(default=None, ge=1)
    license_key: Optional[str] = None
    contract_id: Optional[int] = None
    expires_on: Optional[date] = None
    custom_fields: Optional[Dict[str, Any]] = None


class AssignRequest(BaseModel):
    asset_id: Optional[int] = None
    user_id: Optional[int] = None

    @model_validator(mode="after")
    def one_target(self) -> "AssignRequest":
        if self.asset_id is None and self.user_id is None:
            raise ValueError("Provide asset_id and/or user_id")
        return self


class AssignmentOut(BaseModel):
    id: int
    asset_id: Optional[int]
    asset_tag: Optional[str] = None
    asset_name: Optional[str] = None
    user_id: Optional[int]
    username: Optional[str] = None
    assigned_at: datetime


class EntitlementOut(EntitlementBase):
    id: int
    seats_used: int = 0
    has_key: bool = False
    key_hint: Optional[str] = None      # last 4 chars only
    contract_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class EntitlementDetailOut(EntitlementOut):
    assignments: List[AssignmentOut] = []
    license_key: Optional[str] = None   # populated for admins only


class EntitlementListOut(BaseModel):
    items: List[EntitlementOut]
    total: int
    page: int
    size: int
