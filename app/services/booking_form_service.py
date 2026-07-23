"""Business logic for custom online booking form fields and insurances."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.staff_context import StaffContext
from app.models.booking_form import BookingFieldType, BookingFormField, BookingInsurance
from app.schemas.booking_form import BookingFormFieldCreate, BookingFormFieldUpdate

VALID_SHOW_TO = {"all", "new", "existing"}


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


async def create_form_field(
    db: AsyncSession, ctx: StaffContext, data: BookingFormFieldCreate
) -> BookingFormField:
    _validate_field(data.field_type, data.show_to, data.note_text, data.options)

    result = await db.execute(
        select(BookingFormField.position)
        .where(BookingFormField.practice_id == ctx.practice_id, BookingFormField.location_id == ctx.location_id)
        .order_by(BookingFormField.position.desc())
        .limit(1)
    )
    max_position = result.scalar_one_or_none()
    field = BookingFormField(
        practice_id=ctx.practice_id,
        location_id=ctx.location_id,
        field_type=BookingFieldType(data.field_type),
        label=data.label,
        show_to=data.show_to,
        required=data.required,
        note_text=data.note_text,
        options=data.options,
        position=(max_position + 1) if max_position is not None else 0,
    )
    db.add(field)
    await db.flush()
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
    db: AsyncSession, ctx: StaffContext, names: list[str]
) -> list[BookingInsurance]:
    existing = await list_insurances(db, ctx)
    existing_names = {i.name.strip().lower() for i in existing}
    added: list[BookingInsurance] = []
    for raw_name in names:
        name = raw_name.strip()
        if not name or name.lower() in existing_names:
            continue
        existing_names.add(name.lower())
        insurance = BookingInsurance(practice_id=ctx.practice_id, location_id=ctx.location_id, name=name)
        db.add(insurance)
        added.append(insurance)
    await db.flush()
    return added


async def delete_insurance(db: AsyncSession, insurance: BookingInsurance) -> None:
    await db.delete(insurance)
