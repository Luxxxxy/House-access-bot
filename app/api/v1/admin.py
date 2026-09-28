from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings

from app.api.schemas import (
    CheckpointCreate,
    GuardActive,
    GuardReview,
    InviteCreate,
    ShiftCreate,
)
from app.domain.logic import admin_complex_ids, hash_invite
from app.domain.models import (
    Account,
    Apartment,
    AuditEvent,
    Building,
    Checkpoint,
    GuardCheckpoint,
    GuardInvite,
    GuardProfile,
    GuardShift,
    ResidentApartment,
    VisitRequest,
)
from app.security.auth import require_role
from app.web.db import get_session

router = APIRouter(prefix="/admin", tags=["admin"])


def _audit(session: AsyncSession, complex_id, actor_id: int, action: str, target_id=None, metadata=None) -> None:
    session.add(
        AuditEvent(
            complex_id=complex_id,
            actor_id=actor_id,
            action=action,
            target_id=str(target_id) if target_id is not None else None,
            metadata_json=metadata or {},
        )
    )


async def _complex_id(session: AsyncSession, user_id: int):
    values = await admin_complex_ids(session, user_id)
    if not values:
        raise HTTPException(403, "No residential complex is assigned to this administrator")
    return values[0]


@router.get("/dashboard")
async def dashboard(
    account: Account = Depends(require_role("ADMIN")),
    session: AsyncSession = Depends(get_session),
):
    complex_id = await _complex_id(session, account.max_user_id)
    residents = await session.scalar(
        select(func.count(func.distinct(ResidentApartment.user_id)))
        .join(Apartment, Apartment.id == ResidentApartment.apartment_id)
        .join(Building, Building.id == Apartment.building_id)
        .where(Building.complex_id == complex_id)
    )
    guards = await session.scalar(
        select(func.count(GuardProfile.user_id)).where(
            GuardProfile.complex_id == complex_id, GuardProfile.status.in_(("VERIFIED", "PENDING"))
        )
    )
    checkpoints = await session.scalars(
        select(Checkpoint).where(Checkpoint.complex_id == complex_id).order_by(Checkpoint.name)
    )
    active_visits = await session.scalar(
        select(func.count(VisitRequest.id)).where(
            VisitRequest.complex_id == complex_id, VisitRequest.status == "ACTIVE"
        )
    )
    return {
        "residents": residents or 0,
        "guards": guards or 0,
        "active_requests": active_visits or 0,
        "checkpoints": [{"id": str(cp.id), "name": cp.name, "active": cp.is_active} for cp in checkpoints],
    }


@router.get("/checkpoints")
async def list_checkpoints(
    account: Account = Depends(require_role("ADMIN")),
    session: AsyncSession = Depends(get_session),
):
    complex_id = await _complex_id(session, account.max_user_id)
    rows = await session.scalars(
        select(Checkpoint).where(Checkpoint.complex_id == complex_id).order_by(Checkpoint.name)
    )
    return [
        {"id": str(cp.id), "name": cp.name, "description": cp.description, "active": cp.is_active}
        for cp in rows
    ]


@router.post("/checkpoints", status_code=201)
async def create_checkpoint(
    body: CheckpointCreate,
    account: Account = Depends(require_role("ADMIN")),
    session: AsyncSession = Depends(get_session),
):
    complex_id = await _complex_id(session, account.max_user_id)
    checkpoint = Checkpoint(complex_id=complex_id, name=body.name.strip(), description=body.description)
    session.add(checkpoint)
    await session.flush()
    _audit(session, complex_id, account.max_user_id, "CHECKPOINT_CREATED", metadata={"name": body.name.strip()})
    await session.commit()
    return {"id": str(checkpoint.id), "name": checkpoint.name, "active": checkpoint.is_active}


@router.get("/guards")
async def list_guards(
    account: Account = Depends(require_role("ADMIN")),
    session: AsyncSession = Depends(get_session),
    q: str | None = Query(default=None, max_length=100),
):
    complex_id = await _complex_id(session, account.max_user_id)
    query = (
        select(Account, GuardProfile)
        .join(GuardProfile, GuardProfile.user_id == Account.max_user_id)
        .where(GuardProfile.complex_id == complex_id)
        .order_by(GuardProfile.registered_at.desc())
    )
    if q:
        query = query.where(Account.full_name.ilike(f"%{q.strip()}%"))
    rows = await session.execute(query.limit(200))
    output = []
    for person, profile in rows:
        cp_rows = await session.scalars(
            select(Checkpoint)
            .join(GuardCheckpoint, GuardCheckpoint.checkpoint_id == Checkpoint.id)
            .where(GuardCheckpoint.user_id == person.max_user_id)
        )
        output.append(
            {
                "user_id": person.max_user_id,
                "full_name": person.full_name,
                "username": person.username,
                "status": "DEACTIVATED" if not person.is_active else profile.status,
                "checkpoints": [{"id": str(cp.id), "name": cp.name} for cp in cp_rows],
                "registered_at": profile.registered_at.isoformat(),
                "verified_at": profile.verified_at.isoformat() if profile.verified_at else None,
            }
        )
    return output


@router.post("/guard-invites", status_code=201)
async def create_guard_invite(
    body: InviteCreate,
    account: Account = Depends(require_role("ADMIN")),
    session: AsyncSession = Depends(get_session),
):
    complex_id = await _complex_id(session, account.max_user_id)
    checkpoint = await session.get(Checkpoint, body.checkpoint_id)
    if checkpoint is None or checkpoint.complex_id != complex_id or not checkpoint.is_active:
        raise HTTPException(422, "Выберите активный КПП своего ЖК")
    now = datetime.now(timezone.utc)
    code = secrets.token_urlsafe(32)
    # A fresh invitation for a checkpoint invalidates previous unused invitations.
    old = await session.scalars(
        select(GuardInvite).where(
            GuardInvite.checkpoint_id == checkpoint.id,
            GuardInvite.used_at.is_(None),
        )
    )
    for invite in old:
        invite.used_at = now
    invite = GuardInvite(
        code_hash=hash_invite(code),
        complex_id=complex_id,
        checkpoint_id=checkpoint.id,
        created_by=account.max_user_id,
        expires_at=now + timedelta(minutes=body.expires_in_minutes),
    )
    session.add(invite)
    await session.flush()
    _audit(
        session,
        complex_id,
        account.max_user_id,
        "GUARD_INVITED",
        invite.id,
        {"checkpoint_id": str(checkpoint.id), "expires_in_minutes": body.expires_in_minutes},
    )
    await session.commit()
    link = (
        f"https://max.ru/{settings.max_bot_name}?startapp=guard_{code}"
        if settings.max_bot_name
        else None
    )
    return {
        "id": str(invite.id),
        "code": code,
        "link": link,
        "checkpoint": checkpoint.name,
        "expires_at": invite.expires_at.isoformat(),
    }


@router.post("/guards/{user_id}/review")
async def review_guard(
    user_id: int,
    body: GuardReview,
    account: Account = Depends(require_role("ADMIN")),
    session: AsyncSession = Depends(get_session),
):
    complex_id = await _complex_id(session, account.max_user_id)
    profile = await session.get(GuardProfile, user_id)
    guard = await session.get(Account, user_id)
    if profile is None or guard is None or profile.complex_id != complex_id:
        raise HTTPException(404, "Охранник не найден")
    if profile.status not in {"PENDING", "VERIFIED", "REJECTED"}:
        raise HTTPException(409, "Регистрацию нельзя проверить в текущем статусе")
    if body.approve:
        if body.checkpoint_ids is not None:
            for checkpoint_id in body.checkpoint_ids:
                checkpoint = await session.get(Checkpoint, checkpoint_id)
                if checkpoint is None or checkpoint.complex_id != complex_id or not checkpoint.is_active:
                    raise HTTPException(422, "КПП назначения не относится к этому ЖК")
            current = await session.scalars(
                select(GuardCheckpoint).where(GuardCheckpoint.user_id == user_id)
            )
            for assignment in current:
                await session.delete(assignment)
            for checkpoint_id in set(body.checkpoint_ids):
                session.add(GuardCheckpoint(user_id=user_id, checkpoint_id=checkpoint_id))
        profile.status = "VERIFIED"
        profile.verified_by = account.max_user_id
        profile.verified_at = datetime.now(timezone.utc)
        guard.is_active = True
    else:
        profile.status = "REJECTED"
        profile.verified_by = account.max_user_id
        profile.verified_at = datetime.now(timezone.utc)
        guard.is_active = False
    _audit(
        session,
        complex_id,
        account.max_user_id,
        "GUARD_APPROVED" if body.approve else "GUARD_REJECTED",
        user_id,
    )
    await session.commit()
    return {"user_id": user_id, "status": profile.status}


@router.patch("/guards/{user_id}/active")
async def set_guard_active(
    user_id: int,
    body: GuardActive,
    account: Account = Depends(require_role("ADMIN")),
    session: AsyncSession = Depends(get_session),
):
    complex_id = await _complex_id(session, account.max_user_id)
    profile = await session.get(GuardProfile, user_id)
    guard = await session.get(Account, user_id)
    if profile is None or guard is None or profile.complex_id != complex_id:
        raise HTTPException(404, "Охранник не найден")
    if body.active and profile.status not in {"VERIFIED", "DEACTIVATED"}:
        raise HTTPException(409, "Сначала подтвердите регистрацию охранника")
    guard.is_active = body.active
    if body.active:
        profile.status = "VERIFIED"
    else:
        profile.status = "DEACTIVATED"
    _audit(session, complex_id, account.max_user_id, "GUARD_ACTIVATED" if body.active else "GUARD_DEACTIVATED", user_id)
    await session.commit()
    return {"user_id": user_id, "active": guard.is_active, "status": profile.status}


@router.get("/residents")
async def list_residents(
    account: Account = Depends(require_role("ADMIN")),
    session: AsyncSession = Depends(get_session),
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=100, ge=1, le=200),
):
    complex_id = await _complex_id(session, account.max_user_id)
    active_count = (
        select(func.count(VisitRequest.id))
        .where(
            VisitRequest.resident_id == ResidentApartment.user_id,
            VisitRequest.apartment_id == ResidentApartment.apartment_id,
            VisitRequest.status == "ACTIVE",
        )
        .correlate(ResidentApartment)
        .scalar_subquery()
    )
    query = (
        select(Account, Apartment, Building, ResidentApartment, active_count.label("active_requests"))
        .join(ResidentApartment, ResidentApartment.user_id == Account.max_user_id)
        .join(Apartment, Apartment.id == ResidentApartment.apartment_id)
        .join(Building, Building.id == Apartment.building_id)
        .where(Account.role == "RESIDENT", Building.complex_id == complex_id)
        .order_by(Account.full_name)
        .limit(limit)
    )
    if q:
        pattern = f"%{q.strip()}%"
        query = query.where(
            Account.full_name.ilike(pattern)
            | Apartment.number.ilike(pattern)
            | Building.name.ilike(pattern)
        )
    rows = await session.execute(query)
    return [
        {
            "user_id": person.max_user_id,
            "full_name": person.full_name,
            "apartment": apartment.number,
            "building": building.name,
            "is_active": person.is_active,
            "created_at": person.created_at.isoformat() if person.created_at else None,
            "active_requests": active_requests,
        }
        for person, apartment, building, _membership, active_requests in rows
    ]


@router.patch("/residents/{user_id}/active")
async def set_resident_active(
    user_id: int,
    body: GuardActive,
    account: Account = Depends(require_role("ADMIN")),
    session: AsyncSession = Depends(get_session),
):
    complex_id = await _complex_id(session, account.max_user_id)
    member = await session.scalar(
        select(ResidentApartment.user_id)
        .join(Apartment, Apartment.id == ResidentApartment.apartment_id)
        .join(Building, Building.id == Apartment.building_id)
        .where(ResidentApartment.user_id == user_id, Building.complex_id == complex_id)
    )
    resident = await session.get(Account, user_id)
    if member is None or resident is None or resident.role != "RESIDENT":
        raise HTTPException(404, "Жилец не найден")
    resident.is_active = body.active
    _audit(session, complex_id, account.max_user_id, "RESIDENT_ACTIVATED" if body.active else "RESIDENT_BLOCKED", user_id)
    await session.commit()
    return {"user_id": user_id, "is_active": resident.is_active}


@router.get("/shifts")
async def list_shifts(
    account: Account = Depends(require_role("ADMIN")),
    session: AsyncSession = Depends(get_session),
    start: datetime | None = None,
    end: datetime | None = None,
):
    complex_id = await _complex_id(session, account.max_user_id)
    query = (
        select(GuardShift, Account, Checkpoint)
        .join(Account, Account.max_user_id == GuardShift.user_id)
        .join(Checkpoint, Checkpoint.id == GuardShift.checkpoint_id)
        .where(GuardShift.complex_id == complex_id)
        .order_by(GuardShift.starts_on, GuardShift.weekday, GuardShift.start_time)
    )
    shifts = await session.execute(query.limit(500))
    return [
        {
            "id": str(shift.id),
            "guard_user_id": guard.max_user_id,
            "guard_name": guard.full_name,
            "checkpoint_id": str(cp.id),
            "checkpoint": cp.name,
            "kind": shift.kind,
            "weekday": shift.weekday,
            "starts_on": shift.starts_on.isoformat() if shift.starts_on else None,
            "ends_on": shift.ends_on.isoformat() if shift.ends_on else None,
            "start_time": shift.start_time.isoformat() if shift.start_time else None,
            "end_time": shift.end_time.isoformat() if shift.end_time else None,
            "starts_at": shift.starts_at.isoformat() if shift.starts_at else None,
            "ends_at": shift.ends_at.isoformat() if shift.ends_at else None,
            "note": shift.note,
        }
        for shift, guard, cp in shifts
        if start is None or shift.ends_at is None or shift.ends_at >= start
        if end is None or shift.starts_at is None or shift.starts_at <= end
    ]


@router.post("/shifts", status_code=201)
async def create_shift(
    body: ShiftCreate,
    account: Account = Depends(require_role("ADMIN")),
    session: AsyncSession = Depends(get_session),
):
    complex_id = await _complex_id(session, account.max_user_id)
    checkpoint = await session.get(Checkpoint, body.checkpoint_id)
    guard = await session.get(Account, body.guard_user_id)
    profile = await session.get(GuardProfile, body.guard_user_id)
    if checkpoint is None or checkpoint.complex_id != complex_id or not checkpoint.is_active:
        raise HTTPException(422, "Выберите активный КПП своего ЖК")
    if guard is None or guard.role != "GUARD" or profile is None or profile.complex_id != complex_id:
        raise HTTPException(422, "Охранник не относится к этому ЖК")
    if profile.status != "VERIFIED" or not guard.is_active:
        raise HTTPException(422, "Назначить смену можно только действующему охраннику")
    assignment = await session.get(GuardCheckpoint, (guard.max_user_id, checkpoint.id))
    if assignment is None:
        raise HTTPException(422, "Сначала назначьте охранника на выбранный КПП")
    if body.kind == "RECURRING":
        if body.weekday is None or body.start_time is None or body.end_time is None:
            raise HTTPException(422, "Для недельной смены укажите день недели и время")
        if body.starts_at or body.ends_at:
            raise HTTPException(422, "У недельной смены не задаётся разовый интервал")
        if body.starts_on and body.ends_on and body.ends_on < body.starts_on:
            raise HTTPException(422, "Дата окончания не может быть раньше даты начала")
    else:
        if body.starts_at is None or body.ends_at is None or body.ends_at <= body.starts_at:
            raise HTTPException(422, "Для разовой смены задайте корректные дату и время")
        if body.starts_at.tzinfo is None or body.ends_at.tzinfo is None:
            raise HTTPException(422, "Дата разовой смены должна содержать часовой пояс")
        if body.weekday is not None or body.start_time is not None or body.end_time is not None:
            raise HTTPException(422, "Для разовой смены используйте starts_at и ends_at")
    shift = GuardShift(
        complex_id=complex_id,
        checkpoint_id=checkpoint.id,
        user_id=guard.max_user_id,
        kind=body.kind,
        weekday=body.weekday,
        starts_on=body.starts_on,
        ends_on=body.ends_on,
        start_time=body.start_time,
        end_time=body.end_time,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        note=body.note,
        created_by=account.max_user_id,
    )
    session.add(shift)
    await session.flush()
    _audit(
        session,
        complex_id,
        account.max_user_id,
        "SHIFT_CREATED",
        shift.id,
        {"guard_user_id": guard.max_user_id, "checkpoint_id": str(checkpoint.id), "kind": shift.kind},
    )
    await session.commit()
    return {"id": str(shift.id), "kind": shift.kind}


@router.delete("/shifts/{shift_id}", status_code=204)
async def delete_shift(
    shift_id: UUID,
    account: Account = Depends(require_role("ADMIN")),
    session: AsyncSession = Depends(get_session),
):
    complex_id = await _complex_id(session, account.max_user_id)
    shift = await session.get(GuardShift, shift_id)
    if shift is None or shift.complex_id != complex_id:
        raise HTTPException(404, "Смена не найдена")
    await session.delete(shift)
    _audit(session, complex_id, account.max_user_id, "SHIFT_DELETED", shift_id)
    await session.commit()


@router.patch("/shifts/{shift_id}")
async def update_shift(
    shift_id: UUID,
    body: ShiftCreate,
    account: Account = Depends(require_role("ADMIN")),
    session: AsyncSession = Depends(get_session),
):
    complex_id = await _complex_id(session, account.max_user_id)
    shift = await session.get(GuardShift, shift_id)
    if shift is None or shift.complex_id != complex_id:
        raise HTTPException(404, "Смена не найдена")
    checkpoint = await session.get(Checkpoint, body.checkpoint_id)
    guard = await session.get(Account, body.guard_user_id)
    profile = await session.get(GuardProfile, body.guard_user_id)
    if checkpoint is None or checkpoint.complex_id != complex_id or not checkpoint.is_active:
        raise HTTPException(422, "Выберите активный КПП своего ЖК")
    if guard is None or guard.role != "GUARD" or not guard.is_active or profile is None or profile.status != "VERIFIED":
        raise HTTPException(422, "Выберите действующего охранника этого ЖК")
    if await session.get(GuardCheckpoint, (guard.max_user_id, checkpoint.id)) is None:
        raise HTTPException(422, "Охранник не назначен на этот КПП")
    if body.kind == "RECURRING":
        if body.weekday is None or body.start_time is None or body.end_time is None:
            raise HTTPException(422, "Для недельной смены укажите день недели и время")
        if body.starts_on and body.ends_on and body.ends_on < body.starts_on:
            raise HTTPException(422, "Дата окончания не может быть раньше даты начала")
        starts_at = ends_at = None
    else:
        if body.starts_at is None or body.ends_at is None or body.ends_at <= body.starts_at:
            raise HTTPException(422, "Для разовой смены задайте корректные дату и время")
        if body.starts_at.tzinfo is None or body.ends_at.tzinfo is None:
            raise HTTPException(422, "Дата разовой смены должна содержать часовой пояс")
        if body.weekday is not None or body.start_time is not None or body.end_time is not None:
            raise HTTPException(422, "Для разовой смены используйте starts_at и ends_at")
        starts_at, ends_at = body.starts_at, body.ends_at
    shift.checkpoint_id = checkpoint.id
    shift.user_id = guard.max_user_id
    shift.kind = body.kind
    shift.weekday = body.weekday if body.kind == "RECURRING" else None
    shift.starts_on = body.starts_on if body.kind == "RECURRING" else None
    shift.ends_on = body.ends_on if body.kind == "RECURRING" else None
    shift.start_time = body.start_time if body.kind == "RECURRING" else None
    shift.end_time = body.end_time if body.kind == "RECURRING" else None
    shift.starts_at = starts_at
    shift.ends_at = ends_at
    shift.note = body.note
    _audit(
        session,
        complex_id,
        account.max_user_id,
        "SHIFT_UPDATED",
        shift_id,
        {"guard_user_id": guard.max_user_id, "checkpoint_id": str(checkpoint.id), "kind": shift.kind},
    )
    await session.commit()
    return {"id": str(shift.id), "kind": shift.kind}


@router.get("/history")
async def admin_history(
    account: Account = Depends(require_role("ADMIN")),
    session: AsyncSession = Depends(get_session),
    checkpoint_id: UUID | None = None,
    state: str | None = Query(default=None, pattern="^(PASSED|REJECTED|CANCELLED|EXPIRED)$"),
    limit: int = Query(default=100, ge=1, le=200),
):
    complex_id = await _complex_id(session, account.max_user_id)
    query = (
        select(VisitRequest)
        .where(
            VisitRequest.complex_id == complex_id,
            VisitRequest.status.in_(("PASSED", "REJECTED", "CANCELLED", "EXPIRED")),
        )
        .order_by(VisitRequest.resolved_at.desc().nullslast())
        .limit(limit)
    )
    if checkpoint_id:
        query = query.where(VisitRequest.checkpoint_id == checkpoint_id)
    if state:
        query = query.where(VisitRequest.status == state)
    requests = await session.scalars(query)
    from app.domain.logic import serialize_requests

    return await serialize_requests(session, list(requests))


@router.get("/audit")
async def admin_audit_log(
    account: Account = Depends(require_role("ADMIN")),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=100, ge=1, le=200),
):
    complex_id = await _complex_id(session, account.max_user_id)
    events = await session.scalars(
        select(AuditEvent)
        .where(AuditEvent.complex_id == complex_id)
        .order_by(AuditEvent.created_at.desc())
        .limit(limit)
    )
    return [
        {
            "id": str(event.id),
            "actor_id": event.actor_id,
            "action": event.action,
            "target_id": event.target_id,
            "metadata": event.metadata_json,
            "created_at": event.created_at.isoformat() if event.created_at else None,
        }
        for event in events
    ]
