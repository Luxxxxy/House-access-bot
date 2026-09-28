"""Клиент MAX Bot API за абстракцией BotClient."""

from abc import ABC, abstractmethod
from dataclasses import asdict, is_dataclass
from typing import Any

import httpx
from loguru import logger

from app.bot.updates import chat_id as extract_chat_id
from app.bot.updates import message_mid, sender_user_id
from app.config import settings
from app.integrations.max_tls import create_max_api_client


class BotClient(ABC):
    """Контракт клиента. Реализацию MAX можно заменить без правок хендлеров."""

    @abstractmethod
    async def start(self) -> None:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass

    @abstractmethod
    async def get_updates(
        self,
        *,
        marker: int | None = None,
        timeout: int = 30,
    ) -> Any:
        pass

    @abstractmethod
    async def send_message(
        self,
        *,
        chat_id: int | None = None,
        user_id: int | None = None,
        text: str | None = None,
        attachments: list[Any] | None = None,
        format: str | None = None,
    ) -> Any:
        pass

    @abstractmethod
    async def edit_message(
        self,
        message_id: str,
        *,
        text: str | None = None,
        attachments: list[Any] | None = None,
        format: str | None = None,
    ) -> Any:
        pass

    async def reply(
        self,
        update: Any,
        text: str,
        *,
        attachments: list[Any] | None = None,
    ) -> Any:
        user_id = sender_user_id(update)
        target_chat_id = extract_chat_id(update)
        if user_id is not None:
            return await self.send_message(
                user_id=user_id,
                text=text,
                attachments=attachments,
            )
        if target_chat_id is not None:
            return await self.send_message(
                chat_id=target_chat_id,
                text=text,
                attachments=attachments,
            )
        raise ValueError("Не найден получатель для ответа")

    async def edit_reply(
        self,
        update: Any,
        text: str,
        *,
        attachments: list[Any] | None = None,
    ) -> Any:
        mid = message_mid(update)
        if mid:
            return await self.edit_message(
                mid,
                text=text,
                attachments=attachments,
            )
        return await self.reply(update, text, attachments=attachments)

    async def set_commands(self, commands: list[tuple[str, str]]) -> None:
        return None


class MaxBotClient(BotClient):
    """Direct MAX Bot API adapter, kept behind the existing BotClient contract."""

    def __init__(self, token: str) -> None:
        self._token = token
        self._client: httpx.AsyncClient | None = None
        self._started = False

    async def start(self) -> None:
        self._client = create_max_api_client(
            base_url=settings.max_api_base_url.rstrip("/"),
            headers={"Authorization": self._token},
            timeout=httpx.Timeout(35.0, connect=8.0),
        )
        self._started = True

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._started = False

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("MAX Bot API client has not been started")
        return self._client

    @staticmethod
    def _json_attachments(attachments: list[Any] | None) -> list[Any] | None:
        def convert(value: Any) -> Any:
            if hasattr(value, "model_dump"):
                return value.model_dump(mode="json", exclude_none=True)
            if is_dataclass(value):
                return asdict(value)
            if isinstance(value, list):
                return [convert(item) for item in value]
            if isinstance(value, dict):
                return {key: convert(item) for key, item in value.items()}
            return value

        return convert(attachments) if attachments is not None else None

    async def get_updates(
        self,
        *,
        marker: int | None = None,
        timeout: int = 30,
    ) -> Any:
        if not 0 <= timeout <= 90:
            raise ValueError("MAX long-polling timeout must be between 0 and 90 seconds")
        params: dict[str, object] = {"limit": 100, "timeout": timeout}
        if marker is not None:
            params["marker"] = marker
        response = await self._http().get(
            "/updates",
            params=params,
            timeout=httpx.Timeout(float(max(35, timeout + 5)), connect=8.0),
        )
        response.raise_for_status()
        return response.json()

    async def get_subscriptions(self) -> list[dict[str, Any]]:
        """Return current webhook subscriptions as reported by MAX."""
        response = await self._http().get("/subscriptions")
        response.raise_for_status()
        payload = response.json()
        subscriptions = payload.get("subscriptions") if isinstance(payload, dict) else None
        if not isinstance(subscriptions, list):
            raise RuntimeError("MAX returned an invalid /subscriptions response")
        if not all(isinstance(subscription, dict) for subscription in subscriptions):
            raise RuntimeError("MAX returned an invalid subscription entry")
        return subscriptions

    async def ensure_no_webhook_subscription(self) -> None:
        """Fail closed because MAX does not deliver updates through both transports."""
        subscriptions = await self.get_subscriptions()
        if subscriptions:
            urls = [str(item.get("url") or "<URL не указан>") for item in subscriptions]
            raise RuntimeError(
                "MAX Long Polling недоступен, пока у бота есть webhook-подписка: "
                f"{', '.join(urls)}. Для локальной разработки выполните "
                "python -m app.integrations.unsubscribe_webhook"
            )

    async def send_message(
        self,
        *,
        chat_id: int | None = None,
        user_id: int | None = None,
        text: str | None = None,
        attachments: list[Any] | None = None,
        format: str | None = None,
    ) -> Any:
        recipient = {"user_id": user_id} if user_id is not None else {"chat_id": chat_id}
        if user_id is None and chat_id is None:
            raise ValueError("MAX recipient is required")
        body: dict[str, Any] = {"text": text}
        if attachments is not None:
            body["attachments"] = self._json_attachments(attachments)
        if format is not None:
            body["format"] = format
        response = await self._http().post("/messages", params=recipient, json=body)
        response.raise_for_status()
        logger.info("MAX POST /messages успешно завершён (HTTP {})", response.status_code)
        return response.json()

    async def edit_message(
        self,
        message_id: str,
        *,
        text: str | None = None,
        attachments: list[Any] | None = None,
        format: str | None = None,
    ) -> Any:
        body: dict[str, Any] = {"text": text}
        if attachments is not None:
            body["attachments"] = self._json_attachments(attachments)
        if format is not None:
            body["format"] = format
        response = await self._http().put("/messages", params={"message_id": message_id}, json=body)
        response.raise_for_status()
        return response.json()

    async def set_commands(self, commands: list[tuple[str, str]]) -> None:
        body = {
            "commands": [
                {"name": name, "description": description}
                for name, description in commands
            ]
        }
        response = await self._http().patch("/me/commands", json=body)
        response.raise_for_status()
