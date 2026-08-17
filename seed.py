"""Bootstrap platform accounts only — no demo patients or fake EHR data.

Run after migrations:
  python -m seed              # super admin + empty practice shell
  python -m seed --purge-demo   # remove legacy Simpson/demo records from DB
"""
from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import or_, select

from app.config import settings
from app.core.security import hash_password
from app.database import SessionLocal
from app.models.practice import Practice, SubscriptionPlan
from app.models.staff import Patient
from app.models.user import AccountType, AuthProvider, UserRole
from app.services import practice_service, user_service

LOCATIONS = [
    ("Better Dental - San Francisco", "445 Bush St., Sausalito, 94114"),
    ("Better Dental - Manhattan", "45 Rockefeller Place, New York City, NY, 10111"),
    ("Better Dental - Brooklyn", "980 Washington Ave, Brooklyn, 11225"),
    ("Better Dental - Sausalito", "420 Litho St., Sausalito, 94965"),
    ("Better Dental - Oakland", "1 Frank H. Ogawa Plaza, Oakland, 94612"),
]

DEMO_PATIENT_EMAIL_PATTERNS = ("%simpson%", "%flanders%", "%@example.com%")


async def purge_demo_data(db) -> None:
    """Remove legacy seed/demo patients and demo staff user."""
    demo_user = await user_service.get_user_by_email(db, "dr.riviera@betterdental.com")
    if demo_user is not None:
        await db.delete(demo_user)
        print("[purge] removed demo staff dr.riviera@betterdental.com")

    email_filters = [Patient.email.ilike(p) for p in DEMO_PATIENT_EMAIL_PATTERNS]
    result = await db.execute(
        select(Patient).where(
            or_(
                *email_filters,
                (Patient.ehr_patient_id.is_not(None) & Patient.ehr_patient_id.like("%-EHR-%")),
            )
        )
    )
    demo_patients = list(result.scalars().all())
    for patient in demo_patients:
        await db.delete(patient)
    if demo_patients:
        print(f"[purge] removed {len(demo_patients)} demo patients")


async def seed() -> None:
    async with SessionLocal() as db:
        super_email = settings.seed_super_admin_email
        super_admin = await user_service.get_user_by_email(db, super_email)
        if super_admin is None:
            super_admin = await user_service.create_user(
                db,
                email=super_email,
                first_name="Platform",
                last_name="Admin",
                role=UserRole.ADMIN,
                account_type=AccountType.SUPER_ADMIN,
                password_hash=hash_password(settings.seed_super_admin_password),
                auth_provider=AuthProvider.PASSWORD,
                email_verified=True,
            )
            print(f"[seed] created super admin {super_admin.email}")
        else:
            print(f"[seed] super admin {super_admin.email} already exists")

        result = await db.execute(select(Practice).where(Practice.name == "Better Dental"))
        practice = result.scalar_one_or_none()
        if practice is None:
            practice, main_loc = await practice_service.create_practice(
                db,
                name="Better Dental",
                address="445 Bush St.",
                city="Sausalito",
                state="CA",
                zip_code="94114",
                phone="(415) 555-0100",
                subscription_plan=SubscriptionPlan.PROFESSIONAL,
                default_location_name="Better Dental - San Francisco",
            )
            main_loc.address = LOCATIONS[0][1]
            for name, addr in LOCATIONS[1:]:
                await practice_service.create_location_for_practice(
                    db, practice, name=name, address=addr
                )
            print(f"[seed] created empty practice {practice.name}")
        else:
            print(f"[seed] practice {practice.name} already exists")

        locations = await practice_service.list_practice_locations(db, practice.id)
        all_ids = [loc.id for loc in locations]
        from app.services import staff_service

        for loc in locations:
            await staff_service.seed_starter_form_templates(db, practice.id, loc.id)
            print(f"[seed] starter forms ready for {loc.name}")

        admin = await user_service.get_user_by_email(db, settings.seed_admin_email)
        if admin is None:
            admin = await user_service.create_user(
                db,
                email=settings.seed_admin_email,
                first_name="Practice",
                last_name="Admin",
                role=UserRole.ADMIN,
                account_type=AccountType.PRACTICE,
                practice_id=practice.id,
                password_hash=hash_password(settings.seed_admin_password),
                auth_provider=AuthProvider.PASSWORD,
                email_verified=True,
                location_ids=all_ids,
            )
            print(f"[seed] created practice admin {admin.email}")
        else:
            if admin.practice_id is None:
                admin.practice_id = practice.id
                admin.account_type = AccountType.PRACTICE
            # Keep admin on every practice location so location switching works locally.
            if all_ids:
                await user_service.set_user_locations(db, admin, all_ids)
            print(f"[seed] practice admin {admin.email} already exists")

        if settings.seed_demo_data:
            print("[seed] warning: SEED_DEMO_DATA is deprecated and ignored — use real EHR sync")

        await db.commit()
    print("[seed] done")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bootstrap NexHealth database")
    parser.add_argument(
        "--purge-demo",
        action="store_true",
        help="Delete legacy Simpson/demo patients and demo staff user",
    )
    args = parser.parse_args()

    async def main() -> None:
        if args.purge_demo:
            async with SessionLocal() as db:
                await purge_demo_data(db)
                await db.commit()
            print("[purge] done")
        await seed()

    asyncio.run(main())
