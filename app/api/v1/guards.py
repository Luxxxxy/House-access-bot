from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import Decision, PinUpdate
from app.api.v1.common import require_guard_checkpoint
from app.domain.logic import (
    enqueue_notification,
    guard_has_active_shift,
    serialize_request,
    serialize_requests,
)
from app.domain.models import (
    Account,
    Apartment,
    Building,
    Checkpoint,
    GuardCheckpoint,
    GuardProfile,
    VisitEvent,
    VisitRequest,
)
from app.security.auth import require_role
from app.web.db import get_session

router = APIRouter(prefix="/guards", tags=["guard"])


async def _verified_guard(account: Account, session: AsyncSession) -> GuardProfile:
    profile = await session.get(GuardProfile, account.max_user_id)
    if profile is None or profile.status != "VERIFIED":
        raise HTTPException(403, "Guard account is awaiting administrator review")
    return profile


@router.get("/me")
async def guard_me(
    account: Account = Depends(require_role("GUARD")),
    session: AsyncSession = Depends(get_session),
):
    profile = await session.get(GuardProfile, account.max_user_id)
    if profile is None:
        raise HTTPException(403, "Guard profile not found")
    assignments = await session.scalars(
        select(Checkpoint)
        .join(GuardCheckpoint, GuardCheckpoint.checkpoint_id == Checkpoint.id)
        .where(GuardCheckpoint.user_id == account.max_user_id, Checkpoint.is_active.is_(True))
        .order_by(Checkpoint.name)
    )
    checkpoints = []
    for checkpoint in assignments:
        checkpoints.append(
            {
                "id": str(checkpoint.id),
                "name": checkpoint.name,
                "on_shift": await guard_has_active_shift(session, account.max_user_id, checkpoint.id),
            }
        )
    return {
        "status": profile.status,
        "on_shift": any(checkpoint["on_shift"] for checkpoint in checkpoints),
        "checkpoints": checkpoints,
    }


@router.get("/queue")
async def guard_queue(
    account: Account = Depends(require_role("GUARD")),
    session: AsyncSession = Depends(get_session),
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
):
    await _verified_guard(account, session)
    checkpoints = await session.scalars(
        select(GuardCheckpoint.checkpoint_id).where(GuardCheckpoint.user_id == account.max_user_id)
    )
    active_checkpoints = []
    for checkpoint_id in checkpoints:
        if await guard_has_active_shift(session, account.max_user_id, checkpoint_id):
            active_checkpoints.append(checkpoint_id)
    if not active_checkpoints:
        return {"items": [], "total": 0}

    query = (
        select(VisitRequest)
        .where(
            VisitRequest.checkpoint_id.in_(active_checkpoints),
            VisitRequest.status == "ACTIVE",
        )
        .order_by(VisitRequest.is_pinned.desc(), VisitRequest.created_at.desc())
    )
    if q:
        pattern = f"%{q.strip()}%"
        query = (
            query.join(Account, Account.max_user_id == VisitRequest.resident_id)
            .join(Apartment, Apartment.id == VisitRequest.apartment_id)
            .join(Building, Building.id == Apartment.building_id)
            .where(
                or_(
                    VisitRequest.visitor_name.ilike(pattern),
                    VisitRequest.visitor_car_number.ilike(pattern),
                    Account.full_name.ilike(pattern),
                    Apartment.number.ilike(pattern),
                    Building.name.ilike(pattern),
                )
            )
        )
    count_query = select(func.count(VisitRequest.id)).where(
        VisitRequest.checkpoint_id.in_(active_checkpoints), VisitRequest.status == "ACTIVE"
    )
    if q:
        count_query = (
            count_query.join(Account, Account.max_user_id == VisitRequest.resident_id)
            .join(Apartment, Apartment.id == VisitRequest.apartment_id)
            .join(Building, Building.id == Apartment.building_id)
            .where(
                or_(
                    VisitRequest.visitor_name.ilike(pattern),
                    VisitRequest.visitor_car_number.ilike(pattern),
                    Account.full_name.ilike(pattern),
                    Apartment.number.ilike(pattern),
                    Building.name.ilike(pattern),
                )
            )
        )
    visits = await session.scalars(query.limit(limit).offset(offset))
    total = await session.scalar(count_query) or 0
    return {"items": await serialize_requests(session, list(visits)), "total": total}


@router.get("/history")
async def guard_history(
    account: Account = Depends(require_role("GUARD")),
    session: AsyncSession = Depends(get_session),
    checkpoint_id: UUID | None = None,
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=100),
):
    await _verified_guard(account, session)
    checkpoint_ids = list(
        await session.scalars(
            select(GuardCheckpoint.checkpoint_id).where(GuardCheckpoint.user_id == account.max_user_id)
        )
    )
    if checkpoint_id:
        await require_guard_checkpoint(session, account.max_user_id, checkpoint_id)
        checkpoint_ids = [checkpoint_id]
    if not checkpoint_ids:
        return []
    query = (
        select(VisitRequest)
        .where(
            VisitRequest.checkpoint_id.in_(checkpoint_ids),
            VisitRequest.status.in_(("PASSED", "REJECTED", "CANCELLED", "EXPIRED")),
        )
        .order_by(VisitRequest.resolved_at.desc().nullslast(), VisitRequest.created_at.desc())
        .limit(limit)
    )
    if q:
        pattern = f"%{q.strip()}%"
        query = (
            query.join(Account, Account.max_user_id == VisitRequest.resident_id)
            .join(Apartment, Apartment.id == VisitRequest.apartment_id)
            .where(
                or_(VisitRequest.visitor_name.ilike(pattern), Account.full_name.ilike(pattern), Apartment.number.ilike(pattern))
            )
        )
    visits = list(await session.scalars(query))
    return await serialize_requests(session, visits)


@router.get("/{request_id}")
async def guard_request_detail(
    request_id: UUID,
    account: Account = Depends(require_role("GUARD")),
    session: AsyncSession = Depends(get_session),
):
    await _verified_guard(account, session)
    visit = await session.get(VisitRequest, request_id)
    if visit is None or visit.status == "DELETED":
        raise HTTPException(404, "Заявка не найдена")
    await require_guard_checkpoint(session, account.max_user_id, visit.checkpoint_id)
    if visit.status == "ACTIVE" and not await guard_has_active_shift(
        session, account.max_user_id, visit.checkpoint_id
    ):
        raise HTTPException(403, "Смена на этом КПП не активна")
    return await serialize_request(session, visit)


@router.post("/{request_id}/decision")
async def decide_visit(
    request_id: UUID,
    body: Decision,
    account: Account = Depends(require_role("GUARD")),
    session: AsyncSession = Depends(get_session),
):
    await _verified_guard(account, session)
    visit = await session.scalar(select(VisitRequest).where(VisitRequest.id == request_id).with_for_update())
    if visit is None:
        raise HTTPException(404, "Заявка не найдена")
    await require_guard_checkpoint(session, account.max_user_id, visit.checkpoint_id)
    if not await guard_has_active_shift(session, account.max_user_id, visit.checkpoint_id):
        raise HTTPException(403, "Смена на этом КПП не активна")
    if body.status == "REJECTED" and not (body.reason or "").strip():
        raise HTTPException(422, "Укажите причину отклонения")
    now = datetime.now(timezone.utc)
    update_result = await session.execute(
        update(VisitRequest)
        .where(VisitRequest.id == request_id, VisitRequest.status == "ACTIVE")
        .values(
            status=body.status,
            resolved_at=now,
            resolved_by=account.max_user_id,
            rejection_reason=body.reason.strip()[:500] if body.status == "REJECTED" and body.reason else None,
        )
    )
    if update_result.rowcount != 1:
        await session.rollback()
        raise HTTPException(409, "Заявка уже обработана другим сотрудником или отменена жильцом")
    visit.status = body.status
    visit.resolved_at = now
    visit.resolved_by = account.max_user_id
    visit.rejection_reason = body.reason.strip()[:500] if body.status == "REJECTED" and body.reason else None
    event_type = "PASSED" if body.status == "PASSED" else "REJECTED"
    session.add(
        VisitEvent(
            request_id=visit.id,
            actor_id=account.max_user_id,
            event_type=event_type,
            metadata_json={"reason": visit.rejection_reason} if visit.rejection_reason else {},
        )
    )
    notice = (
        f"Посетитель «{visit.visitor_name}» прошёл КПП."
        if body.status == "PASSED"
        else f"Заявка для «{visit.visitor_name}» отклонена: {visit.rejection_reason}"
    )
    await enqueue_notification(
        session,
        recipient_id=visit.resident_id,
        request_id=visit.id,
        dedupe_key=f"visit:{visit.id}:{body.status.lower()}:resident",
        text=notice,
    )
    await session.commit()
    result = await session.get(VisitRequest, request_id)
    return await serialize_request(session, result)


@router.put("/{request_id}/pin")
async def pin_request(
    request_id: UUID,
    body: PinUpdate,
    account: Account = Depends(require_role("GUARD")),
    session: AsyncSession = Depends(get_session),
):
    await _verified_guard(account, session)
    visit = await session.get(VisitRequest, request_id)
    if visit is None or visit.status != "ACTIVE":
        raise HTTPException(409, "Закрепить можно только активную заявку")
    await require_guard_checkpoint(session, account.max_user_id, visit.checkpoint_id)
    if not await guard_has_active_shift(session, account.max_user_id, visit.checkpoint_id):
        raise HTTPException(403, "Смена на этом КПП не активна")
    visit.is_pinned = body.is_pinned
    session.add(
        VisitEvent(
            request_id=visit.id,
            actor_id=account.max_user_id,
            event_type="PINNED" if body.is_pinned else "UNPINNED",
            metadata_json={},
        )
    )
    await session.commit()
    return {"id": str(visit.id), "is_pinned": visit.is_pinned}
