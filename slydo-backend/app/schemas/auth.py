"""认证相关 Pydantic Schema"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=64)
    password: str = Field(..., min_length=4, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


class UserCreate(BaseModel):
    """管理员创建用户"""
    username: str = Field(..., min_length=2, max_length=64)
    password: str = Field(..., min_length=4, max_length=128)
    display_name: str | None = Field(None, max_length=128)
    role: str = Field("user", pattern=r"^(admin|user)$")
    permissions: list[str] | None = None
    token_ttl_hours: int | None = Field(None, ge=1, le=8760)


class UserOut(BaseModel):
    id: UUID
    username: str
    display_name: str | None
    role: str
    permissions: list[str] = []
    token_ttl_hours: int = 168
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    is_active: bool | None = None
    role: str | None = Field(None, pattern=r"^(admin|user)$")
    password: str | None = Field(None, min_length=4, max_length=128)
    permissions: list[str] | None = None
    token_ttl_hours: int | None = Field(None, ge=1, le=8760)
