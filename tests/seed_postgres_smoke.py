"""Run the idempotent demo seed against an empty PostgreSQL database.

The caller must point DATABASE_URL at a disposable database. This script creates
the schema, runs the production seed twice, and checks its resulting row counts.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain import seed
from app.domain.models import (
    Account,
    Apartment,
    Base,
    Building,
    Checkpoint,
    ComplexAdmin,
    GuardCheckpoint,
    GuardProfile,
    GuardShift,
    Notification,
    RegistryEntry,
    ResidentApartment,
    ResidentialComplex,
    VisitRequest,
)


async def main() -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    seed.SessionLocal = factory

    try:
        await seed.seed_demo()
        async with factory() as session:
            account_ids = set(await session.scalars(select(Account.max_user_id)))
            guard_ids = set(
                await session.scalars(
                    select(Account.max_user_id).where(Account.role == "GUARD")
                )
            )
            profile_ids = set(await session.scalars(select(GuardProfile.user_id)))
            guard_checkpoint_rows = set(
                (
                    await session.execute(
                        select(GuardCheckpoint.user_id, GuardCheckpoint.checkpoint_id)
                    )
                ).all()
            )
            guard_shift_ids = set(await session.scalars(select(GuardShift.user_id).distinct()))
            notification_recipients = set(
                await session.scalars(select(Notification.recipient_id))
            )

        expected_guard_checkpoints = {
            (seed.DEMO_GUARD_IDS[0], seed.uid("checkpoint-1")),
            (seed.DEMO_GUARD_IDS[1], seed.uid("checkpoint-1")),
            (seed.DEMO_GUARD_IDS[1], seed.uid("checkpoint-2")),
            (seed.DEMO_GUARD_IDS[2], seed.uid("checkpoint-2")),
            (seed.DEMO_GUARD_IDS[3], seed.uid("checkpoint-1")),
        }
        assert account_ids == {
            seed.DEMO_ADMIN_ID,
            *seed.DEMO_GUARD_IDS,
            *seed.DEMO_RESIDENT_IDS,
        }
        assert guard_ids == set(seed.DEMO_GUARD_IDS)
        assert profile_ids == set(seed.DEMO_GUARD_IDS)
        assert guard_checkpoint_rows == expected_guard_checkpoints
        assert guard_shift_ids == set(seed.DEMO_GUARD_IDS)
        assert notification_recipients <= account_ids

        models = (
            ResidentialComplex,
            Building,
            Checkpoint,
            Account,
            Apartment,
            RegistryEntry,
            ComplexAdmin,
            ResidentApartment,
            GuardProfile,
            GuardCheckpoint,
            GuardShift,
            VisitRequest,
            Notification,
        )

        async def counts() -> tuple[int, ...]:
            row_counts = []
            async with factory() as session:
                for model in models:
                    row_counts.append(
                        await session.scalar(select(func.count()).select_from(model)) or 0
                    )
            return tuple(row_counts)

        first_counts = await counts()
        await seed.seed_demo()
        second_counts = await counts()
        assert first_counts == second_counts
        assert first_counts == (1, 2, 2, 25, 19, 21, 1, 21, 4, 5, 28, 4, 0)
        print("PostgreSQL seed smoke passed: 25 accounts, 4 guards, 5 checkpoint links.")
        print("Second seed matched first run; no duplicate rows.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
