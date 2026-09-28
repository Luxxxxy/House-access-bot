from __future__ import annotations

import asyncio

from app.config import settings
from app.integrations.max_tls import create_max_api_client


async def main() -> None:
    if settings.max_update_mode != "webhook":
        raise SystemExit(
            "Webhook subscription запрещена при MAX_UPDATE_MODE=long_polling; "
            "переключите MAX_UPDATE_MODE=webhook"
        )
    if not settings.max_bot_token or not settings.max_webhook_secret:
        raise SystemExit("Set MAX_BOT_TOKEN and MAX_WEBHOOK_SECRET before subscribing")
    if not settings.app_base_url.startswith("https://"):
        raise SystemExit("APP_BASE_URL must be the public HTTPS origin")
    url = f"{settings.app_base_url.rstrip('/')}/api/v1/max/webhook"
    async with create_max_api_client(timeout=15) as client:
        response = await client.post(
            "/subscriptions",
            headers={"Authorization": settings.max_bot_token},
            json={
                "url": url,
                "update_types": ["bot_started", "message_created"],
                "secret": settings.max_webhook_secret,
            },
        )
        response.raise_for_status()
        print(f"Webhook subscription registered for {url}")


if __name__ == "__main__":
    asyncio.run(main())
