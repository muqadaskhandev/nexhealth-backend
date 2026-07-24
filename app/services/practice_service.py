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
    locations: Sequence[dict] | None = None,
) -> tuple[Practice, list[Location]]:
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

    created: list[Location] = []
    if locations:
        for loc in locations:
            loc_name = str(loc.get("name") or "").strip()
            if not loc_name:
                continue
            location = Location(
                practice_id=practice.id,
                name=loc_name,
                address=(str(loc.get("address") or "").strip() or practice.address),
                address_line2=str(loc.get("address_line2") or "").strip(),
                city=(str(loc.get("city") or "").strip() or practice.city),
                state=(str(loc.get("state") or "").strip() or practice.state),
                zip_code=(str(loc.get("zip_code") or "").strip() or practice.zip_code),
                phone=(str(loc.get("phone") or "").strip() or practice.phone),
                email=str(loc.get("email") or "").strip(),
            )
            db.add(location)
            created.append(location)

    if not created:
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
        created.append(location)

    await db.flush()
    return practice, created


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


async def delete_location(db: AsyncSession, location: Location) -> None:
    await db.delete(location)
    await db.flush()


async def delete_practice(db: AsyncSession, practice: Practice) -> None:
    await db.delete(practice)
    await db.flush()


async def list_practice_locations(
    db: AsyncSession, practice_id: uuid.UUID
) -> list[Location]:
    result = await db.execute(
        select(Location)
        .where(Location.practice_id == practice_id)
        .order_by(Location.name)
    )
    return list(result.scalars().all())
