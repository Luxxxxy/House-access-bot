from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger
from sqlalchemy import or_, select, update

from app.config import settings
from app.domain.logic import is_request_expired
from app.domain.models import (
    Notification,
    RegistryImport,
    ResidentialComplex,
    VisitEvent,
    VisitRequest,
    WebhookEvent,
)
from app.integrations.max_api import MaxApiClient
from app.web.db import SessionLocal


async def dispatch_notifications() -> None:
    # The local mock mode intentionally keeps a visible PENDING outbox instead of
    # recording a false MAX delivery. Add a token to enable real delivery.
    if not settings.max_bot_token:
        return
    now = datetime.now(timezone.utc)
    async with SessionLocal() as session:
        await session.execute(
            update(Notification)
            .where(
                Notification.status == "PROCESSING",
                Notification.attempts >= 5,
                Notification.locked_until < now,
            )
            .values(
                status="FAILED",
                locked_until=None,
                last_error="Delivery lease expired after the final attempt",
            )
        )
        result = await session.scalars(
            select(Notification)
            .where(
                Notification.attempts < 5,
                or_(
                    (Notification.status == "PENDING") & (Notification.next_attempt_at <= now),
                    (Notification.status == "PROCESSING") & (Notification.locked_until < now),
                ),
            )
            .order_by(Notification.created_at)
            .limit(20)
            .with_for_update(skip_locked=True)
        )
        messages = list(result)
        for message in messages:
            message.status = "PROCESSING"
            message.locked_until = now + timedelta(seconds=60)
            message.attempts += 1
        await session.commit()
        payloads = [(message.id, message.recipient_id, message.text, message.attempts) for message in messages]

    client = MaxApiClient()
    for message_id, recipient, text, attempts in payloads:
        try:
            app_url = (
                f"https://max.ru/{settings.max_bot_name}?startapp" if settings.max_bot_name else None
            )
            await client.send_message(recipient, text, app_url=app_url)
        except Exception as error:
            async with SessionLocal() as session:
                message = await session.get(Notification, message_id)
                if message is not None:
                    message.status = "FAILED" if attempts >= 5 else "PENDING"
                    message.locked_until = None
                    message.next_attempt_at = datetime.now(timezone.utc) + timedelta(
                        seconds=min(3600, 30 * (2 ** (attempts - 1)))
                    )
                    message.last_error = type(error).__name__[:300]
                    await session.commit()
            logger.warning("MAX notification delivery failed ({})", type(error).__name__)
        else:
            async with SessionLocal() as session:
                message = await session.get(Notification, message_id)
                if message is not None:
                    message.status = "SENT"
                    message.sent_at = datetime.now(timezone.utc)
                    message.locked_until = None
                    message.last_error = None
                    await session.commit()
        await asyncio.sleep(0.5)


async def cleanup_visit_requests() -> None:
    now = datetime.now(timezone.utc)
    async with SessionLocal() as session:
        result = await session.execute(
            select(VisitRequest, ResidentialComplex.timezone)
            .join(ResidentialComplex, ResidentialComplex.id == VisitRequest.complex_id)
            .where(VisitRequest.status != "DELETED")
            .where(
                or_(
                    VisitRequest.status.in_(("ACTIVE", "CANCELLED")),
                    VisitRequest.created_at < now - timedelta(days=14),
                )
            )
            .order_by(VisitRequest.created_at)
            .limit(1000)
            .with_for_update(skip_locked=True)
        )
        rows = list(result)
        removed = 0
        expired = 0
        purged_auxiliary = 0
        for request, tz in rows:
            created = request.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if now >= created + timedelta(days=14):
                await session.delete(request)
                removed += 1
                continue
            if request.status == "ACTIVE" and is_request_expired(request, now, tz):
                request.status = "EXPIRED"
                request.resolved_at = now
                session.add(
                    VisitEvent(
                        request_id=request.id,
                        event_type="EXPIRED",
                        metadata_json={"source": "retention_job"},
                    )
                )
                expired += 1
        expired_imports = await session.scalars(
            select(RegistryImport)
            .where(RegistryImport.expires_at < now, RegistryImport.confirmed_at.is_(None))
            .limit(500)
        )
        for imported in expired_imports:
            await session.delete(imported)
            purged_auxiliary += 1
        old_webhooks = await session.scalars(
            select(WebhookEvent)
            .where(WebhookEvent.received_at < now - timedelta(days=14))
            .limit(1000)
        )
        for webhook_event in old_webhooks:
            await session.delete(webhook_event)
            purged_auxiliary += 1
        old_notifications = await session.scalars(
            select(Notification)
            .where(Notification.created_at < now - timedelta(days=14))
            .limit(1000)
        )
        for notification in old_notifications:
            await session.delete(notification)
            purged_auxiliary += 1
        if removed or expired or purged_auxiliary:
            await session.commit()
        logger.info("Visit cleanup completed: expired={}, removed={}", expired, removed)


async def run_worker() -> None:
    scheduler = AsyncIOScheduler(timezone=ZoneInfo(settings.timezone))
    scheduler.add_job(dispatch_notifications, "interval", seconds=2, max_instances=1, coalesce=True)
    scheduler.add_job(cleanup_visit_requests, "interval", minutes=5, max_instances=1, coalesce=True)
    scheduler.start()
    logger.info("Background worker started")
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    asyncio.run(run_worker())
