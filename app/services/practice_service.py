"""Practice onboarding and settings."""
from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.ehr_connection import EhrConnection
from app.models.location import Location
from app.models.practice import (
    DEFAULT_PRODUCTS,
    EhrSystem,
    Practice,
    SubscriptionPlan,
    SyncStatus,
)


async def get_practice(db: AsyncSession, practice_id: uuid.UUID) -> Practice | None:
    return await db.get(Practice, practice_id)


async def get_practice_with_locations(
    db: AsyncSession, practice_id: uuid.UUID
) -> Practice | None:
    result = await db.execute(
        select(Practice)
        .where(Practice.id == practice_id)
        .options(selectinload(Practice.locations))
    )
    return result.scalar_one_or_none()


async def list_practices(db: AsyncSession) -> list[Practice]:
    result = await db.execute(
        select(Practice).options(selectinload(Practice.locations)).order_by(Practice.name)
    )
    return list(result.scalars().all())


async def create_practice(
    db: AsyncSession,
    *,
    name: str,
    address: str = "",
    city: str = "",
    state: str = "",
    zip_code: str = "",
    phone: str = "",
    subscription_plan: SubscriptionPlan = SubscriptionPlan.STARTER,
    enabled_products: dict | None = None,
    default_location_name: str | None = None,
) -> tuple[Practice, Location]:
    products = enabled_products or dict(DEFAULT_PRODUCTS)
    practice = Practice(
        name=name.strip(),
        address=address.strip(),
        city=city.strip(),
        state=state.strip(),
        zip_code=zip_code.strip(),
        phone=phone.strip(),
        subscription_plan=subscription_plan,
        enabled_products=products,
    )
    db.add(practice)
    await db.flush()

    loc_name = default_location_name or f"{practice.name} — Main"
    location = Location(
        practice_id=practice.id,
        name=loc_name,
        address=address.strip() or practice.address,
        city=city.strip(),
        state=state.strip(),
        zip_code=zip_code.strip(),
        phone=phone.strip(),
    )
    db.add(location)
    await db.flush()

    from app.services import staff_service

    await staff_service.seed_default_medical_history_form(db, practice.id, location.id)
    return practice, location


async def update_practice(db: AsyncSession, practice: Practice, **fields) -> Practice:
    for key, value in fields.items():
        if value is not None and hasattr(practice, key):
            setattr(practice, key, value)
    await db.flush()
    return practice


async def connect_ehr(
    db: AsyncSession,
    practice: Practice,
    *,
    ehr_system: EhrSystem,
) -> Practice:
    """Select EHR and reset connector state for a fresh setup."""
    practice.ehr_system = ehr_system
    practice.sync_status = (
        SyncStatus.PENDING if ehr_system != EhrSystem.NONE else SyncStatus.NOT_CONNECTED
    )
    practice.sync_error = None
    if ehr_system == EhrSystem.NONE:
        conn = await db.execute(
            select(EhrConnection).where(EhrConnection.practice_id == practice.id)
        )
        existing = conn.scalar_one_or_none()
        if existing:
            await db.delete(existing)
    else:
        from app.services import synchronizer_service

        await synchronizer_service.reset_connection_for_ehr_change(db, practice, ehr_system)
    await db.flush()
    return practice


async def create_location_for_practice(
    db: AsyncSession,
    practice: Practice,
    *,
    name: str,
    address: str = "",
    address_line2: str = "",
    city: str = "",
    state: str = "",
    zip_code: str = "",
    phone: str = "",
    email: str = "",
) -> Location:
    location = Location(
        practice_id=practice.id,
        name=name.strip(),
        address=address.strip(),
        address_line2=address_line2.strip(),
        city=city.strip(),
        state=state.strip(),
        zip_code=zip_code.strip(),
        phone=phone.strip(),
        email=email.strip(),
    )
    db.add(location)
    await db.flush()

    from app.services import staff_service

    await staff_service.seed_default_medical_history_form(db, practice.id, location.id)
    return location


async def get_practice_location(
    db: AsyncSession, practice_id: uuid.UUID, location_id: uuid.UUID
) -> Location | None:
    result = await db.execute(
        select(Location).where(
            Location.id == location_id,
            Location.practice_id == practice_id,
        )
    )
    return result.scalar_one_or_none()


async def update_location(db: AsyncSession, location: Location, **fields) -> Location:
    for key, value in fields.items():
        if value is not None and hasattr(location, key):
            setattr(location, key, value.strip() if isinstance(value, str) else value)
    await db.flush()
    return location


async def list_practice_locations(
    db: AsyncSession, practice_id: uuid.UUID
) -> list[Location]:
    result = await db.execute(
        select(Location)
        .where(Location.practice_id == practice_id)
        .order_by(Location.name)
    )
    return list(result.scalars().all())
