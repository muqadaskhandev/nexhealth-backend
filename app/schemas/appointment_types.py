"""Pydantic schemas for appointment types, insertion rules, and mapping rules."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class InsertionRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code_type: str
    codes: list[str]


class InsertionRuleIn(BaseModel):
    code_type: str = ""
    codes: list[str] = Field(default_factory=list)


class AppointmentTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    duration_minutes: int
    available_online: bool
    patient_type: str
    allow_patient_cancel: bool
    position: int = 0
    insertion_rules: list[InsertionRuleOut] = Field(default_factory=list)
    created_at: datetime


class AppointmentTypeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    duration_minutes: int = Field(default=30, gt=0)
    available_online: bool = True
    patient_type: str = "all"
    allow_patient_cancel: bool = False
    insertion_rules: list[InsertionRuleIn] = Field(default_factory=list)


class AppointmentTypeUpdate(BaseModel):
    name: str | None = None
    duration_minutes: int | None = Field(default=None, gt=0)
    available_online: bool | None = None
    patient_type: str | None = None
    allow_patient_cancel: bool | None = None
    insertion_rules: list[InsertionRuleIn] | None = None


class AppointmentTypeReorder(BaseModel):
    ordered_ids: list[uuid.UUID]


class MappingCondition(BaseModel):
    field: str  # "visit_type" | "service_type" | "procedure_code" | "operatory" | "provider"
    values: list[str] = Field(default_factory=list)


class MappingFieldsIn(BaseModel):
    visit_type: str = ""
    service_type: str = ""
    procedure_codes: list[str] = Field(default_factory=list)
    operatory: str = ""


class MappingRetagOut(BaseModel):
    updated: int


class MappingRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    target_appointment_type_id: uuid.UUID
    conditions: list[dict[str, Any]]
    position: int
    created_at: datetime


class MappingRuleCreate(BaseModel):
    target_appointment_type_id: uuid.UUID
    conditions: list[MappingCondition] = Field(default_factory=list)


class MappingRuleUpdate(BaseModel):
    target_appointment_type_id: uuid.UUID | None = None
    conditions: list[MappingCondition] | None = None


class MappingRuleReorder(BaseModel):
    ordered_ids: list[uuid.UUID]


class CopyAppointmentTypesRequest(BaseModel):
    appointment_type_ids: list[uuid.UUID] = Field(min_length=1)
    location_ids: list[uuid.UUID] = Field(min_length=1)


class CopyAppointmentTypesOut(BaseModel):
    copied: int


class BulkPatientTypeUpdateItem(BaseModel):
    id: uuid.UUID
    patient_type: str = Field(pattern="^(new|existing|all)$")


class BulkPatientTypeUpdate(BaseModel):
    location_id: uuid.UUID
    updates: list[BulkPatientTypeUpdateItem] = Field(min_length=1)


class BulkPatientTypeUpdateOut(BaseModel):
    updated: int


class CopyMappingRulesRequest(BaseModel):
    rule_ids: list[uuid.UUID] = Field(min_length=1)
    location_ids: list[uuid.UUID] = Field(min_length=1)


class CopyMappingRulesOut(BaseModel):
    copied: int
