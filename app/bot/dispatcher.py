"""Простой диспетчер апдейтов: роутеры без привязки к конкретному SDK."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from app.bot.client import BotClient
from app.bot.context import current_bot
from app.bot.updates import (
    callback_payload,
    message_text,
    parse_command,
    sender_user_id,
    update_type,
)
from app.fsm.storage import fsm

Handler = Callable[..., Awaitable[None]]


@dataclass
class BoundHandler:
    func: Handler
    commands: frozenset[str] = field(default_factory=frozenset)
    payloads: frozenset[str] = field(default_factory=frozenset)
    payload_prefixes: frozenset[str] = field(default_factory=frozenset)
    update_types: frozenset[str] | None = None
    states: frozenset[Any] | None = None

    def matches(self, update: Any) -> bool:
        ut = update_type(update)
        if self.update_types is not None and ut not in self.update_types:
            return False
        if self.states is not None:
            current = fsm.get_state(sender_user_id(update))
            if current not in self.states:
                return False
        if self.commands:
            command = parse_command(message_text(update))
            return command in self.commands
        if self.payloads or self.payload_prefixes:
            payload = callback_payload(update)
            if payload is None:
                return False
            if payload in self.payloads:
                return True
            return any(payload.startswith(prefix) for prefix in self.payload_prefixes)
        return True


class Router:
    def __init__(self, name: str) -> None:
        self.name = name
        self.handlers: list[BoundHandler] = []

    def command(self, *commands: str) -> Callable[[Handler], Handler]:
        names = frozenset(cmd.lstrip("/").lower() for cmd in commands)

        def decorator(func: Handler) -> Handler:
            self.handlers.append(
                BoundHandler(
                    func,
                    commands=names,
                    update_types=frozenset({"message_created"}),
                )
            )
            return func

        return decorator

    def callback(self, *payloads: str) -> Callable[[Handler], Handler]:
        wanted = frozenset(payloads)

        def decorator(func: Handler) -> Handler:
            self.handlers.append(
                BoundHandler(
                    func,
                    payloads=wanted,
                    update_types=frozenset({"message_callback"}),
                )
            )
            return func

        return decorator

    def callback_prefix(self, *prefixes: str) -> Callable[[Handler], Handler]:
        wanted = frozenset(prefixes)

        def decorator(func: Handler) -> Handler:
            self.handlers.append(
                BoundHandler(
                    func,
                    payload_prefixes=wanted,
                    update_types=frozenset({"message_callback"}),
                )
            )
            return func

        return decorator

    def event(self, *types: str) -> Callable[[Handler], Handler]:
        wanted = frozenset(types)

        def decorator(func: Handler) -> Handler:
            self.handlers.append(BoundHandler(func, update_types=wanted))
            return func

        return decorator

    def state(self, *states: Any) -> Callable[[Handler], Handler]:
        wanted = frozenset(states)

        def decorator(func: Handler) -> Handler:
            self.handlers.append(
                BoundHandler(
                    func,
                    update_types=frozenset({"message_created"}),
                    states=wanted,
                )
            )
            return func

        return decorator


class Dispatcher:
    def __init__(self) -> None:
        self.routers: list[Router] = []

    def include_router(self, router: Router) -> None:
        self.routers.append(router)

    async def feed_update(self, bot: BotClient, update: Any) -> None:
        token = current_bot.set(bot)
        try:
            for router in self.routers:
                for handler in router.handlers:
                    if not handler.matches(update):
                        continue
                    await handler.func(bot, update)
                    return
        finally:
            current_bot.reset(token)

    async def start_polling(self, bot: BotClient, *, timeout: int = 30) -> None:
        logger.info("Long polling запущен")
        marker: int | None = None
        connected = False
        while True:
            try:
                page = await bot.get_updates(marker=marker, timeout=timeout)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Ошибка get_updates, повтор через 3 с")
                await asyncio.sleep(3)
                continue

            if not connected:
                logger.info("MAX GET /updates успешно ответил")
                connected = True

            if isinstance(page, dict):
                updates = page.get("updates") or []
                marker = page.get("marker", marker)
            else:
                updates = getattr(page, "updates", None) or []
                marker = getattr(page, "marker", marker)

            if updates:
                logger.info("MAX GET /updates вернул {} обновлений", len(updates))

            for item in updates:
                try:
                    await self.feed_update(bot, item)
                except Exception:
                    logger.exception("Ошибка обработки апдейта")
