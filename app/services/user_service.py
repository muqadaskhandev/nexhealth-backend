"""User + location persistence logic."""
from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.location import Location, UserLocation
from app.models.user import AuthProvider, User, UserRole


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await db.get(User, user_id)


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(
        select(User).where(User.email == email.strip().lower())
    )
    return result.scalar_one_or_none()


async def get_user_with_locations(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    result = await db.execute(
        select(User)
        .where(User.id == user_id)
        .options(selectinload(User.memberships).selectinload(UserLocation.location))
    )
    return result.scalar_one_or_none()


async def list_user_locations(
    db: AsyncSession, user_id: uuid.UUID
) -> list[Location]:
    result = await db.execute(
        select(Location)
        .join(UserLocation, UserLocation.location_id == Location.id)
        .where(UserLocation.user_id == user_id)
        .order_by(Location.name)
    )
    return list(result.scalars().all())


async def user_can_access_location(
    db: AsyncSession, user_id: uuid.UUID, location_id: uuid.UUID
) -> bool:
    result = await db.execute(
        select(UserLocation.id).where(
            UserLocation.user_id == user_id,
            UserLocation.location_id == location_id,
        )
    )
    return result.scalar_one_or_none() is not None


async def default_location_for(
    db: AsyncSession, user_id: uuid.UUID
) -> Location | None:
    locations = await list_user_locations(db, user_id)
    return locations[0] if locations else None


async def create_user(
    db: AsyncSession,
    *,
    email: str,
    first_name: str,
    last_name: str,
    role: UserRole = UserRole.MEMBER,
    password_hash: str | None = None,
    auth_provider: AuthProvider = AuthProvider.PASSWORD,
    email_verified: bool = False,
    location_ids: Sequence[uuid.UUID] | None = None,
) -> User:
    user = User(
        email=email.strip().lower(),
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        role=role,
        password_hash=password_hash,
        auth_provider=auth_provider,
        email_verified=email_verified,
    )
    db.add(user)
    await db.flush()  # assign user.id

    if location_ids:
        await set_user_locations(db, user, location_ids)

    return user


async def set_user_locations(
    db: AsyncSession, user: User, location_ids: Sequence[uuid.UUID]
) -> None:
    """Replace a user's location memberships with the given set.

    Silently ignores ids that don't correspond to real locations.
    """
    result = await db.execute(
        select(Location.id).where(Location.id.in_(list(location_ids)))
    )
    valid_ids = set(result.scalars().all())

    # Drop existing memberships.
    existing = await db.execute(
        select(UserLocation).where(UserLocation.user_id == user.id)
    )
    for membership in existing.scalars().all():
        await db.delete(membership)
    await db.flush()

    for loc_id in valid_ids:
        db.add(UserLocation(user_id=user.id, location_id=loc_id))
    await db.flush()


async def list_users(db: AsyncSession) -> list[User]:
    result = await db.execute(
        select(User)
        .options(selectinload(User.memberships).selectinload(UserLocation.location))
        .order_by(User.created_at)
    )
    return list(result.scalars().all())


async def list_locations(db: AsyncSession) -> list[Location]:
    result = await db.execute(select(Location).order_by(Location.name))
    return list(result.scalars().all())
