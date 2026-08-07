from datetime import datetime

from pydantic import BaseModel, Field, field_validator


ALLOWED_ROLES = {"admin", "asset_manager", "viewer", "user"}  # "user" = legacy alias for viewer


class UserBase(BaseModel):
    username: str
    email: str
    role: str = "viewer"

    @field_validator("role")
    @classmethod
    def role_allowed(cls, v: str) -> str:
        if v not in ALLOWED_ROLES:
            raise ValueError(f"role must be one of {sorted(ALLOWED_ROLES)}")
        return v

    @field_validator("email")
    @classmethod
    def email_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v or "@" not in v or len(v) > 255:
            raise ValueError("Invalid email format")
        return v


class UserCreate(UserBase):
    password: str


class UserLogin(BaseModel):
    username: str
    password: str


class UserOut(UserBase):
    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
