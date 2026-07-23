"""Pydantic schemas for custom online booking form fields and insurances."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BookingFormFieldOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    field_type: str
    label: str
    show_to: str
    required: bool
    note_text: str
    options: list[str]
    position: int
    created_at: datetime


class BookingFormFieldCreate(BaseModel):
    field_type: str = "text"
    label: str = Field(min_length=1, max_length=200)
    show_to: str = "all"
    required: bool = False
    note_text: str = ""
    options: list[str] = Field(default_factory=list)


class BookingFormFieldUpdate(BaseModel):
    field_type: str | None = None
    label: str | None = None
    show_to: str | None = None
    required: bool | None = None
    note_text: str | None = None
    options: list[str] | None = None


class BookingFormFieldReorder(BaseModel):
    ordered_ids: list[uuid.UUID]


class BookingInsuranceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    created_at: datetime


class BookingInsuranceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class BookingInsuranceBulkCreate(BaseModel):
    names: list[str] = Field(min_length=1)
