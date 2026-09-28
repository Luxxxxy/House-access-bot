"""Хендлеры охранника: уведомления о визитах и подтверждение пропуска."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app.bot.client import BotClient
from app.bot.dispatcher import Router
from app.bot.updates import (
    callback_payload,
    message_mid,
    message_text,
    parse_command,
)
from app.db.models import Role, User, VisitRequest, VisitStatus
from app.db.session import async_session_maker
from app.fsm.states import GuardDecision
from app.fsm.storage import fsm
from app.keyboards.menus import (
    GUARD_HISTORY,
    GUARD_PENDING,
    VISIT_APPROVE_PREFIX,
    VISIT_REJECT_PREFIX,
    VISIT_REJECT_SKIP_PREFIX,
    back_menu,
    reject_skip_menu,
    visit_decision_menu,
)
from app.services.notifications import visit_notice_text
from app.services.permissions import load_required_user

router = Router(name="guard")

STATUS_LABELS = {
    VisitStatus.PENDING: "ожидает",
    VisitStatus.APPROVED: "одобрена",
    VisitStatus.REJECTED: "отклонена",
    VisitStatus.EXPIRED: "истекла",
}


def _parse_id(payload: str | None, prefix: str) -> int | None:
    if not payload or not payload.startswith(prefix):
        return None
    raw = payload[len(prefix) :]
    try:
        return int(raw)
    except ValueError:
        return None


def _parse_visit_number(text: str) -> int | None:
    raw = text.strip().lstrip("#№").strip()
    if raw.isdigit():
        return int(raw)
    return None


def _keep_visit_list(guard_id: int) -> None:
    fsm.set_state(guard_id, GuardDecision.WAITING_VISIT_ID)


async def _require_guard(bot: BotClient, update: Any) -> User | None:
    return await load_required_user(bot, update, Role.GUARD)


def _format_dt(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.strftime("%d.%m.%Y %H:%M")


async def _load_visit_pack(visit_id: int) -> tuple[VisitRequest, User | None, User | None] | None:
    async with async_session_maker() as session:
        visit = await session.scalar(
            select(VisitRequest)
            .options(
                selectinload(VisitRequest.resident),
                selectinload(VisitRequest.guard),
            )
            .where(VisitRequest.id == visit_id)
        )
        if visit is None:
            return None
        return visit, visit.resident, visit.guard


async def _try_resolve(
    visit_id: int,
    guard: User,
    status: VisitStatus,
    comment: str | None = None,
) -> VisitRequest | None:
    values: dict[str, Any] = {
        "status": status,
        "guard_id": guard.id,
        "resolved_at": datetime.now(UTC),
    }
    if comment is not None:
        values["comment"] = comment

    async with async_session_maker() as session:
        result = await session.execute(
            update(VisitRequest)
            .where(
                VisitRequest.id == visit_id,
                VisitRequest.status == VisitStatus.PENDING,
            )
            .values(**values)
        )
        rowcount = int(getattr(result, "rowcount", 0) or 0)
        await session.commit()
        if rowcount != 1:
            return None
        return await session.scalar(
            select(VisitRequest)
            .options(
                selectinload(VisitRequest.resident),
                selectinload(VisitRequest.guard),
            )
            .where(VisitRequest.id == visit_id)
        )


def _resolved_guard_text(
    visit: VisitRequest,
    resident: User | None,
    verdict: str,
) -> str:
    base = visit_notice_text(visit, resident)
    extra = f"\n\n{verdict}"
    if visit.comment:
        extra += f"\nКомментарий: {visit.comment}"
    return base + extra


async def _edit_guard_notice(
    bot: BotClient,
    update: Any,
    text: str,
    stored_mid: str | None = None,
) -> None:
    mid = stored_mid or message_mid(update)
    try:
        if mid:
            await bot.edit_message(mid, text=text, attachments=[])
            return
        await bot.edit_reply(update, text, attachments=[])
    except Exception:
        logger.exception("Не удалось отредактировать сообщение охранника")
        await bot.reply(update, text)


async def _notify_resident(bot: BotClient, resident_id: int, text: str) -> None:
    try:
        await bot.send_message(user_id=resident_id, text=text)
    except Exception:
        logger.exception("Не удалось уведомить жильца id={}", resident_id)


@router.callback_prefix(VISIT_APPROVE_PREFIX)
async def approve_visit(bot: BotClient, update: Any) -> None:
    guard = await _require_guard(bot, update)
    if guard is None:
        return
    visit_id = _parse_id(callback_payload(update), VISIT_APPROVE_PREFIX)
    if visit_id is None:
        await bot.reply(update, "Некорректная заявка.")
        return

    from_list = fsm.get_state(guard.id) == GuardDecision.WAITING_VISIT_ID
    fsm.clear(guard.id)
    visit = await _try_resolve(visit_id, guard, VisitStatus.APPROVED)
    if visit is None:
        pack = await _load_visit_pack(visit_id)
        if pack is None:
            await bot.reply(update, "Заявка не найдена.")
            return
        existing, resident, _ = pack
        await _edit_guard_notice(
            bot,
            update,
            _resolved_guard_text(existing, resident, "Уже обработана."),
        )
        await bot.reply(update, "Заявка уже обработана.")
        if from_list:
            _keep_visit_list(guard.id)
        return

    resident = visit.resident
    guard_name = guard.full_name or "охранник"
    await _edit_guard_notice(
        bot,
        update,
        _resolved_guard_text(visit, resident, "Одобрено"),
    )
    await _notify_resident(
        bot,
        visit.resident_id,
        f"✅ Ваш гость {visit.guest_name} одобрен охранником {guard_name}",
    )
    await bot.reply(update, f"Заявка #{visit.id} одобрена.")
    if from_list:
        _keep_visit_list(guard.id)


@router.callback_prefix(VISIT_REJECT_PREFIX)
async def start_reject(bot: BotClient, update: Any) -> None:
    guard = await _require_guard(bot, update)
    if guard is None:
        return
    payload = callback_payload(update)
    if payload and payload.startswith(VISIT_REJECT_SKIP_PREFIX):
        return
    visit_id = _parse_id(payload, VISIT_REJECT_PREFIX)
    if visit_id is None:
        await bot.reply(update, "Некорректная заявка.")
        return

    pack = await _load_visit_pack(visit_id)
    if pack is None:
        await bot.reply(update, "Заявка не найдена.")
        return
    visit, _, _ = pack
    if visit.status != VisitStatus.PENDING:
        await bot.reply(update, "Заявка уже обработана.")
        return

    from_list = fsm.get_state(guard.id) == GuardDecision.WAITING_VISIT_ID
    fsm.set_state(
        guard.id,
        GuardDecision.WAITING_REJECT_COMMENT,
        visit_id=visit_id,
        message_id=message_mid(update),
        from_list=from_list,
    )
    await bot.reply(
        update,
        "Напишите комментарий к отклонению или нажмите «Без комментария».",
        attachments=[reject_skip_menu(visit_id)],
    )


@router.callback_prefix(VISIT_REJECT_SKIP_PREFIX)
async def reject_without_comment(bot: BotClient, update: Any) -> None:
    await _finish_reject(bot, update, comment=None)


@router.state(GuardDecision.WAITING_REJECT_COMMENT)
async def reject_with_comment(bot: BotClient, update: Any) -> None:
    guard = await _require_guard(bot, update)
    if guard is None:
        return
    if parse_command(message_text(update)):
        await bot.reply(
            update,
            "Напишите комментарий или нажмите «Без комментария». /cancel — отмена.",
        )
        return

    comment = message_text(update)
    if not comment:
        await bot.reply(update, "Комментарий пустой. Напишите текст или нажмите «Без комментария».")
        return
    if len(comment) > 1024:
        await bot.reply(update, "Комментарий слишком длинный (до 1024 символов).")
        return
    await _finish_reject(bot, update, comment=comment)


async def _finish_reject(
    bot: BotClient,
    update: Any,
    comment: str | None,
) -> None:
    guard = await _require_guard(bot, update)
    if guard is None:
        return

    payload = callback_payload(update)
    visit_id = _parse_id(payload, VISIT_REJECT_SKIP_PREFIX)
    data = fsm.get_data(guard.id)
    stored_mid = data.get("message_id")
    from_list = bool(data.get("from_list"))
    if visit_id is None:
        raw = data.get("visit_id")
        visit_id = int(raw) if raw is not None else None
    fsm.clear(guard.id)

    if visit_id is None:
        await bot.reply(update, "Не удалось определить заявку. Начните заново.")
        if from_list:
            _keep_visit_list(guard.id)
        return

    visit = await _try_resolve(
        visit_id,
        guard,
        VisitStatus.REJECTED,
        comment=comment,
    )
    if visit is None:
        pack = await _load_visit_pack(visit_id)
        if pack is None:
            await bot.reply(update, "Заявка не найдена.")
            if from_list:
                _keep_visit_list(guard.id)
            return
        existing, resident, _ = pack
        await _edit_guard_notice(
            bot,
            update,
            _resolved_guard_text(existing, resident, "Уже обработана."),
            stored_mid=stored_mid,
        )
        await bot.reply(update, "Заявка уже обработана.")
        if from_list:
            _keep_visit_list(guard.id)
        return

    resident = visit.resident
    guard_name = guard.full_name or "охранник"
    await _edit_guard_notice(
        bot,
        update,
        _resolved_guard_text(visit, resident, "Отклонено"),
        stored_mid=stored_mid,
    )
    text = f"❌ Ваш гость {visit.guest_name} отклонён охранником {guard_name}"
    if visit.comment:
        text += f"\nКомментарий: {visit.comment}"
    await _notify_resident(bot, visit.resident_id, text)
    await bot.reply(update, f"Заявка #{visit.id} отклонена.")
    if from_list:
        _keep_visit_list(guard.id)


@router.callback(GUARD_PENDING)
async def list_pending(bot: BotClient, update: Any) -> None:
    guard = await _require_guard(bot, update)
    if guard is None:
        return

    async with async_session_maker() as session:
        visits = (
            await session.scalars(
                select(VisitRequest)
                .options(selectinload(VisitRequest.resident))
                .where(VisitRequest.status == VisitStatus.PENDING)
                .order_by(VisitRequest.created_at.asc())
            )
        ).all()
        items = [
            (
                visit.id,
                visit.guest_name,
                visit.apartment,
                visit.purpose,
                visit.created_at,
                visit.resident.full_name if visit.resident else "—",
            )
            for visit in visits
        ]

    if not items:
        fsm.clear(guard.id)
        await bot.reply(update, "Новых заявок нет.", attachments=[back_menu()])
        return

    lines = [
        f"📥 Новые заявки ({len(items)}):",
        "Введите номер заявки в чат, чтобы принять или отклонить её.",
    ]
    for visit_id, guest, apartment, purpose, created, resident_name in items:
        lines.append(
            f"#{visit_id} · {_format_dt(created)}\n"
            f"Гость: {guest}\n"
            f"Квартира: {apartment or '—'}\n"
            f"Цель: {purpose}\n"
            f"Жилец: {resident_name}"
        )
    fsm.set_state(guard.id, GuardDecision.WAITING_VISIT_ID)
    await bot.reply(update, "\n\n".join(lines), attachments=[back_menu()])


@router.state(GuardDecision.WAITING_VISIT_ID)
async def on_visit_number(bot: BotClient, update: Any) -> None:
    guard = await _require_guard(bot, update)
    if guard is None:
        return
    if parse_command(message_text(update)):
        await bot.reply(
            update,
            "Введите номер заявки, например 12, или /cancel.",
            attachments=[back_menu()],
        )
        return

    visit_id = _parse_visit_number(message_text(update))
    if visit_id is None:
        await bot.reply(
            update,
            "Введите номер заявки из списка, например 12 или #12.",
            attachments=[back_menu()],
        )
        return

    pack = await _load_visit_pack(visit_id)
    if pack is None:
        await bot.reply(update, f"Заявка #{visit_id} не найдена.", attachments=[back_menu()])
        return
    visit, resident, _ = pack
    if visit.status != VisitStatus.PENDING:
        await bot.reply(
            update,
            f"Заявка #{visit_id} уже обработана.",
            attachments=[back_menu()],
        )
        return

    _keep_visit_list(guard.id)
    await bot.reply(
        update,
        visit_notice_text(visit, resident),
        attachments=[visit_decision_menu(visit.id)],
    )


@router.callback(GUARD_HISTORY)
async def list_history(bot: BotClient, update: Any) -> None:
    guard = await _require_guard(bot, update)
    if guard is None:
        return

    async with async_session_maker() as session:
        visits = (
            await session.scalars(
                select(VisitRequest)
                .options(
                    selectinload(VisitRequest.resident),
                    selectinload(VisitRequest.guard),
                )
                .where(VisitRequest.status != VisitStatus.PENDING)
                .order_by(
                    VisitRequest.resolved_at.desc(),
                    VisitRequest.created_at.desc(),
                )
                .limit(20)
            )
        ).all()
        items = [
            (
                visit.id,
                visit.guest_name,
                visit.apartment,
                visit.status,
                visit.resolved_at or visit.created_at,
                visit.guard.full_name if visit.guard else "—",
                visit.comment,
            )
            for visit in visits
        ]

    if not items:
        await bot.reply(update, "История пуста.", attachments=[back_menu()])
        return

    lines = ["✅ История (последние 20):"]
    for visit_id, guest, apartment, status, when, guard_name, comment in items:
        label = STATUS_LABELS.get(status, str(status))
        line = (
            f"#{visit_id} · {_format_dt(when)} · {label}\n"
            f"Гость: {guest}\n"
            f"Квартира: {apartment or '—'}\n"
            f"Охранник: {guard_name}"
        )
        if comment:
            line += f"\nКомментарий: {comment}"
        lines.append(line)
    await bot.reply(update, "\n\n".join(lines), attachments=[back_menu()])
