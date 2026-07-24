"""User invitations for practice admin and staff."""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core import security
from app.core.permissions import normalize_staff_role
from app.models.invite import InviteToken, InviteType
from app.models.user import UserRole
from app.services import email_service, user_service


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def create_invite(
    db: AsyncSession,
    *,
    practice_id: uuid.UUID,
    practice_name: str,
    email: str,
    first_name: str,
    last_name: str,
    invite_type: InviteType,
    inviter_name: str = "NextHealth",
    role: str = "member",
    location_ids: Sequence[uuid.UUID] | None = None,
) -> str:
    raw = security.generate_opaque_token()
    loc_ids = [str(x) for x in (location_ids or [])]
    if invite_type == InviteType.PRACTICE_ADMIN:
        stored_role = UserRole.ADMIN.value
    else:
        stored_role = normalize_staff_role(role).value
    db.add(
        InviteToken(
            practice_id=practice_id,
            email=email.strip().lower(),
            first_name=first_name.strip(),
            last_name=last_name.strip(),
            invite_type=invite_type,
            role=stored_role,
            location_ids=loc_ids,
            token_hash=security.hash_token(raw),
            expires_at=_now() + timedelta(hours=settings.invite_ttl_hours),
        )
    )
    await db.flush()

    invite_url = f"{settings.frontend_url}/accept-invite?token={raw}"
    if invite_type == InviteType.PRACTICE_ADMIN:
        email_service.send_practice_admin_invite(
            to=email,
            practice_name=practice_name,
            invite_url=invite_url,
            admin_name=first_name or "there",
        )
    else:
        email_service.send_staff_invite(
            to=email,
            practice_name=practice_name,
            invite_url=invite_url,
            inviter_name=inviter_name,
        )
    return raw


async def get_valid_invite(db: AsyncSession, raw_token: str) -> InviteToken | None:
    token_hash = security.hash_token(raw_token)
    result = await db.execute(
        select(InviteToken).where(InviteToken.token_hash == token_hash)
    )
    row = result.scalar_one_or_none()
    if row is None or row.accepted_at is not None or row.expires_at <= _now():
        return None
    return row


async def accept_invite(
    db: AsyncSession,
    invite: InviteToken,
    *,
    password: str,
):
    from app.models.user import AccountType, AuthProvider
    from app.services import practice_service

    if invite.invite_type == InviteType.PRACTICE_ADMIN:
        role = UserRole.ADMIN
    else:
        role = normalize_staff_role(invite.role)

    user = await user_service.create_user(
        db,
        email=invite.email,
        first_name=invite.first_name,
        last_name=invite.last_name,
        role=role,
        password_hash=security.hash_password(password),
        auth_provider=AuthProvider.PASSWORD,
        email_verified=True,
        account_type=AccountType.PRACTICE,
        practice_id=invite.practice_id,
    )

    practice_locations = await practice_service.list_practice_locations(
        db, invite.practice_id
    )
    practice_loc_ids = {loc.id for loc in practice_locations}

    if invite.invite_type == InviteType.PRACTICE_ADMIN:
        # Practice admins get every office.
        granted = list(practice_loc_ids)
    else:
        requested = []
        for raw in invite.location_ids or []:
            try:
                requested.append(uuid.UUID(str(raw)))
            except ValueError:
                continue
        granted = [lid for lid in requested if lid in practice_loc_ids]

    if granted:
        await user_service.set_user_locations(db, user, granted)

    invite.accepted_at = _now()
    await db.flush()
    return user
