"""Отправка уведомлений охранникам и админам."""

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.context import current_bot
from app.db.models import GuardAccessRequest, Role, User, VisitRequest
from app.keyboards.menus import guard_access_menu, visit_decision_menu


def visit_notice_text(visit: VisitRequest, resident: User | None) -> str:
    resident_name = resident.full_name if resident and resident.full_name else "неизвестно"
    return (
        "🔔 Новый запрос на визит\n"
        f"👤 Гость: {visit.guest_name}\n"
        f"🚪 Квартира: {visit.apartment or '—'}\n"
        f"🎯 Цель: {visit.purpose}\n"
        f"🏠 Жилец: {resident_name}"
    )


def guard_application_text(applicant: User | None, request_id: int) -> str:
    name = applicant.full_name if applicant and applicant.full_name else "неизвестно"
    nick = f"@{applicant.username}" if applicant and applicant.username else "—"
    user_id = applicant.id if applicant else "—"
    return (
        "🛡 Новая заявка на роль охранника\n"
        f"#{request_id}\n"
        f"👤 {name}\n"
        f"id={user_id} · {nick}\n\n"
        "Дать доступ или отклонить?"
    )


async def notify_guards(session: AsyncSession, visit: VisitRequest) -> None:
    bot = current_bot.get()
    if bot is None:
        logger.error("notify_guards: бот не задан в контексте")
        return

    resident = await session.get(User, visit.resident_id)

    guards = (
        await session.scalars(
            select(User).where(
                User.role == Role.GUARD,
                User.is_active.is_(True),
            )
        )
    ).all()
    guard_ids = [guard.id for guard in guards]
    text = visit_notice_text(visit, resident)
    keyboard = visit_decision_menu(visit.id)

    if not guard_ids:
        logger.info("Нет активных охранников для заявки #{}", visit.id)
        return

    for guard_id in guard_ids:
        try:
            await bot.send_message(
                user_id=guard_id,
                text=text,
                attachments=[keyboard],
            )
        except Exception:
            logger.exception("Не удалось уведомить охранника id={}", guard_id)


async def notify_admins(session: AsyncSession, request: GuardAccessRequest) -> None:
    bot = current_bot.get()
    if bot is None:
        logger.error("notify_admins: бот не задан в контексте")
        return

    applicant = await session.get(User, request.user_id)
    admins = (
        await session.scalars(
            select(User).where(
                User.role == Role.ADMIN,
                User.is_active.is_(True),
            )
        )
    ).all()
    admin_ids = [admin.id for admin in admins if admin.id != request.user_id]
    text = guard_application_text(applicant, request.id)
    keyboard = guard_access_menu(request.id)

    if not admin_ids:
        logger.info("Нет админов для заявки охранника #{}", request.id)
        return

    for admin_id in admin_ids:
        try:
            await bot.send_message(
                user_id=admin_id,
                text=text,
                attachments=[keyboard],
            )
        except Exception:
            logger.exception("Не удалось уведомить админа id={}", admin_id)
