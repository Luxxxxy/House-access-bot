from __future__ import annotations

from app.config import settings
from app.integrations.max_tls import create_max_api_client


class MaxApiClient:
    """Small transport wrapper for the current official MAX Bot API host."""

    def __init__(self) -> None:
        self.base_url = settings.max_api_base_url.rstrip("/")

    async def send_message(self, user_id: int, text: str, *, app_url: str | None = None) -> None:
        if not settings.max_bot_token:
            raise RuntimeError("MAX_BOT_TOKEN is not configured")
        body: dict = {"text": text}
        if app_url:
            body["attachments"] = [
                {
                    "type": "inline_keyboard",
                    "payload": {"buttons": [[{"type": "link", "text": "Открыть приложение", "url": app_url}]]},
                }
            ]
        async with create_max_api_client(
            base_url=self.base_url,
            headers={"Authorization": settings.max_bot_token},
            timeout=8.0,
        ) as client:
            response = await client.post(
                "/messages",
                params={"user_id": user_id},
                json=body,
            )
            response.raise_for_status()
