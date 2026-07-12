"""Authentication business logic: sign-in, sessions, refresh rotation, resets.

Session model
-------------
A *session* is a refresh-token family. On login we mint a refresh token (opaque,
stored hashed) and an access JWT bound to that session id. On refresh we rotate:
the presented refresh token is revoked and a fresh one issued. Presenting an
already-revoked token is treated as theft and revokes the entire family.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core import security
from app.models.token import PasswordResetToken, RefreshToken
from app.models.user import AuthProvider, User
from app.services import user_service

MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15


class AuthError(Exception):
    """Raised for any authentication failure surfaced to the caller."""

    def __init__(self, message: str = "Invalid email or password") -> None:
        self.message = message
        super().__init__(message)


@dataclass
class IssuedSession:
    access_token: str
    refresh_token: str
    csrf_token: str
    session_id: uuid.UUID
    active_location_id: uuid.UUID | None


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Password login ───────────────────────────────────────────────────────────
async def authenticate_password(
    db: AsyncSession, *, email: str, password: str
) -> User:
    """Verify credentials with lockout + uniform errors (no user enumeration)."""
    user = await user_service.get_user_by_email(db, email)

    # Always run a hash verification to keep timing uniform whether or not the
    # user exists, mitigating account-enumeration via response time.
    if user is None:
        security.verify_password(password, None)
        raise AuthError()

    if user.locked_until and user.locked_until > _now():
        raise AuthError("Account temporarily locked. Try again later.")

    if not user.is_active:
        raise AuthError("This account is disabled.")

    if not security.verify_password(password, user.password_hash):
        await _register_failed_login(db, user)
        raise AuthError()

    # Success: reset counters, opportunistically upgrade the hash.
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = _now()
    if user.password_hash and security.needs_rehash(user.password_hash):
        user.password_hash = security.hash_password(password)
    await db.flush()
    return user


async def _register_failed_login(db: AsyncSession, user: User) -> None:
    user.failed_login_count += 1
    if user.failed_login_count >= MAX_FAILED_LOGINS:
        user.locked_until = _now() + timedelta(minutes=LOCKOUT_MINUTES)
        user.failed_login_count = 0
    await db.flush()


# ── Session issuance / rotation ──────────────────────────────────────────────
async def issue_session(
    db: AsyncSession,
    user: User,
    *,
    user_agent: str | None = None,
    ip_address: str | None = None,
    session_id: uuid.UUID | None = None,
) -> IssuedSession:
    """Create a refresh-token row and matching access + CSRF tokens."""
    active_location = await user_service.default_location_for(db, user.id)
    active_location_id = active_location.id if active_location else None

    sid = session_id or uuid.uuid4()
    raw_refresh = security.generate_opaque_token()
    refresh_row = RefreshToken(
        id=sid,
        user_id=user.id,
        token_hash=security.hash_token(raw_refresh),
        expires_at=_now() + timedelta(days=settings.refresh_token_ttl_days),
        user_agent=(user_agent or "")[:400] or None,
        ip_address=(ip_address or "")[:64] or None,
    )
    db.add(refresh_row)
    await db.flush()

    access = security.create_access_token(
        user_id=user.id,
        role=user.role.value,
        account_type=user.account_type.value,
        practice_id=user.practice_id,
        active_location_id=active_location_id,
        session_id=refresh_row.id,
    )
    return IssuedSession(
        access_token=access,
        refresh_token=raw_refresh,
        csrf_token=security.generate_opaque_token(),
        session_id=refresh_row.id,
        active_location_id=active_location_id,
    )


async def rotate_refresh_token(
    db: AsyncSession,
    raw_refresh: str,
    *,
    user_agent: str | None = None,
    ip_address: str | None = None,
    active_location_id: uuid.UUID | None = None,
) -> IssuedSession:
    """Validate + rotate a refresh token, returning a fresh session."""
    token_hash = security.hash_token(raw_refresh)
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise AuthError("Invalid session")

    # Reuse of a revoked token => probable theft. Nuke the whole family.
    if row.revoked_at is not None:
        await _revoke_user_sessions(db, row.user_id)
        raise AuthError("Session revoked")

    if row.expires_at <= _now():
        raise AuthError("Session expired")

    user = await user_service.get_user_by_id(db, row.user_id)
    if user is None or not user.is_active:
        raise AuthError("Account unavailable")

    # Mint the replacement.
    raw_new = security.generate_opaque_token()
    new_row = RefreshToken(
        user_id=user.id,
        token_hash=security.hash_token(raw_new),
        expires_at=_now() + timedelta(days=settings.refresh_token_ttl_days),
        user_agent=(user_agent or "")[:400] or None,
        ip_address=(ip_address or "")[:64] or None,
    )
    db.add(new_row)
    await db.flush()

    row.revoked_at = _now()
    row.replaced_by = new_row.id
    await db.flush()

    # Preserve the active location the user had selected, if still valid.
    if active_location_id and not await user_service.user_can_access_location(
        db, user.id, active_location_id
    ):
        active_location_id = None
    if active_location_id is None:
        default = await user_service.default_location_for(db, user.id)
        active_location_id = default.id if default else None

    access = security.create_access_token(
        user_id=user.id,
        role=user.role.value,
        account_type=user.account_type.value,
        practice_id=user.practice_id,
        active_location_id=active_location_id,
        session_id=new_row.id,
    )
    return IssuedSession(
        access_token=access,
        refresh_token=raw_new,
        csrf_token=security.generate_opaque_token(),
        session_id=new_row.id,
        active_location_id=active_location_id,
    )


async def is_session_active(db: AsyncSession, session_id: uuid.UUID) -> bool:
    """True if the refresh-token family for this access token is still live.

    Called on every authenticated request so that logout, password change, and
    account deactivation revoke access immediately rather than waiting for the
    short access token to expire.
    """
    row = await db.get(RefreshToken, session_id)
    if row is None:
        return False
    return row.revoked_at is None and row.expires_at > _now()


async def revoke_refresh_token(db: AsyncSession, raw_refresh: str) -> None:
    token_hash = security.hash_token(raw_refresh)
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == token_hash, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


async def _revoke_user_sessions(db: AsyncSession, user_id: uuid.UUID) -> None:
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


async def issue_access_for_location(
    db: AsyncSession, user: User, *, session_id: uuid.UUID, location_id: uuid.UUID
) -> str:
    """Re-mint an access token pointing at a newly selected active location."""
    return security.create_access_token(
        user_id=user.id,
        role=user.role.value,
        account_type=user.account_type.value,
        practice_id=user.practice_id,
        active_location_id=location_id,
        session_id=session_id,
    )


# ── Password reset ───────────────────────────────────────────────────────────
async def create_password_reset(db: AsyncSession, user: User) -> str:
    """Create a single-use reset token, returning the raw value (to be emailed)."""
    raw = security.generate_opaque_token()
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=security.hash_token(raw),
            expires_at=_now() + timedelta(minutes=settings.password_reset_ttl_minutes),
        )
    )
    await db.flush()
    return raw


async def consume_password_reset(
    db: AsyncSession, raw_token: str, new_password: str
) -> User:
    token_hash = security.hash_token(raw_token)
    result = await db.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
    )
    row = result.scalar_one_or_none()
    if row is None or row.used_at is not None or row.expires_at <= _now():
        raise AuthError("Invalid or expired reset link")

    user = await user_service.get_user_by_id(db, row.user_id)
    if user is None:
        raise AuthError("Invalid or expired reset link")

    user.password_hash = security.hash_password(new_password)
    user.auth_provider = AuthProvider.PASSWORD
    user.email_verified = True
    row.used_at = _now()

    # Changing the password invalidates every existing session.
    await _revoke_user_sessions(db, user.id)
    await db.flush()
    return user
