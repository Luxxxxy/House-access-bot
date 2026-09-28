from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import VisitCreate
from app.api.v1.common import get_resident_complex
from app.domain.logic import (
    active_guard_ids,
    enqueue_notification,
    ensure_local_today,
    serialize_request,
    serialize_requests,
)
from app.domain.models import (
    Account,
    Apartment,
    Building,
    Checkpoint,
    ResidentApartment,
    VisitEvent,
    VisitRequest,
)
from app.security.auth import require_role
from app.web.db import get_session

router = APIRouter(tags=["resident"])


@router.get("/resident/apartments")
async def resident_apartments(
    account: Account = Depends(require_role("RESIDENT")),
    session: AsyncSession = Depends(get_session),
):
    rows = await session.execute(
        select(Apartment, Building)
        .join(Building, Building.id == Apartment.building_id)
        .join(ResidentApartment, ResidentApartment.apartment_id == Apartment.id)
        .where(ResidentApartment.user_id == account.max_user_id, Apartment.is_active.is_(True))
        .order_by(Building.name, Apartment.number)
    )
    return [
        {"id": str(apt.id), "number": apt.number, "building": building.name}
        for apt, building in rows
    ]


@router.get("/resident/checkpoints")
async def resident_checkpoints(
    account: Account = Depends(require_role("RESIDENT")),
    session: AsyncSession = Depends(get_session),
    apartment_id: UUID | None = None,
):
    complex_obj = None
    if apartment_id:
        complex_obj = await get_resident_complex(session, account.max_user_id, apartment_id)
        if complex_obj is None:
            raise HTTPException(403, "Квартира не связана с этим жильцом")
    if complex_obj:
        rows = await session.execute(
            select(Checkpoint)
            .where(Checkpoint.complex_id == complex_obj.id, Checkpoint.is_active.is_(True))
            .order_by(Checkpoint.name)
        )
    else:
        rows = await session.execute(
            select(Checkpoint)
            .join(Building, Building.complex_id == Checkpoint.complex_id)
            .join(Apartment, Apartment.building_id == Building.id)
            .join(ResidentApartment, ResidentApartment.apartment_id == Apartment.id)
            .where(ResidentApartment.user_id == account.max_user_id, Checkpoint.is_active.is_(True))
            .distinct()
            .order_by(Checkpoint.name)
        )
    return [{"id": str(cp.id), "name": cp.name} for cp in rows.scalars()]


@router.post("/visit-requests", status_code=status.HTTP_201_CREATED)
async def create_visit_request(
    body: VisitCreate,
    account: Account = Depends(require_role("RESIDENT")),
    session: AsyncSession = Depends(get_session),
):
    complex_obj = await get_resident_complex(session, account.max_user_id, body.apartment_id)
    if complex_obj is None:
        raise HTTPException(403, "Квартира не связана с этим жильцом")
    checkpoint = await session.get(Checkpoint, body.checkpoint_id)
    if checkpoint is None or not checkpoint.is_active or checkpoint.complex_id != complex_obj.id:
        raise HTTPException(422, "Выбранный КПП не относится к вашему ЖК")
    apartment = await session.get(Apartment, body.apartment_id)
    if apartment is None or not apartment.is_active:
        raise HTTPException(404, "Квартира не найдена")

    now = datetime.now(timezone.utc)
    arrival = ensure_local_today(body.estimated_arrival_at, now, complex_obj.timezone)
    contact = (body.resident_contact or account.default_contact or "").strip()
    if not contact:
        raise HTTPException(422, "Укажите контакт для этой заявки")

    visit = VisitRequest(
        complex_id=complex_obj.id,
        resident_id=account.max_user_id,
        apartment_id=apartment.id,
        checkpoint_id=checkpoint.id,
        visitor_type=body.visitor_type,
        visitor_name=body.visitor_name.strip(),
        visitor_car_number=body.visitor_car_number.strip() if body.visitor_car_number else None,
        resident_contact=contact,
        estimated_arrival_at=arrival,
        comment=body.comment,
        status="ACTIVE",
        is_pinned=False,
    )
    session.add(visit)
    await session.flush()
    session.add(
        VisitEvent(
            request_id=visit.id,
            actor_id=account.max_user_id,
            event_type="CREATED",
            metadata_json={"checkpoint_id": str(checkpoint.id)},
        )
    )
    guard_ids = await active_guard_ids(session, checkpoint.id, now)
    for guard_id in guard_ids:
        building = await session.get(Building, apartment.building_id)
        await enqueue_notification(
            session,
            recipient_id=guard_id,
            request_id=visit.id,
            dedupe_key=f"visit:{visit.id}:created:guard:{guard_id}",
            text=(
                f"Новая заявка: {visit.visitor_name}. "
                f"Квартира {apartment.number}, корпус {building.name if building else '—'}."
            ),
        )
    await session.commit()
    await session.refresh(visit)
    data = await serialize_request(session, visit)
    data["notified_guards"] = len(guard_ids)
    return data


@router.get("/visit-requests")
async def resident_visit_requests(
    account: Account = Depends(require_role("RESIDENT")),
    session: AsyncSession = Depends(get_session),
    history: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=100),
):
    states = ("PASSED", "REJECTED", "CANCELLED", "EXPIRED") if history else ("ACTIVE",)
    requests = await session.scalars(
        select(VisitRequest)
        .where(VisitRequest.resident_id == account.max_user_id, VisitRequest.status.in_(states))
        .order_by(VisitRequest.created_at.desc())
        .limit(limit)
    )
    included = []
    for visit in requests:
        if history and visit.created_at:
            created_at = visit.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            if created_at < datetime.now(timezone.utc) - timedelta(days=14):
                continue
        included.append(visit)
    return await serialize_requests(session, included)


@router.get("/visit-requests/{request_id}")
async def resident_visit_detail(
    request_id: UUID,
    account: Account = Depends(require_role("RESIDENT")),
    session: AsyncSession = Depends(get_session),
):
    visit = await session.get(VisitRequest, request_id)
    if visit is None or visit.resident_id != account.max_user_id or visit.status == "DELETED":
        raise HTTPException(404, "Заявка не найдена")
    return await serialize_request(session, visit)


@router.post("/visit-requests/{request_id}/cancel")
async def cancel_visit_request(
    request_id: UUID,
    account: Account = Depends(require_role("RESIDENT")),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        update(VisitRequest)
        .where(
            VisitRequest.id == request_id,
            VisitRequest.resident_id == account.max_user_id,
            VisitRequest.status == "ACTIVE",
        )
        .values(status="CANCELLED", resolved_at=datetime.now(timezone.utc))
    )
    if result.rowcount != 1:
        await session.rollback()
        raise HTTPException(409, "Заявка уже обработана или недоступна")
    session.add(
        VisitEvent(
            request_id=request_id,
            actor_id=account.max_user_id,
            event_type="CANCELLED",
            metadata_json={},
        )
    )
    await session.commit()
    return {"status": "CANCELLED"}
