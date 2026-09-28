from __future__ import annotations

import hashlib
import hmac
import json
from urllib.parse import quote

from fastapi import APIRouter, Header, HTTPException, Request, status
from loguru import logger
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.domain.models import WebhookEvent
from app.integrations.max_api import MaxApiClient
from app.web.db import SessionLocal

router = APIRouter(tags=["MAX integration"])


def _miniapp_link(payload: str | None = None) -> str | None:
    if settings.max_bot_name:
        link = f"https://max.ru/{quote(settings.max_bot_name, safe='')}?startapp"
        if payload and all(char.isalnum() or char in "_-" for char in payload) and len(payload) <= 512:
            link += f"={quote(payload, safe='_-')}"
        return link
    if settings.miniapp_url.startswith("https://"):
        return settings.miniapp_url
    return None


def _user_id(update: dict) -> int | None:
    message = update.get("message") or {}
    sender = message.get("sender") or {}
    callback = update.get("callback") or {}
    user = callback.get("user") or {}
    started_user = update.get("user") or {}
    value = sender.get("user_id") or user.get("user_id") or started_user.get("user_id") or update.get("user_id")
    try:
        return int(value) if value is not None else None
    except (ValueError, TypeError):
        return None


@router.post("/max/webhook", include_in_schema=False)
async def max_webhook(
    request: Request,
    secret: str | None = Header(default=None, alias="X-Max-Bot-Api-Secret"),
):
    if settings.max_update_mode == "long_polling":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "MAX webhook is disabled while MAX_UPDATE_MODE=long_polling",
        )
    expected = settings.max_webhook_secret
    if (
        not expected
        or not secret
        or not hmac.compare_digest(expected.encode("utf-8"), secret.encode("utf-8"))
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid webhook secret")
    chunks: list[bytes] = []
    received_bytes = 0
    async for chunk in request.stream():
        received_bytes += len(chunk)
        if received_bytes > 256_000:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Webhook payload is too large")
        chunks.append(chunk)
    raw = b"".join(chunks)
    try:
        update = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid webhook payload") from None
    if not isinstance(update, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid webhook payload")

    event_value = update.get("update_id")
    event_key = (
        str(event_value)
        if event_value is not None
        else f"{update.get('update_type', '')}:{update.get('timestamp', '')}:{_user_id(update) or ''}:{hashlib.sha256(raw).hexdigest()}"
    )
    async with SessionLocal() as session:
        session.add(WebhookEvent(event_key=event_key))
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return {"ok": True, "duplicate": True}

    event_type = update.get("update_type")
    body = (update.get("message") or {}).get("body") or {}
    text = str(body.get("text") or "").strip()
    command = text.split(maxsplit=1)[0].lower() if text else ""
    if event_type == "bot_started" or command in {"/start", "/app"}:
        user_id = _user_id(update)
        if user_id is not None and settings.max_bot_token:
            try:
                payload = update.get("payload")
                await MaxApiClient().send_message(
                    user_id,
                    "Сервис цифровых заявок на проход. Здесь можно оформить пропуск или проверить заявки.",
                    app_url=_miniapp_link(str(payload) if payload else None),
                )
            except Exception:
                # MAX retries non-200 webhook requests; remove the idempotency key to let it retry.
                async with SessionLocal() as session:
                    await session.delete(await session.get(WebhookEvent, event_key))
                    await session.commit()
                logger.exception("MAX welcome message could not be delivered")
                raise HTTPException(503, "MAX message delivery failed") from None
    return {"ok": True}
