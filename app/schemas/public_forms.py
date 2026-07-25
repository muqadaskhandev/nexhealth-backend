"""Pydantic schemas for the public (unauthenticated) patient forms flow."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class PublicTokenInfoOut(BaseModel):
    practice_name: str
    practice_logo_url: str | None
    location_name: str
    location_address: str
    location_phone: str


class PublicVerifyRequest(BaseModel):
    last_name: str = Field(min_length=1, max_length=120)
    dob: date


class PublicFormFieldOut(BaseModel):
    id: str
    type: str
    label: str
    required: bool
    options: list[str]
    page: int
    min_length: int | None = None
    max_length: int | None = None
    conditional_field_id: str | None = None
    conditional_value: str = ""


class PublicFormOut(BaseModel):
    request_id: uuid.UUID
    template_id: uuid.UUID
    name: str
    display_type: str
    page_count: int
    fields: list[PublicFormFieldOut]
    completed: bool
    expires_at: datetime


class PublicVerifyOut(BaseModel):
    patient_name: str
    practice_name: str
    practice_logo_url: str | None
    location_name: str
    location_address: str
    location_phone: str
    forms: list[PublicFormOut]


class PublicSubmitRequest(BaseModel):
    last_name: str = Field(min_length=1, max_length=120)
    dob: date
    form_request_id: uuid.UUID
    answers: dict[str, Any] = Field(default_factory=dict)


class PublicSubmitOut(BaseModel):
    remaining: int
