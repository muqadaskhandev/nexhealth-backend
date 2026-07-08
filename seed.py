"""Idempotent seed data: the five Better Dental locations + demo users.

Run after migrations:  python -m seed
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.config import settings
from app.core.security import hash_password
from app.database import SessionLocal
from app.models.location import Location
from app.models.user import AuthProvider, User, UserRole
from app.services import user_service

# Mirrors the LOCATIONS array in the React app (src/app/App.tsx).
LOCATIONS = [
    ("Better Dental - San Francisco", "445 Bush St., Sausalito, 94114"),
    ("Better Dental - Manhattan", "45 Rockefeller Place, New York City, NY, 10111"),
    ("Better Dental - Brooklyn", "980 Washington Ave, Brooklyn, 11225"),
    ("Better Dental - Sausalito", "420 Litho St., Sausalito, 94965"),
    ("Better Dental - Oakland", "1 Frank H. Ogawa Plaza, Oakland, 94612"),
]


async def _get_or_create_location(db, name: str, address: str) -> Location:
    result = await db.execute(select(Location).where(Location.name == name))
    loc = result.scalar_one_or_none()
    if loc is None:
        loc = Location(name=name, address=address)
        db.add(loc)
        await db.flush()
    return loc


async def seed() -> None:
    async with SessionLocal() as db:
        locations = [
            await _get_or_create_location(db, name, addr) for name, addr in LOCATIONS
        ]
        all_ids = [loc.id for loc in locations]

        # Admin — access to every location.
        admin = await user_service.get_user_by_email(db, settings.seed_admin_email)
        if admin is None:
            admin = await user_service.create_user(
                db,
                email=settings.seed_admin_email,
                first_name="Practice",
                last_name="Admin",
                role=UserRole.ADMIN,
                password_hash=hash_password(settings.seed_admin_password),
                auth_provider=AuthProvider.PASSWORD,
                email_verified=True,
                location_ids=all_ids,
            )
            print(f"[seed] created admin {admin.email}")
        else:
            print(f"[seed] admin {admin.email} already exists")

        # Demo member — access to two locations (to exercise the switcher).
        demo_email = "dr.riviera@betterdental.com"
        demo = await user_service.get_user_by_email(db, demo_email)
        if demo is None:
            demo = await user_service.create_user(
                db,
                email=demo_email,
                first_name="Nick",
                last_name="Riviera",
                role=UserRole.MEMBER,
                password_hash=hash_password("Demo1234!"),
                auth_provider=AuthProvider.PASSWORD,
                email_verified=True,
                location_ids=all_ids[2:4],  # Brooklyn + Sausalito
            )
            print(f"[seed] created demo member {demo.email} (password: Demo1234!)")
        else:
            print(f"[seed] demo member {demo.email} already exists")

        await db.commit()
    print("[seed] done")


if __name__ == "__main__":
    asyncio.run(seed())
