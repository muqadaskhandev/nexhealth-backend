"""Business logic for custom online booking form fields and insurances."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.staff_context import StaffContext
from app.models.booking_form import BookingFieldType, BookingFormField, BookingInsurance
from app.models.location import Location
from app.schemas.booking_form import BookingFormFieldCreate, BookingFormFieldUpdate

VALID_SHOW_TO = {"all", "new", "existing"}

DEFAULT_BOOKING_INSURANCES = [
    "Aetna",
    "Anthem",
    "Blue Cross Blue Shield",
    "Cigna",
    "Humana",
    "Kaiser Permanente",
    "MetLife",
    "United Healthcare",
    "Delta Dental",
    "Guardian",
]


def _validate_field(field_type: str, show_to: str, note_text: str, options: list[str]) -> None:
    if show_to not in VALID_SHOW_TO:
        raise ValueError(f"Invalid show_to: {show_to}")
    if field_type == BookingFieldType.NOTE.value and not note_text.strip():
        raise ValueError("Note fields require note text")
    if field_type in (BookingFieldType.SINGLE_SELECT.value, BookingFieldType.MULTI_SELECT.value) and not options:
        raise ValueError("Select fields require at least one option")


# ── Form fields ──────────────────────────────────────────────────────────────
async def list_form_fields(db: AsyncSession, ctx: StaffContext) -> list[BookingFormField]:
    result = await db.execute(
        select(BookingFormField)
        .where(BookingFormField.practice_id == ctx.practice_id, BookingFormField.location_id == ctx.location_id)
        .order_by(BookingFormField.position)
    )
    return list(result.scalars().all())


async def get_form_field(db: AsyncSession, ctx: StaffContext, field_id: uuid.UUID) -> BookingFormField | None:
    field = await db.get(BookingFormField, field_id)
    if field is None or field.practice_id != ctx.practice_id or field.location_id != ctx.location_id:
        return None
    return field


async def _practice_location_ids(db: AsyncSession, practice_id: uuid.UUID) -> list[uuid.UUID]:
    result = await db.execute(select(Location.id).where(Location.practice_id == practice_id))
    return list(result.scalars().all())


async def _next_field_position(db: AsyncSession, practice_id: uuid.UUID, location_id: uuid.UUID) -> int:
    result = await db.execute(
        select(BookingFormField.position)
        .where(BookingFormField.practice_id == practice_id, BookingFormField.location_id == location_id)
        .order_by(BookingFormField.position.desc())
        .limit(1)
    )
    max_position = result.scalar_one_or_none()
    return (max_position + 1) if max_position is not None else 0


def _build_field(
    *,
    practice_id: uuid.UUID,
    location_id: uuid.UUID,
    data: BookingFormFieldCreate,
    position: int,
) -> BookingFormField:
    return BookingFormField(
        practice_id=practice_id,
        location_id=location_id,
        field_type=BookingFieldType(data.field_type),
        label=data.label,
        show_to=data.show_to,
        required=data.required,
        note_text=data.note_text,
        options=data.options,
        position=position,
    )


async def _upsert_field_at_location(
    db: AsyncSession,
    *,
    practice_id: uuid.UUID,
    location_id: uuid.UUID,
    data: BookingFormFieldCreate,
) -> BookingFormField:
    result = await db.execute(
        select(BookingFormField).where(
            BookingFormField.practice_id == practice_id,
            BookingFormField.location_id == location_id,
            BookingFormField.label == data.label,
            BookingFormField.field_type == BookingFieldType(data.field_type),
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.show_to = data.show_to
        existing.required = data.required
        existing.note_text = data.note_text
        existing.options = data.options
        await db.flush()
        return existing

    position = await _next_field_position(db, practice_id, location_id)
    field = _build_field(practice_id=practice_id, location_id=location_id, data=data, position=position)
    db.add(field)
    await db.flush()
    return field


async def create_form_field(
    db: AsyncSession, ctx: StaffContext, data: BookingFormFieldCreate
) -> BookingFormField:
    _validate_field(data.field_type, data.show_to, data.note_text, data.options)

    field = await _upsert_field_at_location(
        db, practice_id=ctx.practice_id, location_id=ctx.location_id, data=data
    )

    if data.add_to_all_locations:
        for loc_id in await _practice_location_ids(db, ctx.practice_id):
            if loc_id == ctx.location_id:
                continue
            await _upsert_field_at_location(db, practice_id=ctx.practice_id, location_id=loc_id, data=data)

    return field


async def update_form_field(
    db: AsyncSession, field: BookingFormField, data: BookingFormFieldUpdate
) -> BookingFormField:
    field_type = data.field_type if data.field_type is not None else field.field_type.value
    show_to = data.show_to if data.show_to is not None else field.show_to
    note_text = data.note_text if data.note_text is not None else field.note_text
    options = data.options if data.options is not None else field.options
    _validate_field(field_type, show_to, note_text, options)

    if data.field_type is not None:
        field.field_type = BookingFieldType(data.field_type)
    if data.label is not None:
        field.label = data.label
    if data.show_to is not None:
        field.show_to = data.show_to
    if data.required is not None:
        field.required = data.required
    if data.note_text is not None:
        field.note_text = data.note_text
    if data.options is not None:
        field.options = data.options

    await db.flush()
    return field


async def delete_form_field(db: AsyncSession, field: BookingFormField) -> None:
    await db.delete(field)


async def reorder_form_fields(
    db: AsyncSession, ctx: StaffContext, ordered_ids: list[uuid.UUID]
) -> list[BookingFormField]:
    fields = await list_form_fields(db, ctx)
    by_id = {f.id: f for f in fields}
    missing = [i for i in ordered_ids if i not in by_id]
    if missing:
        raise ValueError(f"Form field(s) not found: {', '.join(str(i) for i in missing)}")
    for position, field_id in enumerate(ordered_ids):
        by_id[field_id].position = position
    await db.flush()
    return await list_form_fields(db, ctx)


# ── Insurances ───────────────────────────────────────────────────────────────
async def list_insurances(db: AsyncSession, ctx: StaffContext) -> list[BookingInsurance]:
    result = await db.execute(
        select(BookingInsurance)
        .where(BookingInsurance.practice_id == ctx.practice_id, BookingInsurance.location_id == ctx.location_id)
        .order_by(BookingInsurance.name)
    )
    return list(result.scalars().all())


async def get_insurance(db: AsyncSession, ctx: StaffContext, insurance_id: uuid.UUID) -> BookingInsurance | None:
    insurance = await db.get(BookingInsurance, insurance_id)
    if insurance is None or insurance.practice_id != ctx.practice_id or insurance.location_id != ctx.location_id:
        return None
    return insurance


async def create_insurance(db: AsyncSession, ctx: StaffContext, name: str) -> BookingInsurance:
    insurance = BookingInsurance(practice_id=ctx.practice_id, location_id=ctx.location_id, name=name)
    db.add(insurance)
    await db.flush()
    return insurance


async def bulk_create_insurances(
    db: AsyncSession, ctx: StaffContext, names: list[str], *, copy_to_all_locations: bool = False
) -> list[BookingInsurance]:
    added = await _bulk_create_insurances_at_location(db, ctx.practice_id, ctx.location_id, names)

    if copy_to_all_locations:
        for loc_id in await _practice_location_ids(db, ctx.practice_id):
            if loc_id == ctx.location_id:
                continue
            await _bulk_create_insurances_at_location(db, ctx.practice_id, loc_id, names)

    return added


async def _bulk_create_insurances_at_location(
    db: AsyncSession, practice_id: uuid.UUID, location_id: uuid.UUID, names: list[str]
) -> list[BookingInsurance]:
    result = await db.execute(
        select(BookingInsurance).where(
            BookingInsurance.practice_id == practice_id,
            BookingInsurance.location_id == location_id,
        )
    )
    existing = list(result.scalars().all())
    existing_names = {i.name.strip().lower() for i in existing}
    added: list[BookingInsurance] = []
    for raw_name in names:
        name = raw_name.strip()
        if not name or name.lower() in existing_names:
            continue
        existing_names.add(name.lower())
        insurance = BookingInsurance(practice_id=practice_id, location_id=location_id, name=name)
        db.add(insurance)
        added.append(insurance)
    await db.flush()
    return added


async def copy_insurances_to_locations(
    db: AsyncSession, ctx: StaffContext, location_ids: list[uuid.UUID]
) -> int:
    sources = await list_insurances(db, ctx)
    if not sources:
        raise ValueError("Add at least one insurance to copy")

    target_locations = [lid for lid in dict.fromkeys(location_ids) if lid != ctx.location_id]
    if not target_locations:
        raise ValueError("Select at least one other location to copy to")

    copied = 0
    names = [s.name for s in sources]
    for loc_id in target_locations:
        added = await _bulk_create_insurances_at_location(db, ctx.practice_id, loc_id, names)
        copied += len(added)
    return copied


async def restore_default_insurances(db: AsyncSession, ctx: StaffContext) -> list[BookingInsurance]:
    result = await db.execute(
        select(BookingInsurance).where(
            BookingInsurance.practice_id == ctx.practice_id,
            BookingInsurance.location_id == ctx.location_id,
        )
    )
    for row in result.scalars().all():
        await db.delete(row)
    await db.flush()

    added: list[BookingInsurance] = []
    for name in DEFAULT_BOOKING_INSURANCES:
        insurance = BookingInsurance(practice_id=ctx.practice_id, location_id=ctx.location_id, name=name)
        db.add(insurance)
        added.append(insurance)
    await db.flush()
    return added


async def delete_insurance(db: AsyncSession, insurance: BookingInsurance) -> None:
    await db.delete(insurance)
