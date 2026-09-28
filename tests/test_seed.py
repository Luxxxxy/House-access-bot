from __future__ import annotations

import os

import pytest
import pytest_asyncio
from sqlalchemy import BigInteger, event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

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


@pytest_asyncio.fixture
async def seed_database(monkeypatch: pytest.MonkeyPatch):
    database_url = os.getenv("SEED_TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    engine = create_async_engine(database_url)
    if database_url.startswith("sqlite"):

        @event.listens_for(engine.sync_engine, "connect")
        def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(seed, "SessionLocal", factory)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _counts(factory) -> dict[str, int]:
    models = {
        "accounts": Account,
        "complexes": ResidentialComplex,
        "buildings": Building,
        "checkpoints": Checkpoint,
        "apartments": Apartment,
        "registry_entries": RegistryEntry,
        "complex_admins": ComplexAdmin,
        "resident_apartments": ResidentApartment,
        "guard_profiles": GuardProfile,
        "guard_checkpoints": GuardCheckpoint,
        "guard_shifts": GuardShift,
        "visits": VisitRequest,
        "notifications": Notification,
    }
    async with factory() as session:
        return {
            name: await session.scalar(select(func.count()).select_from(model)) or 0
            for name, model in models.items()
        }


@pytest.mark.asyncio
async def test_seed_demo_creates_parents_before_associations_and_is_idempotent(seed_database):
    factory = seed_database
    assert Account.__table__.c.max_user_id.primary_key
    assert isinstance(Account.__table__.c.max_user_id.type, BigInteger)
    assert isinstance(GuardProfile.__table__.c.user_id.type, BigInteger)
    assert isinstance(GuardCheckpoint.__table__.c.user_id.type, BigInteger)
    assert isinstance(GuardShift.__table__.c.user_id.type, BigInteger)
    assert next(iter(GuardProfile.__table__.c.user_id.foreign_keys)).target_fullname == (
        "accounts.max_user_id"
    )
    assert next(iter(GuardCheckpoint.__table__.c.user_id.foreign_keys)).target_fullname == (
        "guard_profiles.user_id"
    )

    await seed.seed_demo()

    async with factory() as session:
        accounts = (await session.scalars(select(Account))).all()
        assert len(accounts) == 25
        roles = {account.max_user_id: account.role for account in accounts}
        assert roles[seed.DEMO_ADMIN_ID] == "ADMIN"
        assert {user_id for user_id, role in roles.items() if role == "GUARD"} == set(
            seed.DEMO_GUARD_IDS
        )
        assert {user_id for user_id, role in roles.items() if role == "RESIDENT"} == set(
            seed.DEMO_RESIDENT_IDS
        )

        guard_profiles = set(await session.scalars(select(GuardProfile.user_id)))
        assert guard_profiles == set(seed.DEMO_GUARD_IDS)

        actual_guard_checkpoints = {
            (user_id, checkpoint_id)
            for user_id, checkpoint_id in (
                await session.execute(
                    select(GuardCheckpoint.user_id, GuardCheckpoint.checkpoint_id)
                )
            ).all()
        }
        expected_guard_checkpoints = {
            (seed.DEMO_GUARD_IDS[0], seed.uid("checkpoint-1")),
            (seed.DEMO_GUARD_IDS[1], seed.uid("checkpoint-1")),
            (seed.DEMO_GUARD_IDS[1], seed.uid("checkpoint-2")),
            (seed.DEMO_GUARD_IDS[2], seed.uid("checkpoint-2")),
            (seed.DEMO_GUARD_IDS[3], seed.uid("checkpoint-1")),
        }
        assert actual_guard_checkpoints == expected_guard_checkpoints

        shift_user_ids = set(await session.scalars(select(GuardShift.user_id).distinct()))
        assert shift_user_ids == set(seed.DEMO_GUARD_IDS)
        assert await session.scalar(select(func.count()).select_from(GuardShift)) == 28

        assert await session.scalar(select(func.count()).select_from(ComplexAdmin)) == 1
        assert await session.scalar(select(func.count()).select_from(ResidentApartment)) == 21
        assert await session.scalar(select(func.count()).select_from(VisitRequest)) == 4
        assert await session.scalar(
            select(func.count())
            .select_from(ResidentApartment)
            .where(ResidentApartment.registry_entry_id.is_(None))
        ) == 0

        # Notification is not currently seeded, but any demo notification recipient
        # must also refer to an existing account.
        notification_recipients = set(await session.scalars(select(Notification.recipient_id)))
        assert notification_recipients <= set(roles)

    first_run_counts = await _counts(factory)
    await seed.seed_demo()
    second_run_counts = await _counts(factory)
    assert second_run_counts == first_run_counts
    assert second_run_counts == {
        "accounts": 25,
        "complexes": 1,
        "buildings": 2,
        "checkpoints": 2,
        "apartments": 19,
        "registry_entries": 21,
        "complex_admins": 1,
        "resident_apartments": 21,
        "guard_profiles": 4,
        "guard_checkpoints": 5,
        "guard_shifts": 28,
        "visits": 4,
        "notifications": 0,
    }
