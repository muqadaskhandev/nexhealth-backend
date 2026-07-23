"""Business logic for providers, operatories, and availability slots."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.staff_context import StaffContext
from app.models.providers import AvailabilityBlock, AvailabilitySlot, Operatory, Provider, ProviderStatus, RepeatMode
from app.schemas.providers import (
    AvailabilityBlockCreate,
    AvailabilityBlockUpdate,
    AvailabilitySlotCreate,
    AvailabilitySlotUpdate,
    OperatoryCreate,
    OperatoryUpdate,
    ProviderCreate,
    ProviderUpdate,
)


# ── Providers ────────────────────────────────────────────────────────────────
async def list_providers(db: AsyncSession, ctx: StaffContext) -> list[Provider]:
    result = await db.execute(
        select(Provider)
        .where(Provider.practice_id == ctx.practice_id, Provider.location_id == ctx.location_id)
        .order_by(Provider.name)
    )
    return list(result.scalars().all())


async def get_provider(db: AsyncSession, ctx: StaffContext, provider_id: uuid.UUID) -> Provider | None:
    provider = await db.get(Provider, provider_id)
    if provider is None or provider.practice_id != ctx.practice_id or provider.location_id != ctx.location_id:
        return None
    return provider


async def create_provider(db: AsyncSession, ctx: StaffContext, data: ProviderCreate) -> Provider:
    provider = Provider(
        practice_id=ctx.practice_id,
        location_id=ctx.location_id,
        name=data.name,
        role=data.role,
        status=ProviderStatus(data.status),
        default_appointment_type_ids=data.default_appointment_type_ids,
        default_insurances=data.default_insurances,
    )
    db.add(provider)
    await db.flush()
    return provider


async def update_provider(db: AsyncSession, provider: Provider, data: ProviderUpdate) -> Provider:
    if data.name is not None:
        provider.name = data.name
    if data.role is not None:
        provider.role = data.role
    if data.status is not None:
        provider.status = ProviderStatus(data.status)
    if data.default_appointment_type_ids is not None:
        provider.default_appointment_type_ids = data.default_appointment_type_ids
    if data.default_insurances is not None:
        provider.default_insurances = data.default_insurances
    await db.flush()
    return provider


async def delete_provider(db: AsyncSession, provider: Provider) -> None:
    await db.delete(provider)


# ── Operatories ──────────────────────────────────────────────────────────────
async def list_operatories(db: AsyncSession, ctx: StaffContext) -> list[Operatory]:
    result = await db.execute(
        select(Operatory)
        .where(Operatory.practice_id == ctx.practice_id, Operatory.location_id == ctx.location_id)
        .order_by(Operatory.name)
    )
    return list(result.scalars().all())


async def get_operatory(db: AsyncSession, ctx: StaffContext, operatory_id: uuid.UUID) -> Operatory | None:
    operatory = await db.get(Operatory, operatory_id)
    if operatory is None or operatory.practice_id != ctx.practice_id or operatory.location_id != ctx.location_id:
        return None
    return operatory


async def create_operatory(db: AsyncSession, ctx: StaffContext, data: OperatoryCreate) -> Operatory:
    operatory = Operatory(
        practice_id=ctx.practice_id,
        location_id=ctx.location_id,
        name=data.name,
        active=data.active,
    )
    db.add(operatory)
    await db.flush()
    return operatory


async def update_operatory(db: AsyncSession, operatory: Operatory, data: OperatoryUpdate) -> Operatory:
    if data.name is not None:
        operatory.name = data.name
    if data.active is not None:
        operatory.active = data.active
    await db.flush()
    return operatory


async def delete_operatory(db: AsyncSession, operatory: Operatory) -> None:
    await db.delete(operatory)


# ── Availability slots ───────────────────────────────────────────────────────
async def list_availability_slots(
    db: AsyncSession, ctx: StaffContext, provider_id: uuid.UUID | None = None
) -> list[AvailabilitySlot]:
    query = select(AvailabilitySlot).where(
        AvailabilitySlot.practice_id == ctx.practice_id, AvailabilitySlot.location_id == ctx.location_id
    )
    if provider_id is not None:
        query = query.where(AvailabilitySlot.provider_id == provider_id)
    result = await db.execute(query.order_by(AvailabilitySlot.created_at))
    return list(result.scalars().all())


async def get_availability_slot(
    db: AsyncSession, ctx: StaffContext, slot_id: uuid.UUID
) -> AvailabilitySlot | None:
    slot = await db.get(AvailabilitySlot, slot_id)
    if slot is None or slot.practice_id != ctx.practice_id or slot.location_id != ctx.location_id:
        return None
    return slot


async def create_availability_slot(
    db: AsyncSession, ctx: StaffContext, data: AvailabilitySlotCreate
) -> AvailabilitySlot:
    provider = await get_provider(db, ctx, data.provider_id)
    if provider is None:
        raise ValueError("Provider not found")
    if data.end_time <= data.start_time:
        raise ValueError("End time must be after start time")
    if data.operatory_id is not None:
        operatory = await get_operatory(db, ctx, data.operatory_id)
        if operatory is None:
            raise ValueError("Operatory not found")

    slot = AvailabilitySlot(
        practice_id=ctx.practice_id,
        location_id=ctx.location_id,
        provider_id=data.provider_id,
        operatory_id=data.operatory_id,
        repeat_mode=RepeatMode(data.repeat_mode),
        specific_date=data.specific_date,
        day_of_week=data.day_of_week,
        starts_on=data.starts_on,
        start_time=data.start_time,
        end_time=data.end_time,
        use_provider_defaults=data.use_provider_defaults,
        appointment_type_ids=data.appointment_type_ids,
    )
    db.add(slot)
    await db.flush()
    return slot


async def update_availability_slot(
    db: AsyncSession, ctx: StaffContext, slot: AvailabilitySlot, data: AvailabilitySlotUpdate
) -> AvailabilitySlot:
    if data.operatory_id is not None:
        operatory = await get_operatory(db, ctx, data.operatory_id)
        if operatory is None:
            raise ValueError("Operatory not found")
        slot.operatory_id = data.operatory_id
    if data.repeat_mode is not None:
        slot.repeat_mode = RepeatMode(data.repeat_mode)
    if data.specific_date is not None:
        slot.specific_date = data.specific_date
    if data.day_of_week is not None:
        slot.day_of_week = data.day_of_week
    if data.starts_on is not None:
        slot.starts_on = data.starts_on
    if data.start_time is not None:
        slot.start_time = data.start_time
    if data.end_time is not None:
        slot.end_time = data.end_time
    if data.use_provider_defaults is not None:
        slot.use_provider_defaults = data.use_provider_defaults
    if data.appointment_type_ids is not None:
        slot.appointment_type_ids = data.appointment_type_ids

    if slot.end_time <= slot.start_time:
        raise ValueError("End time must be after start time")

    await db.flush()
    return slot


async def delete_availability_slot(db: AsyncSession, slot: AvailabilitySlot) -> None:
    await db.delete(slot)


async def clone_availability_slot(
    db: AsyncSession, ctx: StaffContext, slot: AvailabilitySlot
) -> AvailabilitySlot:
    clone = AvailabilitySlot(
        practice_id=slot.practice_id,
        location_id=slot.location_id,
        provider_id=slot.provider_id,
        operatory_id=slot.operatory_id,
        repeat_mode=slot.repeat_mode,
        specific_date=slot.specific_date,
        day_of_week=slot.day_of_week,
        starts_on=slot.starts_on,
        start_time=slot.start_time,
        end_time=slot.end_time,
        use_provider_defaults=slot.use_provider_defaults,
        appointment_type_ids=slot.appointment_type_ids,
    )
    db.add(clone)
    await db.flush()
    return clone


# ── Availability blocks ──────────────────────────────────────────────────────
async def list_availability_blocks(
    db: AsyncSession, ctx: StaffContext, provider_id: uuid.UUID | None = None
) -> list[AvailabilityBlock]:
    query = select(AvailabilityBlock).where(
        AvailabilityBlock.practice_id == ctx.practice_id, AvailabilityBlock.location_id == ctx.location_id
    )
    if provider_id is not None:
        query = query.where(AvailabilityBlock.provider_id == provider_id)
    result = await db.execute(query.order_by(AvailabilityBlock.starts_at))
    return list(result.scalars().all())


async def get_availability_block(
    db: AsyncSession, ctx: StaffContext, block_id: uuid.UUID
) -> AvailabilityBlock | None:
    block = await db.get(AvailabilityBlock, block_id)
    if block is None or block.practice_id != ctx.practice_id or block.location_id != ctx.location_id:
        return None
    return block


async def create_availability_block(
    db: AsyncSession, ctx: StaffContext, data: AvailabilityBlockCreate
) -> AvailabilityBlock:
    provider = await get_provider(db, ctx, data.provider_id)
    if provider is None:
        raise ValueError("Provider not found")
    if data.ends_at <= data.starts_at:
        raise ValueError("End time must be after start time")
    if data.operatory_id is not None:
        operatory = await get_operatory(db, ctx, data.operatory_id)
        if operatory is None:
            raise ValueError("Operatory not found")

    block = AvailabilityBlock(
        practice_id=ctx.practice_id,
        location_id=ctx.location_id,
        provider_id=data.provider_id,
        operatory_id=data.operatory_id,
        starts_at=data.starts_at,
        ends_at=data.ends_at,
        notes=data.notes,
    )
    db.add(block)
    await db.flush()
    return block


async def update_availability_block(
    db: AsyncSession, ctx: StaffContext, block: AvailabilityBlock, data: AvailabilityBlockUpdate
) -> AvailabilityBlock:
    if data.operatory_id is not None:
        operatory = await get_operatory(db, ctx, data.operatory_id)
        if operatory is None:
            raise ValueError("Operatory not found")
        block.operatory_id = data.operatory_id
    if data.starts_at is not None:
        block.starts_at = data.starts_at
    if data.ends_at is not None:
        block.ends_at = data.ends_at
    if data.notes is not None:
        block.notes = data.notes

    if block.ends_at <= block.starts_at:
        raise ValueError("End time must be after start time")

    await db.flush()
    return block


async def delete_availability_block(db: AsyncSession, block: AvailabilityBlock) -> None:
    await db.delete(block)
