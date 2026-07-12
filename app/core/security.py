"""Cryptographic primitives: password hashing, JWT, and opaque tokens.

- Passwords are hashed with Argon2id (memory-hard, the current OWASP default).
- Access tokens are short-lived signed JWTs.
- Refresh / reset tokens are high-entropy random strings; only their SHA-256
  hash is persisted, so the DB never holds a usable secret.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.config import settings

# Argon2id with sensible defaults (tuned by the library for interactive use).
_ph = PasswordHasher()

ACCESS_TOKEN_TYPE = "access"


# ── Passwords ────────────────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """Constant-time-ish verification. Returns False for SSO-only users."""
    if not password_hash:
        return False
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, Exception):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _ph.check_needs_rehash(password_hash)
    except Exception:
        return False


# ── Access-token JWTs ────────────────────────────────────────────────────────
def create_access_token(
    *,
    user_id: uuid.UUID,
    role: str,
    account_type: str,
    practice_id: uuid.UUID | None,
    active_location_id: uuid.UUID | None,
    session_id: uuid.UUID,
) -> str:
    """Issue a short-lived access JWT.

    `session_id` ties the access token to a refresh-token family so a revoked
    session can be rejected even before the access token expires (when the API
    chooses to check it).
    """
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "acct": account_type,
        "pid": str(practice_id) if practice_id else None,
        "loc": str(active_location_id) if active_location_id else None,
        "sid": str(session_id),
        "type": ACCESS_TOKEN_TYPE,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_ttl_minutes)).timestamp()),
        "jti": secrets.token_urlsafe(8),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode + verify an access token. Raises jwt.PyJWTError on failure."""
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["exp", "sub", "type"]},
    )
    if payload.get("type") != ACCESS_TOKEN_TYPE:
        raise jwt.InvalidTokenError("wrong token type")
    return payload


# ── Opaque tokens (refresh / password reset / oauth state) ───────────────────
def generate_opaque_token() -> str:
    """256 bits of entropy, URL-safe."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """SHA-256 hex digest for at-rest storage/lookup of opaque tokens."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_compare(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)
