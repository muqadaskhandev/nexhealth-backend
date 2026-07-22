"""Pydantic schemas for providers, operatories, and availability slots."""
from __future__ import annotations

import uuid
from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field


class ProviderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    role: str
    status: str
    default_appointment_type_ids: list[str]
    default_insurances: list[str]
    created_at: datetime


class ProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    role: str = ""
    status: str = "active"
    default_appointment_type_ids: list[str] = Field(default_factory=list)
    default_insurances: list[str] = Field(default_factory=list)


class ProviderUpdate(BaseModel):
    name: str | None = None
    role: str | None = None
    status: str | None = None
    default_appointment_type_ids: list[str] | None = None
    default_insurances: list[str] | None = None


class OperatoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    active: bool
    created_at: datetime


class OperatoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    active: bool = True


class OperatoryUpdate(BaseModel):
    name: str | None = None
    active: bool | None = None


class AvailabilitySlotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider_id: uuid.UUID
    operatory_id: uuid.UUID | None
    repeat_mode: str
    specific_date: date | None
    day_of_week: int | None
    starts_on: date | None
    start_time: time
    end_time: time
    use_provider_defaults: bool
    appointment_type_ids: list[str]
    created_at: datetime


class AvailabilitySlotCreate(BaseModel):
    provider_id: uuid.UUID
    operatory_id: uuid.UUID | None = None
    repeat_mode: str = "weekly"
    specific_date: date | None = None
    day_of_week: int | None = Field(default=None, ge=0, le=6)
    starts_on: date | None = None
    start_time: time
    end_time: time
    use_provider_defaults: bool = True
    appointment_type_ids: list[str] = Field(default_factory=list)


class AvailabilitySlotUpdate(BaseModel):
    operatory_id: uuid.UUID | None = None
    repeat_mode: str | None = None
    specific_date: date | None = None
    day_of_week: int | None = Field(default=None, ge=0, le=6)
    starts_on: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    use_provider_defaults: bool | None = None
    appointment_type_ids: list[str] | None = None
