"""Gate EHR integration until live connectors are enabled."""
from __future__ import annotations

from fastapi import HTTPException, status

from app.config import settings
from app.core.ehr_features import EHR_COMING_SOON_MESSAGE


def ehr_sync_live() -> bool:
    return settings.ehr_sync_enabled


def require_ehr_sync_enabled() -> None:
    if not ehr_sync_live():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=EHR_COMING_SOON_MESSAGE,
        )
