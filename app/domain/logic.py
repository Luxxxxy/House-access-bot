from __future__ import annotations

import hashlib
from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import (
    Account,
    Apartment,
    Building,
    Checkpoint,
    ComplexAdmin,
    GuardCheckpoint,
    GuardProfile,
    GuardShift,
    Notification,
    ResidentialComplex,
    VisitRequest,
)
from app.domain.schedules import shift_covers_instant


def normalize_name(full_name: str) -> str:
    return " ".join(full_name.casefold().split())


def hash_invite(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


async def admin_complex_ids(session: AsyncSession, user_id: int) -> list[Any]:
    result = await session.scalars(select(ComplexAdmin.complex_id).where(ComplexAdmin.user_id == user_id))
    return list(result)


async def require_admin_complex(session: AsyncSession, user_id: int):
    complex_ids = await admin_complex_ids(session, user_id)
    if not complex_ids:
        from fastapi import HTTPException

        raise HTTPException(403, "No residential complex is assigned to this administrator")
    return complex_ids[0]


async def complex_timezone(session: AsyncSession, complex_id) -> str:
    complex_obj = await session.get(ResidentialComplex, complex_id)
    return complex_obj.timezone if complex_obj else "Europe/Moscow"


async def active_guard_ids(
    session: AsyncSession, checkpoint_id, at: datetime | None = None
) -> list[int]:
    instant = at or datetime.now(timezone.utc)
    rows = await session.execute(
        select(GuardShift, GuardProfile, Account, Checkpoint, ResidentialComplex)
        .join(GuardProfile, GuardProfile.user_id == GuardShift.user_id)
        .join(Account, Account.max_user_id == GuardShift.user_id)
        .join(Checkpoint, Checkpoint.id == GuardShift.checkpoint_id)
        .join(ResidentialComplex, ResidentialComplex.id == GuardShift.complex_id)
        .join(
            GuardCheckpoint,
            (GuardCheckpoint.user_id == GuardShift.user_id)
            & (GuardCheckpoint.checkpoint_id == GuardShift.checkpoint_id),
        )
        .where(
            GuardShift.checkpoint_id == checkpoint_id,
            GuardProfile.status == "VERIFIED",
            Account.role == "GUARD",
            Account.is_active.is_(True),
            Checkpoint.is_active.is_(True),
        )
    )
    found: set[int] = set()
    replacements: set[int] = set()
    for shift, _profile, account, _checkpoint, complex_obj in rows:
        if shift_covers_instant(
            kind=shift.kind,
            weekday=shift.weekday,
            starts_on=shift.starts_on,
            ends_on=shift.ends_on,
            start_time=shift.start_time,
            end_time=shift.end_time,
            starts_at=shift.starts_at,
            ends_at=shift.ends_at,
            at=instant,
            timezone=complex_obj.timezone,
        ):
            if shift.kind == "REPLACEMENT":
                replacements.add(account.max_user_id)
            else:
                found.add(account.max_user_id)
    return sorted(replacements or found)


async def guard_has_active_shift(
    session: AsyncSession, user_id: int, checkpoint_id, at: datetime | None = None
) -> bool:
    return user_id in await active_guard_ids(session, checkpoint_id, at)


async def guard_has_checkpoint(session: AsyncSession, user_id: int, checkpoint_id) -> bool:
    query = (
        select(GuardCheckpoint.user_id)
        .join(GuardProfile, GuardProfile.user_id == GuardCheckpoint.user_id)
        .where(
            GuardCheckpoint.user_id == user_id,
            GuardCheckpoint.checkpoint_id == checkpoint_id,
            GuardProfile.status == "VERIFIED",
        )
    )
    return await session.scalar(query) is not None


def ensure_local_today(arrival: datetime | None, now: datetime, tz: str) -> datetime | None:
    if arrival is None:
        return None
    zone = ZoneInfo(tz)
    normalized = arrival.replace(tzinfo=zone) if arrival.tzinfo is None else arrival.astimezone(zone)
    local_now = now.astimezone(zone)
    if normalized.date() != local_now.date():
        from fastapi import HTTPException

        raise HTTPException(422, "Заявку можно оформить только на текущую дату")
    return normalized.astimezone(timezone.utc)


def is_request_expired(request: VisitRequest, now: datetime, tz: str) -> bool:
    zone = ZoneInfo(tz)
    created = request.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    local_created = created.astimezone(zone)
    local_now = now.astimezone(zone)
    if (local_now - local_created).days >= 14:
        return True
    if request.status == "ACTIVE" and not request.is_pinned:
        expiry = datetime.combine(local_created.date() + timedelta(days=1), time.min, tzinfo=zone)
        return local_now >= expiry
    return False


async def enqueue_notification(
    session: AsyncSession,
    *,
    recipient_id: int,
    dedupe_key: str,
    text: str,
    request_id=None,
) -> None:
    session.add(
        Notification(
            recipient_id=recipient_id,
            request_id=request_id,
            dedupe_key=dedupe_key,
            text=text[:1500],
            status="PENDING",
            attempts=0,
            next_attempt_at=datetime.now(timezone.utc),
        )
    )


async def apartment_context(session: AsyncSession, apartment_id):
    return await session.execute(
        select(Apartment, Building, ResidentialComplex)
        .join(Building, Building.id == Apartment.building_id)
        .join(ResidentialComplex, ResidentialComplex.id == Building.complex_id)
        .where(Apartment.id == apartment_id)
    )


async def serialize_requests(
    session: AsyncSession, requests: list[VisitRequest]
) -> list[dict[str, Any]]:
    if not requests:
        return []
    account_ids = {request.resident_id for request in requests}
    account_ids.update(request.resolved_by for request in requests if request.resolved_by is not None)
    accounts = await session.scalars(select(Account).where(Account.max_user_id.in_(account_ids)))
    account_by_id = {item.max_user_id: item for item in accounts}
    checkpoint_ids = {request.checkpoint_id for request in requests}
    checkpoints = await session.scalars(select(Checkpoint).where(Checkpoint.id.in_(checkpoint_ids)))
    checkpoint_by_id = {item.id: item for item in checkpoints}
    apartment_ids = {request.apartment_id for request in requests}
    contexts = await session.execute(
        select(Apartment, Building).join(Building, Building.id == Apartment.building_id).where(
            Apartment.id.in_(apartment_ids)
        )
    )
    apartment_context_by_id = {apartment.id: (apartment, building) for apartment, building in contexts}
    result = []
    for request in requests:
        resident = account_by_id.get(request.resident_id)
        guard = account_by_id.get(request.resolved_by) if request.resolved_by is not None else None
        checkpoint = checkpoint_by_id.get(request.checkpoint_id)
        apartment_pair = apartment_context_by_id.get(request.apartment_id)
        apartment, building = apartment_pair if apartment_pair else (None, None)
        result.append(
            {
                "id": str(request.id),
                "complex_id": str(request.complex_id),
                "resident_id": request.resident_id,
                "resident_name": resident.full_name if resident else "Жилец",
                "apartment_id": str(request.apartment_id),
                "apartment": apartment.number if apartment else "",
                "building": building.name if building else "",
                "checkpoint_id": str(request.checkpoint_id),
                "checkpoint": checkpoint.name if checkpoint else "",
                "visitor_type": request.visitor_type,
                "visitor_name": request.visitor_name,
                "visitor_car_number": request.visitor_car_number,
                "resident_contact": request.resident_contact,
                "estimated_arrival_at": request.estimated_arrival_at.isoformat()
                if request.estimated_arrival_at
                else None,
                "comment": request.comment,
                "status": request.status,
                "is_pinned": request.is_pinned,
                "created_at": request.created_at.isoformat() if request.created_at else None,
                "resolved_at": request.resolved_at.isoformat() if request.resolved_at else None,
                "resolved_by": request.resolved_by,
                "resolved_by_name": guard.full_name if guard else None,
                "rejection_reason": request.rejection_reason,
            }
        )
    return result


async def serialize_request(session: AsyncSession, request: VisitRequest) -> dict[str, Any]:
    return (await serialize_requests(session, [request]))[0]
