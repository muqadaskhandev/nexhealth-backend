"""Encrypt/decrypt EHR connector credentials at rest."""
from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


def _fernet() -> Fernet:
    key_material = settings.ehr_credentials_key.strip()
    if key_material:
        return Fernet(key_material.encode("utf-8"))
    # Dev fallback: derive a stable Fernet key from JWT secret.
    digest = hashlib.sha256(settings.jwt_secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_credentials(data: dict[str, Any]) -> str:
    payload = json.dumps(data).encode("utf-8")
    return _fernet().encrypt(payload).decode("utf-8")


def decrypt_credentials(token: str) -> dict[str, Any]:
    try:
        raw = _fernet().decrypt(token.encode("utf-8"))
    except InvalidToken as exc:
        raise ValueError("Could not decrypt EHR credentials") from exc
    return json.loads(raw.decode("utf-8"))


def mask_secret(value: str, visible: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= visible:
        return "*" * len(value)
    return "*" * (len(value) - visible) + value[-visible:]
