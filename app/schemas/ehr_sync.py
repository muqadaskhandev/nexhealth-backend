"""EHR Synchronizer API schemas."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.ehr_connection import ConnectionMode
from app.models.practice import EhrSystem, SyncStatus


class CredentialFieldOut(BaseModel):
    key: str
    label: str
    type: str


class EhrConnectionOut(BaseModel):
    ehr_system: EhrSystem
    connection_mode: ConnectionMode
    credentials_configured: bool
    credentials_hint: dict[str, Any]
    connector_installed: bool
    last_tested_at: datetime | None
    last_sync_at: datetime | None
    sync_status: SyncStatus
    sync_error: str | None
    required_fields: list[CredentialFieldOut] = []
    locations_mapped: int = 0
    locations_total: int = 0


class EhrCredentialsRequest(BaseModel):
    connection_mode: ConnectionMode = ConnectionMode.API
    credentials: dict[str, str] = Field(default_factory=dict)


class LocationEhrMapping(BaseModel):
    location_id: uuid.UUID
    ehr_site_id: str = Field(min_length=1, max_length=120)
    ehr_site_name: str = Field(default="", max_length=200)


class LocationEhrMappingRequest(BaseModel):
    mappings: list[LocationEhrMapping]


class ConnectionTestOut(BaseModel):
    ok: bool
    message: str
    sync_status: SyncStatus


class SyncRunOut(BaseModel):
    ok: bool
    message: str
    patients_imported: int
    patients_updated: int
    sync_status: SyncStatus
