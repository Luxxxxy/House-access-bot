"""Создание таблиц и seed первого админа."""

from typing import Any

from loguru import logger
from sqlalchemy import inspect, select, text
from sqlalchemy import update as sa_update

from app.config import persist_admin_max_user_id, settings
from app.db.models import Base, Role, User
from app.db.session import async_session_maker, engine


def _ensure_columns(sync_conn: Any) -> None:
    inspector = inspect(sync_conn)
    tables = set(inspector.get_table_names())
    if "users" in tables:
        cols = {column["name"] for column in inspector.get_columns("users")}
        if "guard_approved" not in cols:
            sync_conn.execute(
                text(
                    "ALTER TABLE users ADD COLUMN guard_approved "
                    "BOOLEAN DEFAULT 0 NOT NULL"
                )
            )
    if "visit_requests" in tables:
        cols = {column["name"] for column in inspector.get_columns("visit_requests")}
        if "apartment" not in cols:
            sync_conn.execute(
                text(
                    "ALTER TABLE visit_requests ADD COLUMN apartment "
                    "VARCHAR(32) DEFAULT '' NOT NULL"
                )
            )


async def init_models() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_columns)
    async with async_session_maker() as session:
        await session.execute(
            sa_update(User)
            .where(
                User.role == Role.GUARD,
                User.is_active.is_(True),
                User.guard_approved.is_(False),
            )
            .values(guard_approved=True)
        )
        await session.commit()
    logger.info("Таблицы БД созданы или уже существуют")


async def seed_admin() -> None:
    async with async_session_maker() as session:
        if settings.admin_max_user_id is not None:
            existing = await session.get(User, settings.admin_max_user_id)
            if existing is not None:
                logger.info(
                    "Админ уже есть в БД (id={})",
                    settings.admin_max_user_id,
                )
                return

            session.add(
                User(
                    id=settings.admin_max_user_id,
                    full_name="Главный админ",
                    role=Role.ADMIN,
                    is_active=True,
                )
            )
            await session.commit()
            logger.info(
                "Создан главный админ (id={})",
                settings.admin_max_user_id,
            )
            return

        first_admin = await session.scalar(
            select(User)
            .where(User.role == Role.ADMIN, User.is_active.is_(True))
            .order_by(User.created_at.asc())
        )
        if first_admin is not None:
            persist_admin_max_user_id(first_admin.id)
            logger.info(
                "ADMIN_MAX_USER_ID восстановлен из БД (id={})",
                first_admin.id,
            )
            return

    logger.info("ADMIN_MAX_USER_ID не задан: первый админ появится после входа по коду")
