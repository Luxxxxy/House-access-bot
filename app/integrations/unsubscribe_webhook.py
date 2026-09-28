"""Safely remove this application's MAX webhook while switching to local polling."""

from __future__ import annotations

import asyncio

from app.config import settings
from app.integrations.max_tls import create_max_api_client


def _configured_webhook_url() -> str:
    return f"{settings.app_base_url.rstrip('/')}/api/v1/max/webhook"


async def main() -> None:
    if settings.environment.lower() != "development":
        raise SystemExit("Удалять webhook этой командой можно только в development")
    if settings.max_update_mode != "long_polling":
        raise SystemExit("Перед отпиской задайте MAX_UPDATE_MODE=long_polling")
    if not settings.max_bot_token:
        raise SystemExit("Задайте MAX_BOT_TOKEN")

    base_url = settings.max_api_base_url.rstrip("/")
    headers = {"Authorization": settings.max_bot_token}
    target_url = _configured_webhook_url()
    async with create_max_api_client(
        base_url=base_url,
        headers=headers,
        timeout=15,
    ) as client:
        response = await client.get("/subscriptions")
        response.raise_for_status()
        payload = response.json()
        subscriptions = payload.get("subscriptions") if isinstance(payload, dict) else None
        if not isinstance(subscriptions, list):
            raise SystemExit("MAX вернул некорректный список подписок; ничего не изменено")

        active_urls = {
            str(subscription.get("url"))
            for subscription in subscriptions
            if isinstance(subscription, dict) and subscription.get("url")
        }
        if target_url not in active_urls:
            if active_urls:
                raise SystemExit(
                    "Активная webhook-подписка не совпадает с APP_BASE_URL. "
                    "Ничего не удалено. Укажите в APP_BASE_URL origin существующей "
                    "подписки и повторите команду."
                )
            print("Активных webhook-подписок нет; Long Polling можно запускать.")
            return

        response = await client.delete("/subscriptions", params={"url": target_url})
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict) or result.get("success") is not True:
            message = result.get("message") if isinstance(result, dict) else None
            raise SystemExit(f"MAX не удалил webhook-подписку: {message or 'неизвестная ошибка'}")
        print(f"Webhook-подписка удалена: {target_url}")


if __name__ == "__main__":
    asyncio.run(main())
