"""Reserve with Google — location validation and sync status management."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.location import Location

GOOGLE_RESERVE_STATUSES = {"inactive", "pending", "active", "removing", "error"}


def _format_address(location: Location) -> str:
    parts = [location.address, location.city, location.state, location.zip_code]
    return ", ".join(p.strip() for p in parts if p and p.strip())


def validate_location_for_google(location: Location) -> str | None:
    """Return an error message when the location cannot be matched to Google."""
    missing: list[str] = []
    if not location.name.strip():
        missing.append("location name")
    if not location.address.strip():
        missing.append("street address")
    if not location.city.strip():
        missing.append("city")
    if not location.state.strip():
        missing.append("state")
    if not location.zip_code.strip():
        missing.append("zip code")
    if not location.phone.strip():
        missing.append("phone number")
    if missing:
        return (
            "Complete your location profile before enabling Reserve with Google: "
            + ", ".join(missing)
            + ". NexHealth matches your address on file with your Google Business Profile."
        )
    return None


def apply_reserve_with_google(location: Location, *, enabled: bool) -> None:
    if enabled:
        error = validate_location_for_google(location)
        if error:
            location.reserve_with_google = False
            location.google_reserve_status = "error"
            location.google_reserve_message = error
            raise ValueError(error)
        location.reserve_with_google = True
        location.google_reserve_status = "pending"
        location.google_reserve_message = (
            "The button will appear on your Google listings within 24 hours. "
            "If you don't see it after this time, please contact support@nexhealth.com."
        )
    else:
        location.reserve_with_google = False
        location.google_reserve_status = "removing"
        location.google_reserve_message = (
            "The online booking link should be removed from your Google listing within 24 hours."
        )


def copy_reserve_settings(source: Location, target: Location) -> None:
    target.reserve_with_google = source.reserve_with_google
    target.google_reserve_status = source.google_reserve_status
    target.google_reserve_message = source.google_reserve_message


async def get_google_reserve_feed(
    db: AsyncSession,
    *,
    slug: str,
    lid: str | None = None,
) -> list[dict] | None:
    """Public feed of locations enabled for Reserve with Google."""
    from app.services.public_booking_service import practice_slug, resolve_practice_by_slug

    practice = await resolve_practice_by_slug(db, slug)
    if practice is None:
        return None
    if lid and not str(practice.id).startswith(lid):
        return None

    result = await db.execute(
        select(Location).where(
            Location.practice_id == practice.id,
            Location.reserve_with_google.is_(True),
        )
    )
    slug_name = practice_slug(practice.name)
    lid_prefix = str(practice.id)[:8]
    entries: list[dict] = []
    for loc in result.scalars().all():
        booking_path = (
            f"/appt/{slug_name}?lid={lid_prefix}"
            f"&location_ids={loc.id}"
            f"&utm_source=google&utm_medium=reserve_with_google&utm_campaign=online_booking"
        )
        entries.append(
            {
                "location_id": str(loc.id),
                "name": loc.name,
                "formatted_address": _format_address(loc),
                "phone": loc.phone,
                "status": loc.google_reserve_status,
                "booking_path": booking_path,
            }
        )
    return entries
