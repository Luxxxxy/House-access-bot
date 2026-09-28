"""Тестовые хелперы без импорта conftest как модуля."""

from __future__ import annotations

from typing import Any

from app.bot.client import BotClient
from app.bot.dispatcher import Dispatcher
from app.handlers.admin import router as admin_router
from app.handlers.common import router as common_router
from app.handlers.guard import router as guard_router
from app.handlers.resident import router as resident_router


class FakeBot(BotClient):
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.edits: list[dict[str, Any]] = []

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def get_updates(
        self,
        *,
        marker: int | None = None,
        timeout: int = 30,
    ) -> Any:
        return {"updates": [], "marker": marker}

    async def send_message(
        self,
        *,
        chat_id: int | None = None,
        user_id: int | None = None,
        text: str | None = None,
        attachments: list[Any] | None = None,
        format: str | None = None,
    ) -> Any:
        payload = {
            "chat_id": chat_id,
            "user_id": user_id,
            "text": text,
            "attachments": attachments,
            "format": format,
        }
        self.sent.append(payload)
        return payload

    async def edit_message(
        self,
        message_id: str,
        *,
        text: str | None = None,
        attachments: list[Any] | None = None,
        format: str | None = None,
    ) -> Any:
        payload = {
            "message_id": message_id,
            "text": text,
            "attachments": attachments,
            "format": format,
        }
        self.edits.append(payload)
        return payload


def make_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(common_router)
    dp.include_router(admin_router)
    dp.include_router(guard_router)
    dp.include_router(resident_router)
    return dp


def message_update(user_id: int, text: str, *, name: str = "User") -> dict[str, Any]:
    return {
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": user_id, "name": name, "username": None},
            "recipient": {"chat_id": user_id, "chat_type": "dialog", "user_id": user_id},
            "body": {"mid": f"m-{user_id}", "seq": 1, "text": text},
        },
    }


def callback_update(
    user_id: int,
    payload: str,
    *,
    name: str = "User",
    mid: str = "mid-1",
) -> dict[str, Any]:
    return {
        "update_type": "message_callback",
        "callback": {
            "payload": payload,
            "user": {"user_id": user_id, "name": name},
        },
        "message": {
            "sender": {"user_id": 0, "name": "bot"},
            "recipient": {"chat_id": user_id, "chat_type": "dialog", "user_id": user_id},
            "body": {"mid": mid, "seq": 1, "text": "notice"},
        },
    }
