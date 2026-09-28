"""Проверка require_role как функции и как декоратора."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

from app.db.models import Role, User
from app.services.permissions import DENIED, require_role


def _user(*, role: Role, is_active: bool = True, user_id: int = 10) -> User:
    return User(
        id=user_id,
        username="u",
        full_name="Тест",
        role=role,
        is_active=is_active,
    )


def test_require_role_allows_matching_role() -> None:
    assert require_role(_user(role=Role.ADMIN), Role.ADMIN) is True
    assert require_role(_user(role=Role.GUARD), Role.GUARD, Role.ADMIN) is True


def test_require_role_denies_wrong_role() -> None:
    assert require_role(_user(role=Role.RESIDENT), Role.ADMIN) is False
    assert require_role(_user(role=Role.GUARD), Role.ADMIN) is False


def test_require_role_denies_inactive_and_missing() -> None:
    assert require_role(_user(role=Role.ADMIN, is_active=False), Role.ADMIN) is False
    assert require_role(None, Role.ADMIN) is False


async def test_require_role_decorator_allows(monkeypatch: Any) -> None:
    admin = _user(role=Role.ADMIN, user_id=1)

    async def fake_get_user(user_id: int | None) -> User | None:
        return admin if user_id == 1 else None

    monkeypatch.setattr("app.services.permissions.get_user", fake_get_user)

    @require_role(Role.ADMIN)
    async def handler(_bot: Any, _update: Any) -> str:
        return "ok"

    bot = AsyncMock()
    result = await handler(bot, {"update_type": "message_created", "user_id": 1})
    assert result == "ok"
    bot.reply.assert_not_called()


async def test_require_role_decorator_denies(monkeypatch: Any) -> None:
    resident = _user(role=Role.RESIDENT, user_id=2)

    async def fake_get_user(user_id: int | None) -> User | None:
        return resident if user_id == 2 else None

    monkeypatch.setattr("app.services.permissions.get_user", fake_get_user)

    @require_role(Role.ADMIN)
    async def handler(_bot: Any, _update: Any) -> str:
        return "ok"

    bot = AsyncMock()
    result = await handler(
        bot,
        {
            "update_type": "message_created",
            "message": {"sender": {"user_id": 2}, "body": {"text": "x"}},
        },
    )
    assert result is None
    bot.reply.assert_awaited()
    assert bot.reply.await_args.args[1] == DENIED
