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
    separate_by_patient_type: bool = True
    allow_cancellations_for_unmapped: bool = False
    set_availability_by_operatory: bool = False
    ask_for_insurance: bool = False
    reserve_with_google: bool = False
    google_reserve_status: str = "inactive"
    google_reserve_message: str = ""
    form_expiration_amount: int = 7
    form_expiration_unit: str = "days"
    form_sync_mode: str = "automatic"


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
    separate_by_patient_type: bool | None = None
    allow_cancellations_for_unmapped: bool | None = None
    set_availability_by_operatory: bool | None = None
    ask_for_insurance: bool | None = None
    reserve_with_google: bool | None = None
    form_expiration_amount: int | None = Field(default=None, ge=1)
    form_expiration_unit: str | None = None
    form_sync_mode: str | None = None


class LogoCopyRequest(BaseModel):
    location_ids: list[uuid.UUID] = Field(min_length=1)
