"""Practice and platform schemas."""
from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.practice import EhrSystem, SubscriptionPlan, SyncStatus
from app.schemas.location import LocationOut


class EnabledProducts(BaseModel):
    scheduling: bool = True
    forms: bool = True
    communications: bool = True
    payments: bool = False
    verification: bool = False


class PracticeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    logo_url: str | None
    address: str
    city: str
    state: str
    zip_code: str
    phone: str
    subscription_plan: SubscriptionPlan
    enabled_products: dict[str, Any]
    ehr_system: EhrSystem
    sync_status: SyncStatus
    sync_error: str | None
    is_active: bool
    locations: list[LocationOut] = []


class LocationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    address: str = ""
    address_line2: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    phone: str = ""
    email: str = ""


class PracticeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    address: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    phone: str = ""
    subscription_plan: SubscriptionPlan = SubscriptionPlan.STARTER
    enabled_products: EnabledProducts | None = None
    admin_email: EmailStr
    admin_first_name: str = Field(min_length=1, max_length=120)
    admin_last_name: str = Field(min_length=1, max_length=120)
    default_location_name: str | None = None
    # Optional offices created at onboard time. When empty, one default location is created.
    locations: list[LocationCreate] = Field(default_factory=list)


class PracticeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    logo_url: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    phone: str | None = None
    enabled_products: EnabledProducts | None = None


class PlatformPracticeUpdate(BaseModel):
    """Fields a platform super-admin may change after onboarding."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    phone: str | None = None
    subscription_plan: SubscriptionPlan | None = None
    enabled_products: EnabledProducts | None = None
    is_active: bool | None = None


class EhrConnectRequest(BaseModel):
    ehr_system: EhrSystem


class InvitePreview(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str
    practice_name: str
    invite_type: str
    expires_at: str


class AcceptInviteRequest(BaseModel):
    token: str = Field(min_length=1)
    password: str = Field(min_length=6, max_length=200)

    @field_validator("password")
    @classmethod
    def strong_password(cls, value: str) -> str:
        if len(value) < 6:
            raise ValueError("Password must be at least 6 characters")
        if not any(c.isupper() for c in value):
            raise ValueError("Password must include at least one uppercase letter")
        if not any(c.isdigit() for c in value):
            raise ValueError("Password must include at least one number")
        if "@" not in value:
            raise ValueError('Password must include at least one "@" symbol')
        return value


class StaffInviteRequest(BaseModel):
    email: EmailStr
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)
    role: str = Field(
        default="member",
        pattern="^(admin|member|provider|front_desk|billing)$",
    )
    location_ids: list[uuid.UUID] = Field(min_length=1)
