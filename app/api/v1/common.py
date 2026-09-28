from fastapi import HTTPException
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
    ResidentApartment,
    ResidentialComplex,
)


async def get_resident_complex(session: AsyncSession, user_id: int, apartment_id=None):
    query = (
        select(ResidentialComplex)
        .join(Building, Building.complex_id == ResidentialComplex.id)
        .join(Apartment, Apartment.building_id == Building.id)
        .join(ResidentApartment, ResidentApartment.apartment_id == Apartment.id)
        .where(ResidentApartment.user_id == user_id, Apartment.is_active.is_(True))
    )
    if apartment_id:
        query = query.where(Apartment.id == apartment_id)
    return await session.scalar(query.limit(1))


async def require_admin(session: AsyncSession, user_id: int, complex_id) -> None:
    if await session.scalar(
        select(ComplexAdmin.user_id).where(
            ComplexAdmin.user_id == user_id,
            ComplexAdmin.complex_id == complex_id,
        )
    ) is None:
        raise HTTPException(403, "Administrator has no access to this residential complex")


async def require_guard_checkpoint(session: AsyncSession, user_id: int, checkpoint_id) -> Checkpoint:
    checkpoint = await session.get(Checkpoint, checkpoint_id)
    if checkpoint is None or not checkpoint.is_active:
        raise HTTPException(404, "Checkpoint not found")
    assignment = await session.scalar(
        select(GuardCheckpoint.user_id)
        .join(GuardProfile, GuardProfile.user_id == GuardCheckpoint.user_id)
        .where(
            GuardCheckpoint.user_id == user_id,
            GuardCheckpoint.checkpoint_id == checkpoint_id,
            GuardProfile.status == "VERIFIED",
        )
    )
    if assignment is None:
        raise HTTPException(403, "Guard is not assigned to this checkpoint")
    return checkpoint


async def ensure_same_complex(session: AsyncSession, user_id: int, complex_id) -> Account:
    account = await session.get(Account, user_id)
    if account is None or not account.is_active:
        raise HTTPException(403, "Account is blocked")
    return account
