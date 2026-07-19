"""Practice and platform schemas."""
from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

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


class PracticeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    logo_url: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    phone: str | None = None
    enabled_products: EnabledProducts | None = None


class EhrConnectRequest(BaseModel):
    ehr_system: EhrSystem


class LocationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    address: str = ""
    address_line2: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    phone: str = ""
    email: str = ""


class InvitePreview(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str
    practice_name: str
    invite_type: str
    expires_at: str


class AcceptInviteRequest(BaseModel):
    token: str = Field(min_length=1)
    password: str = Field(min_length=8, max_length=200)


class StaffInviteRequest(BaseModel):
    email: EmailStr
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)
    role: str = Field(default="member", pattern="^(admin|member)$")
    location_ids: list[uuid.UUID] = Field(min_length=1)
