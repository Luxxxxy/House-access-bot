"""Хендлеры админа: заявки охранников, снятие доступа, статистика."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy import update as sa_update

from app.bot.client import BotClient
from app.bot.dispatcher import Router
from app.bot.updates import callback_payload, sender_user_id
from app.config import settings
from app.db.models import (
    GuardAccessRequest,
    GuardAccessStatus,
    Role,
    User,
    VisitRequest,
    VisitStatus,
)
from app.db.session import async_session_maker
from app.keyboards.menus import (
    ADMIN_DEACTIVATE_PREFIX,
    ADMIN_GUARDS,
    ADMIN_REMOVE_GUARD,
    ADMIN_STATS,
    GUARD_APPLY_APPROVE_PREFIX,
    GUARD_APPLY_REJECT_PREFIX,
    admin_menu,
    back_menu,
    deactivate_guards_menu,
    guard_access_menu,
    guard_menu,
)
from app.services.notifications import guard_application_text
from app.services.permissions import load_required_user, require_role

router = Router(name="admin")


def _guard_label(user: User) -> str:
    name = user.full_name or "без имени"
    nick = f"@{user.username}" if user.username else "—"
    return f"{name} ({nick})"


def _parse_id(payload: str | None, prefix: str) -> int | None:
    if not payload or not payload.startswith(prefix):
        return None
    raw = payload[len(prefix) :]
    try:
        return int(raw)
    except ValueError:
        return None


async def _try_resolve_application(
    request_id: int,
    admin: User,
    status: GuardAccessStatus,
) -> GuardAccessRequest | None:
    async with async_session_maker() as session:
        result = await session.execute(
            sa_update(GuardAccessRequest)
            .where(
                GuardAccessRequest.id == request_id,
                GuardAccessRequest.status == GuardAccessStatus.PENDING,
            )
            .values(
                status=status,
                admin_id=admin.id,
                resolved_at=datetime.now(UTC),
            )
        )
        rowcount = int(getattr(result, "rowcount", 0) or 0)
        await session.commit()
        if rowcount != 1:
            return None
        return await session.get(GuardAccessRequest, request_id)


async def _notify_applicant(
    bot: BotClient,
    user_id: int,
    text: str,
    attachments: list[Any] | None = None,
) -> None:
    try:
        await bot.send_message(user_id=user_id, text=text, attachments=attachments)
    except Exception:
        logger.exception("Не удалось уведомить заявителя id={}", user_id)


@router.callback(ADMIN_GUARDS)
@require_role(Role.ADMIN)
async def list_guards(bot: BotClient, update: Any) -> None:
    async with async_session_maker() as session:
        pending = (
            await session.scalars(
                select(GuardAccessRequest)
                .where(GuardAccessRequest.status == GuardAccessStatus.PENDING)
                .order_by(GuardAccessRequest.created_at)
            )
        ).all()
        pending_items: list[tuple[GuardAccessRequest, User | None]] = []
        for request in pending:
            applicant = await session.get(User, request.user_id)
            pending_items.append((request, applicant))

        guards = (
            await session.scalars(
                select(User)
                .where(User.guard_approved.is_(True))
                .order_by(User.is_active.desc(), User.full_name)
            )
        ).all()
        lines = []
        for user in guards:
            if user.role == Role.GUARD:
                mode = "сейчас охранник"
            elif user.role == Role.ADMIN:
                mode = "сейчас админ"
            else:
                mode = "сейчас жилец"
            lines.append(
                f"• {_guard_label(user)}\n"
                f"  id={user.id} · одобрен · {mode}"
            )

    for request, applicant in pending_items:
        await bot.reply(
            update,
            guard_application_text(applicant, request.id),
            attachments=[guard_access_menu(request.id)],
        )

    if not lines and not pending_items:
        await bot.reply(update, "Охранников пока нет.", attachments=[back_menu()])
        return
    if lines:
        await bot.reply(
            update,
            "👮 Охранники:\n\n" + "\n\n".join(lines),
            attachments=[back_menu()],
        )


@router.callback_prefix(GUARD_APPLY_APPROVE_PREFIX)
@require_role(Role.ADMIN)
async def approve_guard_application(bot: BotClient, update: Any) -> None:
    admin = await load_required_user(bot, update, Role.ADMIN)
    if admin is None:
        return

    request_id = _parse_id(callback_payload(update), GUARD_APPLY_APPROVE_PREFIX)
    if request_id is None:
        await bot.reply(update, "Некорректный идентификатор заявки.")
        return

    async with async_session_maker() as session:
        result = await session.execute(
            sa_update(GuardAccessRequest)
            .where(
                GuardAccessRequest.id == request_id,
                GuardAccessRequest.status == GuardAccessStatus.PENDING,
            )
            .values(
                status=GuardAccessStatus.APPROVED,
                admin_id=admin.id,
                resolved_at=datetime.now(UTC),
            )
        )
        rowcount = int(getattr(result, "rowcount", 0) or 0)
        if rowcount != 1:
            await session.rollback()
            existing = await session.get(GuardAccessRequest, request_id)
            if existing is None:
                await bot.reply(update, "Заявка не найдена.")
                return
            await bot.reply(update, "Заявка уже обработана.")
            return

        request = await session.get(GuardAccessRequest, request_id)
        if request is None:
            await session.rollback()
            await bot.reply(update, "Заявка не найдена.")
            return
        target = await session.get(User, request.user_id)
        if target is None:
            await session.rollback()
            await bot.reply(update, "Пользователь заявки не найден.")
            return
        if target.role == Role.ADMIN:
            await session.rollback()
            await bot.reply(update, "Нельзя выдать роль охранника действующему админу.")
            return
        target.role = Role.GUARD
        target.is_active = True
        target.guard_approved = True
        target.approved_by_id = admin.id
        name = target.full_name or str(target.id)
        target_id = target.id
        await session.commit()

    await _notify_applicant(
        bot,
        target_id,
        "Вам выдан доступ охранника. Выберите действие:",
        attachments=[guard_menu()],
    )
    await bot.reply(
        update,
        f"Охраннику {name} (id={target_id}) выдан доступ.",
        attachments=[admin_menu()],
    )


@router.callback_prefix(GUARD_APPLY_REJECT_PREFIX)
@require_role(Role.ADMIN)
async def reject_guard_application(bot: BotClient, update: Any) -> None:
    admin = await load_required_user(bot, update, Role.ADMIN)
    if admin is None:
        return

    request_id = _parse_id(callback_payload(update), GUARD_APPLY_REJECT_PREFIX)
    if request_id is None:
        await bot.reply(update, "Некорректный идентификатор заявки.")
        return

    resolved = await _try_resolve_application(
        request_id,
        admin,
        GuardAccessStatus.REJECTED,
    )
    if resolved is None:
        await bot.reply(update, "Заявка уже обработана.")
        return

    await _notify_applicant(
        bot,
        resolved.user_id,
        "Заявка на роль охранника отклонена.",
    )
    await bot.reply(
        update,
        f"Заявка #{resolved.id} отклонена.",
        attachments=[admin_menu()],
    )


@router.callback(ADMIN_REMOVE_GUARD)
@require_role(Role.ADMIN)
async def start_remove_guard(bot: BotClient, update: Any) -> None:
    admin_id = sender_user_id(update)
    async with async_session_maker() as session:
        guards = (
            await session.scalars(
                select(User)
                .where(User.guard_approved.is_(True))
                .order_by(User.full_name)
            )
        ).all()
        buttons = [
            (user.id, f"{user.full_name or user.id}")
            for user in guards
            if admin_id is None or user.id != admin_id
        ]

    if not buttons:
        await bot.reply(
            update,
            "Нет активных охранников для снятия.",
            attachments=[back_menu()],
        )
        return
    await bot.reply(
        update,
        "Выберите охранника, которого нужно снять:",
        attachments=[deactivate_guards_menu(buttons)],
    )


@router.callback_prefix(ADMIN_DEACTIVATE_PREFIX)
@require_role(Role.ADMIN)
async def deactivate_guard(bot: BotClient, update: Any) -> None:
    admin = await load_required_user(bot, update, Role.ADMIN)
    if admin is None:
        return

    payload = callback_payload(update) or ""
    raw = payload[len(ADMIN_DEACTIVATE_PREFIX) :]
    try:
        target_id = int(raw)
    except ValueError:
        await bot.reply(update, "Некорректный идентификатор.")
        return

    if target_id == admin.id or target_id == settings.admin_max_user_id:
        await bot.reply(update, "Админ не может снять сам себя.")
        return

    async with async_session_maker() as session:
        target = await session.get(User, target_id)
        if target is None or not target.guard_approved:
            await bot.reply(update, "Охранник не найден.")
            return
        if target.role == Role.ADMIN:
            await bot.reply(update, "Админ не может снять сам себя.")
            return
        target.guard_approved = False
        if target.role == Role.GUARD:
            target.role = Role.RESIDENT
        await session.commit()
        name = target.full_name or str(target.id)

    await bot.reply(
        update,
        f"Охранник {name} (id={target_id}) снят. История заявок сохранена.",
        attachments=[admin_menu()],
    )


@router.callback(ADMIN_STATS)
@require_role(Role.ADMIN)
async def show_stats(bot: BotClient, update: Any) -> None:
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)

    async with async_session_maker() as session:
        rows = (
            await session.execute(
                select(VisitRequest.status, func.count())
                .where(
                    VisitRequest.created_at >= start,
                    VisitRequest.created_at < end,
                )
                .group_by(VisitRequest.status)
            )
        ).all()

    counts: dict[VisitStatus, int] = {status: 0 for status in VisitStatus}
    total = 0
    for status, count in rows:
        key = status if isinstance(status, VisitStatus) else VisitStatus(str(status))
        counts[key] = int(count)
        total += int(count)

    text = (
        "📊 Статистика за сегодня\n\n"
        f"Всего заявок: {total}\n"
        f"• ожидают: {counts[VisitStatus.PENDING]}\n"
        f"• одобрены: {counts[VisitStatus.APPROVED]}\n"
        f"• отклонены: {counts[VisitStatus.REJECTED]}\n"
        f"• истекли: {counts[VisitStatus.EXPIRED]}"
    )
    await bot.reply(update, text, attachments=[back_menu()])
