"""Проверка роли пользователя."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, TypeVar, overload

from app.bot.updates import sender_user_id
from app.db.models import Role, User
from app.db.session import async_session_maker

DENIED = "Недостаточно прав"

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


async def get_user(user_id: int | None) -> User | None:
    if user_id is None:
        return None
    async with async_session_maker() as session:
        return await session.get(User, user_id)


def _has_role(user: User | None, *roles: Role) -> bool:
    if user is None or not user.is_active:
        return False
    if not roles:
        return True
    return user.role in roles


@overload
def require_role(user_or_role: Role, *roles: Role) -> Callable[[F], F]: ...


@overload
def require_role(user_or_role: User | None, *roles: Role) -> bool: ...


def require_role(
    user_or_role: User | Role | None,
    *roles: Role,
) -> bool | Callable[[F], F]:
    """Функция или декоратор.

    Функция: ``require_role(user, Role.ADMIN)`` → bool.
    Декоратор: ``@require_role(Role.ADMIN)`` — при отказе отвечает
    «Недостаточно прав».
    """
    if isinstance(user_or_role, Role):
        needed = (user_or_role, *roles)

        def decorator(func: F) -> F:
            @wraps(func)
            async def wrapper(bot: Any, update: Any, *args: Any, **kwargs: Any) -> Any:
                user = await get_user(sender_user_id(update))
                if not _has_role(user, *needed):
                    await bot.reply(update, DENIED)
                    return None
                return await func(bot, update, *args, **kwargs)

            return wrapper  # type: ignore[return-value]

        return decorator

    return _has_role(user_or_role, *roles)


async def load_required_user(
    bot: Any,
    update: Any,
    *roles: Role,
) -> User | None:
    user = await get_user(sender_user_id(update))
    if not require_role(user, *roles):
        await bot.reply(update, DENIED)
        return None
    return user
