"""Shared helpers for EHR adapters."""
from __future__ import annotations

from typing import Any

from app.synchronizer.types import ConnectionTestResult


def require_fields(credentials: dict[str, Any], fields: list[str]) -> list[str]:
    errors: list[str] = []
    for field in fields:
        if not str(credentials.get(field, "")).strip():
            errors.append(f"Missing required field: {field}")
    return errors
