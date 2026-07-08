"""Location schemas."""
from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict


class LocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    address: str


class SwitchLocationRequest(BaseModel):
    location_id: uuid.UUID
