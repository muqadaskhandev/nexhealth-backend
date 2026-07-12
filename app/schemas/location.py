"""Location schemas."""
from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict


class LocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    address: str
    ehr_site_id: str | None = None
    ehr_site_name: str | None = None


class SwitchLocationRequest(BaseModel):
    location_id: uuid.UUID
