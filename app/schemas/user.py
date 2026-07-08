"""User-management schemas (admin CRUD)."""
from __future__ import annotations

import uuid

from pydantic import BaseModel, EmailStr, Field

from app.models.user import UserRole
from app.schemas.auth import UserOut
from app.schemas.location import LocationOut


class UserCreate(BaseModel):
    email: EmailStr
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)
    role: UserRole = UserRole.MEMBER
    # Optional: if omitted, the user is created without a password and must use
    # the "forgot password" flow or SSO to set one.
    password: str | None = Field(default=None, min_length=8, max_length=200)
    location_ids: list[uuid.UUID] = Field(default_factory=list)


class UserUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=120)
    last_name: str | None = Field(default=None, min_length=1, max_length=120)
    role: UserRole | None = None
    is_active: bool | None = None
    location_ids: list[uuid.UUID] | None = None


class UserDetail(UserOut):
    locations: list[LocationOut]
