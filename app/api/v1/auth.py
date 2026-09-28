from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import GuardRegistration, ResidentRegistration
from app.domain.logic import hash_invite, normalize_name
from app.domain.models import (
    Account,
    Apartment,
    AuditEvent,
    Building,
    Checkpoint,
    ComplexAdmin,
    GuardCheckpoint,
    GuardInvite,
    GuardProfile,
    RegistryEntry,
    ResidentApartment,
    ResidentialComplex,
)
from app.security.auth import Principal, get_principal
from app.web.db import get_session

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.get("/me")
async def me(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    account = await session.get(Account, principal.user_id)
    if principal.is_demo and (account is None or not account.is_demo):
        raise HTTPException(403, "Demo access is limited to seed accounts")
    memberships = await session.execute(
        select(ResidentApartment, Apartment, Building, ResidentialComplex)
        .join(Apartment, Apartment.id == ResidentApartment.apartment_id)
        .join(Building, Building.id == Apartment.building_id)
        .join(ResidentialComplex, ResidentialComplex.id == Building.complex_id)
        .where(ResidentApartment.user_id == principal.user_id, Apartment.is_active.is_(True))
    )
    apartment_list = [
        {
            "id": str(apt.id),
            "number": apt.number,
            "building": building.name,
            "complex_id": str(complex_obj.id),
            "complex_name": complex_obj.name,
            "timezone": complex_obj.timezone,
        }
        for _membership, apt, building, complex_obj in memberships
    ]
    guard = await session.get(GuardProfile, principal.user_id)
    guard_checkpoints = await session.execute(
        select(Checkpoint)
        .join(GuardCheckpoint, GuardCheckpoint.checkpoint_id == Checkpoint.id)
        .where(GuardCheckpoint.user_id == principal.user_id, Checkpoint.is_active.is_(True))
    )
    admin_complexes = await session.execute(
        select(ResidentialComplex)
        .join(ComplexAdmin, ComplexAdmin.complex_id == ResidentialComplex.id)
        .where(ComplexAdmin.user_id == principal.user_id)
    )
    return {
        "user_id": principal.user_id,
        "full_name": account.full_name if account else None,
        "role": account.role if account else "UNREGISTERED",
        "is_active": account.is_active if account else False,
        "default_contact": account.default_contact if account else None,
        "apartments": apartment_list,
        "guard_status": guard.status if guard else None,
        "guard_checkpoints": [
            {"id": str(cp.id), "name": cp.name} for cp in guard_checkpoints.scalars()
        ],
        "admin_complexes": [
            {"id": str(cx.id), "name": cx.name} for cx in admin_complexes.scalars()
        ],
        "demo": principal.is_demo,
    }


@router.post("/resident/register", status_code=201)
async def register_resident(
    body: ResidentRegistration,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    account = await session.get(Account, principal.user_id)
    is_new_account = account is None
    if account and (account.role != "RESIDENT" or not account.is_active):
        raise HTTPException(409, "This MAX account already has a different role or is blocked")
    normalized = normalize_name(body.full_name)
    candidates = await session.execute(
        select(RegistryEntry, Apartment, Building, ResidentialComplex)
        .join(Apartment, Apartment.id == RegistryEntry.apartment_id)
        .join(Building, Building.id == Apartment.building_id)
        .join(ResidentialComplex, ResidentialComplex.id == Building.complex_id)
        .where(
            RegistryEntry.normalized_name == normalized,
            RegistryEntry.is_active.is_(True),
            Apartment.number == body.apartment.strip(),
            Building.name == body.building.strip(),
            Apartment.is_active.is_(True),
            ResidentialComplex.is_active.is_(True),
        )
    )
    rows = list(candidates)
    if not rows:
        raise HTTPException(422, "Данные не найдены в реестре жильцов. Проверьте ФИО, корпус и квартиру")
    entry, apartment, _building, _complex = rows[0]
    if account and normalize_name(account.full_name) != normalized:
        raise HTTPException(409, "MAX-аккаунт уже связан с другой записью жильца")
    linked = await session.scalar(
        select(ResidentApartment.id).where(ResidentApartment.registry_entry_id == entry.id)
    )
    if linked:
        raise HTTPException(409, "Эта запись реестра уже связана с MAX-аккаунтом")
    if account is None:
        account = Account(
            max_user_id=principal.user_id,
            role="RESIDENT",
            full_name=entry.full_name,
            default_contact=body.default_contact.strip(),
            is_demo=principal.is_demo,
        )
        session.add(account)
        await session.flush()
    else:
        account.default_contact = body.default_contact.strip()
    session.add(
        ResidentApartment(
            user_id=principal.user_id,
            apartment_id=apartment.id,
            registry_entry_id=entry.id,
        )
    )
    session.add(
        AuditEvent(
            complex_id=_complex.id,
            actor_id=principal.user_id,
            action="RESIDENT_REGISTERED" if is_new_account else "RESIDENT_APARTMENT_LINKED",
            target_id=str(principal.user_id),
            metadata_json={"apartment_id": str(apartment.id)},
        )
    )
    await session.commit()
    return {"registered": True, "full_name": account.full_name, "apartment_id": str(apartment.id)}


@router.post("/guard/register", status_code=202)
async def register_guard(
    body: GuardRegistration,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    now = datetime.now(timezone.utc)
    invite = await session.scalar(
        select(GuardInvite)
        .where(GuardInvite.code_hash == hash_invite(body.invite_code), GuardInvite.used_at.is_(None))
        .with_for_update()
    )
    invite_expiry = (
        invite.expires_at.replace(tzinfo=timezone.utc)
        if invite is not None and invite.expires_at.tzinfo is None
        else invite.expires_at if invite is not None else None
    )
    if invite is None or invite_expiry <= now:
        raise HTTPException(410, "Код приглашения недействителен или истёк")
    if await session.get(Account, principal.user_id):
        raise HTTPException(409, "This MAX account already has a registered role")
    checkpoint = await session.get(Checkpoint, invite.checkpoint_id)
    if checkpoint is None or not checkpoint.is_active or checkpoint.complex_id != invite.complex_id:
        raise HTTPException(410, "Приглашение больше не действует")
    account = Account(
        max_user_id=principal.user_id,
        role="GUARD",
        full_name=body.full_name.strip(),
        is_demo=principal.is_demo,
    )
    session.add(account)
    await session.flush()
    session.add(GuardProfile(user_id=principal.user_id, complex_id=invite.complex_id, status="PENDING"))
    session.add(GuardCheckpoint(user_id=principal.user_id, checkpoint_id=invite.checkpoint_id))
    invite.used_at = now
    invite.used_by = principal.user_id
    session.add(
        AuditEvent(
            complex_id=invite.complex_id,
            actor_id=principal.user_id,
            action="GUARD_REGISTERED",
            target_id=str(principal.user_id),
            metadata_json={"checkpoint_id": str(invite.checkpoint_id)},
        )
    )
    await session.commit()
    return {"status": "PENDING", "message": "Регистрация ожидает проверки администратора"}
