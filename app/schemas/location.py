"""Location schemas."""
from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


class LocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    address: str
    address_line2: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    phone: str = ""
    email: str = ""
    logo_url: str | None = None
    ehr_site_id: str | None = None
    ehr_site_name: str | None = None


class SwitchLocationRequest(BaseModel):
    location_id: uuid.UUID


class LocationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    address: str | None = None
    address_line2: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    phone: str | None = None
    email: str | None = None


class LogoCopyRequest(BaseModel):
    location_ids: list[uuid.UUID] = Field(min_length=1)
