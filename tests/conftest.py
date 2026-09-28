"""Общие фикстуры тестов."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

os.environ["MAX_BOT_TOKEN"] = "test-token"
os.environ["ADMIN_MAX_USER_ID"] = "1"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["LOG_LEVEL"] = "WARNING"

import pytest

from app.config import settings
from app.db.models import Base
from app.db.session import engine
from app.fsm.storage import fsm


@pytest.fixture
async def db() -> AsyncIterator[None]:
    original_admin_id = settings.admin_max_user_id
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    fsm._records.clear()
    yield
    fsm._records.clear()
    settings.admin_max_user_id = original_admin_id
