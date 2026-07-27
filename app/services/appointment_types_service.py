"""Business logic for appointment types, insertion rules, and mapping rules."""
from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.staff_context import StaffContext
from app.models.appointment_types import AppointmentTypeDef, InsertionRule, MappingRule, PatientTypeRule
from app.schemas.appointment_types import (
    AppointmentTypeCreate,
    AppointmentTypeUpdate,
    BulkPatientTypeUpdateItem,
    InsertionRuleIn,
    MappingRuleCreate,
    MappingRuleUpdate,
)
from app.services import user_service


async def list_appointment_types(db: AsyncSession, ctx: StaffContext) -> list[AppointmentTypeDef]:
    result = await db.execute(
        select(AppointmentTypeDef)
        .where(
            AppointmentTypeDef.practice_id == ctx.practice_id,
            AppointmentTypeDef.location_id == ctx.location_id,
        )
        .order_by(AppointmentTypeDef.position, AppointmentTypeDef.name)
    )
    types = list(result.scalars().all())
    await _attach_rules(db, types)
    return types


async def list_appointment_types_at_location(
    db: AsyncSession, ctx: StaffContext, location_id: uuid.UUID
) -> list[AppointmentTypeDef]:
    if not await user_service.user_can_access_location(db, ctx.user.id, location_id):
        raise ValueError("No access to location")
    result = await db.execute(
        select(AppointmentTypeDef)
        .where(
            AppointmentTypeDef.practice_id == ctx.practice_id,
            AppointmentTypeDef.location_id == location_id,
        )
        .order_by(AppointmentTypeDef.position, AppointmentTypeDef.name)
    )
    types = list(result.scalars().all())
    await _attach_rules(db, types)
    return types


async def bulk_update_patient_types(
    db: AsyncSession,
    ctx: StaffContext,
    location_id: uuid.UUID,
    updates: list[BulkPatientTypeUpdateItem],
) -> int:
    if not await user_service.user_can_access_location(db, ctx.user.id, location_id):
        raise ValueError("No access to location")
    updated = 0
    for item in updates:
        at = await db.get(AppointmentTypeDef, item.id)
        if at is None or at.practice_id != ctx.practice_id or at.location_id != location_id:
            raise ValueError(f"Appointment type not found: {item.id}")
        at.patient_type = PatientTypeRule(item.patient_type)
        updated += 1
    await db.flush()
    return updated


async def _attach_rules(db: AsyncSession, types: list[AppointmentTypeDef]) -> None:
    """Manually load insertion rules per type (no ORM relationship declared —
    keeps the two models decoupled, matching this app's preference for
    explicit queries over relationship magic elsewhere in staff_service.py)."""
    if not types:
        return
    ids = [t.id for t in types]
    result = await db.execute(select(InsertionRule).where(InsertionRule.appointment_type_id.in_(ids)))
    rules_by_type: dict[uuid.UUID, list[InsertionRule]] = {}
    for rule in result.scalars().all():
        rules_by_type.setdefault(rule.appointment_type_id, []).append(rule)
    for t in types:
        t.insertion_rules = rules_by_type.get(t.id, [])  # type: ignore[attr-defined]


async def get_appointment_type(
    db: AsyncSession, ctx: StaffContext, appointment_type_id: uuid.UUID
) -> AppointmentTypeDef | None:
    at = await db.get(AppointmentTypeDef, appointment_type_id)
    if at is None or at.practice_id != ctx.practice_id or at.location_id != ctx.location_id:
        return None
    await _attach_rules(db, [at])
    return at


async def _replace_insertion_rules(
    db: AsyncSession, appointment_type_id: uuid.UUID, rules: list
) -> None:
    await db.execute(delete(InsertionRule).where(InsertionRule.appointment_type_id == appointment_type_id))
    for rule in rules:
        db.add(InsertionRule(appointment_type_id=appointment_type_id, code_type=rule.code_type, codes=rule.codes))


async def create_appointment_type(
    db: AsyncSession, ctx: StaffContext, data: AppointmentTypeCreate
) -> AppointmentTypeDef:
    result = await db.execute(
        select(AppointmentTypeDef.position)
        .where(
            AppointmentTypeDef.practice_id == ctx.practice_id,
            AppointmentTypeDef.location_id == ctx.location_id,
        )
        .order_by(AppointmentTypeDef.position.desc())
        .limit(1)
    )
    max_position = result.scalar_one_or_none()
    at = AppointmentTypeDef(
        practice_id=ctx.practice_id,
        location_id=ctx.location_id,
        name=data.name,
        duration_minutes=data.duration_minutes,
        available_online=data.available_online,
        patient_type=PatientTypeRule(data.patient_type),
        allow_patient_cancel=data.allow_patient_cancel,
        position=(max_position + 1) if max_position is not None else 0,
    )
    db.add(at)
    await db.flush()
    await _replace_insertion_rules(db, at.id, data.insertion_rules)
    await db.flush()
    await _attach_rules(db, [at])
    return at


async def update_appointment_type(
    db: AsyncSession, at: AppointmentTypeDef, data: AppointmentTypeUpdate
) -> AppointmentTypeDef:
    if data.name is not None:
        at.name = data.name
    if data.duration_minutes is not None:
        at.duration_minutes = data.duration_minutes
    if data.available_online is not None:
        at.available_online = data.available_online
    if data.patient_type is not None:
        at.patient_type = PatientTypeRule(data.patient_type)
    if data.allow_patient_cancel is not None:
        at.allow_patient_cancel = data.allow_patient_cancel
    if data.insertion_rules is not None:
        await _replace_insertion_rules(db, at.id, data.insertion_rules)
    await db.flush()
    await _attach_rules(db, [at])
    return at


async def delete_appointment_type(db: AsyncSession, at: AppointmentTypeDef) -> None:
    await db.delete(at)


async def reorder_appointment_types(
    db: AsyncSession, ctx: StaffContext, ordered_ids: list[uuid.UUID]
) -> list[AppointmentTypeDef]:
    types = await list_appointment_types(db, ctx)
    by_id = {t.id: t for t in types}
    missing = [i for i in ordered_ids if i not in by_id]
    if missing:
        raise ValueError(f"Appointment type(s) not found: {', '.join(str(i) for i in missing)}")
    if len(ordered_ids) != len(types):
        raise ValueError("ordered_ids must include every appointment type for this location")
    for position, type_id in enumerate(ordered_ids):
        by_id[type_id].position = position
    await db.flush()
    return await list_appointment_types(db, ctx)


# ── Mapping rules ──────────────────────────────────────────────────────────
async def list_mapping_rules(db: AsyncSession, ctx: StaffContext) -> list[MappingRule]:
    result = await db.execute(
        select(MappingRule)
        .where(MappingRule.practice_id == ctx.practice_id, MappingRule.location_id == ctx.location_id)
        .order_by(MappingRule.position)
    )
    return list(result.scalars().all())


async def get_mapping_rule(db: AsyncSession, ctx: StaffContext, rule_id: uuid.UUID) -> MappingRule | None:
    rule = await db.get(MappingRule, rule_id)
    if rule is None or rule.practice_id != ctx.practice_id or rule.location_id != ctx.location_id:
        return None
    return rule


async def create_mapping_rule(
    db: AsyncSession, ctx: StaffContext, data: MappingRuleCreate
) -> MappingRule:
    target = await get_appointment_type(db, ctx, data.target_appointment_type_id)
    if target is None:
        raise ValueError("Target appointment type not found")
    result = await db.execute(
        select(MappingRule.position)
        .where(MappingRule.practice_id == ctx.practice_id, MappingRule.location_id == ctx.location_id)
        .order_by(MappingRule.position.desc())
        .limit(1)
    )
    max_position = result.scalar_one_or_none()
    rule = MappingRule(
        practice_id=ctx.practice_id,
        location_id=ctx.location_id,
        target_appointment_type_id=data.target_appointment_type_id,
        conditions=[c.model_dump() for c in data.conditions],
        position=(max_position + 1) if max_position is not None else 0,
    )
    db.add(rule)
    await db.flush()
    return rule


async def update_mapping_rule(
    db: AsyncSession, ctx: StaffContext, rule: MappingRule, data: MappingRuleUpdate
) -> MappingRule:
    if data.target_appointment_type_id is not None:
        target = await get_appointment_type(db, ctx, data.target_appointment_type_id)
        if target is None:
            raise ValueError("Target appointment type not found")
        rule.target_appointment_type_id = data.target_appointment_type_id
    if data.conditions is not None:
        rule.conditions = [c.model_dump() for c in data.conditions]
    await db.flush()
    return rule


async def delete_mapping_rule(db: AsyncSession, rule: MappingRule) -> None:
    await db.delete(rule)


async def copy_appointment_types(
    db: AsyncSession, ctx: StaffContext, appointment_type_ids: list[uuid.UUID], location_ids: list[uuid.UUID]
) -> int:
    result = await db.execute(
        select(AppointmentTypeDef).where(
            AppointmentTypeDef.id.in_(appointment_type_ids),
            AppointmentTypeDef.practice_id == ctx.practice_id,
            AppointmentTypeDef.location_id == ctx.location_id,
        )
    )
    sources = list(result.scalars().all())
    if len(sources) != len(set(appointment_type_ids)):
        raise ValueError("Some appointment types could not be found in your current location")

    target_locations = [lid for lid in dict.fromkeys(location_ids) if lid != ctx.location_id]
    if not target_locations:
        raise ValueError("Select at least one other location to copy to")

    copied = 0
    for loc_id in target_locations:
        for src in sources:
            existing_result = await db.execute(
                select(AppointmentTypeDef).where(
                    AppointmentTypeDef.practice_id == ctx.practice_id,
                    AppointmentTypeDef.location_id == loc_id,
                    AppointmentTypeDef.name == src.name,
                )
            )
            existing = existing_result.scalar_one_or_none()
            if existing:
                existing.duration_minutes = src.duration_minutes
                existing.available_online = src.available_online
                existing.patient_type = src.patient_type
                existing.allow_patient_cancel = src.allow_patient_cancel
                target = existing
            else:
                target = AppointmentTypeDef(
                    practice_id=ctx.practice_id,
                    location_id=loc_id,
                    name=src.name,
                    duration_minutes=src.duration_minutes,
                    available_online=src.available_online,
                    patient_type=src.patient_type,
                    allow_patient_cancel=src.allow_patient_cancel,
                )
                db.add(target)
                await db.flush()

            rules_result = await db.execute(
                select(InsertionRule).where(InsertionRule.appointment_type_id == src.id)
            )
            await _replace_insertion_rules(
                db,
                target.id,
                [
                    InsertionRuleIn(code_type=r.code_type, codes=r.codes)
                    for r in rules_result.scalars().all()
                ],
            )
            copied += 1
    await db.flush()
    return copied


async def copy_mapping_rules(
    db: AsyncSession, ctx: StaffContext, rule_ids: list[uuid.UUID], location_ids: list[uuid.UUID]
) -> int:
    result = await db.execute(
        select(MappingRule).where(
            MappingRule.id.in_(rule_ids),
            MappingRule.practice_id == ctx.practice_id,
            MappingRule.location_id == ctx.location_id,
        )
    )
    sources = list(result.scalars().all())
    if len(sources) != len(set(rule_ids)):
        raise ValueError("Some mapping rules could not be found in your current location")

    target_locations = [lid for lid in dict.fromkeys(location_ids) if lid != ctx.location_id]
    if not target_locations:
        raise ValueError("Select at least one other location to copy to")

    copied = 0
    for loc_id in target_locations:
        for src in sources:
            target_type = await get_appointment_type(db, ctx, src.target_appointment_type_id)
            if target_type is None:
                continue
            dest_type_result = await db.execute(
                select(AppointmentTypeDef).where(
                    AppointmentTypeDef.practice_id == ctx.practice_id,
                    AppointmentTypeDef.location_id == loc_id,
                    AppointmentTypeDef.name == target_type.name,
                )
            )
            dest_type = dest_type_result.scalar_one_or_none()
            if dest_type is None:
                continue

            pos_result = await db.execute(
                select(MappingRule.position)
                .where(MappingRule.practice_id == ctx.practice_id, MappingRule.location_id == loc_id)
                .order_by(MappingRule.position.desc())
                .limit(1)
            )
            max_position = pos_result.scalar_one_or_none()

            db.add(
                MappingRule(
                    practice_id=ctx.practice_id,
                    location_id=loc_id,
                    target_appointment_type_id=dest_type.id,
                    conditions=src.conditions,
                    position=(max_position + 1) if max_position is not None else 0,
                )
            )
            copied += 1
    await db.flush()
    return copied


async def reorder_mapping_rules(
    db: AsyncSession, ctx: StaffContext, ordered_ids: list[uuid.UUID]
) -> list[MappingRule]:
    rules = await list_mapping_rules(db, ctx)
    by_id = {r.id: r for r in rules}
    missing = [i for i in ordered_ids if i not in by_id]
    if missing:
        raise ValueError(f"Mapping rule(s) not found: {', '.join(str(i) for i in missing)}")
    for position, rule_id in enumerate(ordered_ids):
        by_id[rule_id].position = position
    await db.flush()
    return await list_mapping_rules(db, ctx)
