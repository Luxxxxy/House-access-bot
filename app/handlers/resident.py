"""Хендлеры жильца: форма визита (гость, квартира, цель)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.bot.client import BotClient
from app.bot.dispatcher import Router
from app.bot.updates import message_text, parse_command, sender_user_id
from app.db.models import Role, User, VisitRequest, VisitStatus
from app.db.session import async_session_maker
from app.fsm.states import VisitForm
from app.fsm.storage import fsm
from app.keyboards.menus import (
    RESIDENT_CANCEL,
    RESIDENT_CONFIRM,
    RESIDENT_MY_REQUESTS,
    RESIDENT_VISIT,
    back_menu,
    menu_for_role,
    visit_confirm_menu,
)
from app.services.notifications import notify_guards
from app.services.permissions import get_user, load_required_user

router = Router(name="resident")

STATUS_LABELS = {
    VisitStatus.PENDING: "ожидает",
    VisitStatus.APPROVED: "одобрена",
    VisitStatus.REJECTED: "отклонена",
    VisitStatus.EXPIRED: "истекла",
}


async def _require_visit_creator(bot: BotClient, update: Any) -> User | None:
    return await load_required_user(bot, update, Role.RESIDENT, Role.ADMIN)


@router.callback(RESIDENT_VISIT)
async def start_visit(bot: BotClient, update: Any) -> None:
    user = await _require_visit_creator(bot, update)
    if user is None:
        return
    fsm.set_state(user.id, VisitForm.WAITING_GUEST_NAME)
    await bot.reply(update, "Введите имя гостя")


@router.state(VisitForm.WAITING_GUEST_NAME)
async def on_guest_name(bot: BotClient, update: Any) -> None:
    user_id = sender_user_id(update)
    if user_id is None:
        return
    if parse_command(message_text(update)):
        await bot.reply(
            update,
            "Сейчас нужно ввести имя гостя. /cancel — отменить заявку.",
        )
        return

    name = message_text(update)
    if not name:
        await bot.reply(update, "Имя не должно быть пустым. Введите имя гостя")
        return
    if len(name) > 255:
        await bot.reply(update, "Имя слишком длинное (до 255 символов). Введите имя гостя")
        return

    fsm.set_state(user_id, VisitForm.WAITING_APARTMENT, guest_name=name)
    await bot.reply(update, "Укажите номер квартиры")


@router.state(VisitForm.WAITING_APARTMENT)
async def on_apartment(bot: BotClient, update: Any) -> None:
    user_id = sender_user_id(update)
    if user_id is None:
        return
    if parse_command(message_text(update)):
        await bot.reply(
            update,
            "Сейчас нужно указать номер квартиры. /cancel — отменить заявку.",
        )
        return

    apartment = message_text(update)
    if not apartment:
        await bot.reply(update, "Квартира не должна быть пустой. Укажите номер квартиры")
        return
    if len(apartment) > 32:
        await bot.reply(
            update,
            "Номер квартиры слишком длинный (до 32 символов). Укажите номер квартиры",
        )
        return

    fsm.set_state(user_id, VisitForm.WAITING_PURPOSE, apartment=apartment)
    await bot.reply(update, "Укажите цель визита")


@router.state(VisitForm.WAITING_PURPOSE)
async def on_purpose(bot: BotClient, update: Any) -> None:
    user_id = sender_user_id(update)
    if user_id is None:
        return

    purpose = message_text(update)
    if parse_command(purpose):
        await bot.reply(
            update,
            "Сейчас нужно указать цель визита. /cancel — отменить заявку.",
        )
        return
    if not purpose:
        await bot.reply(update, "Цель не должна быть пустой. Укажите цель визита")
        return

    data = fsm.get_data(user_id)
    guest_name = str(data.get("guest_name") or "")
    apartment = str(data.get("apartment") or "")
    fsm.set_state(user_id, VisitForm.WAITING_CONFIRM, purpose=purpose)
    await bot.reply(
        update,
        (
            "Проверьте заявку:\n\n"
            f"Гость: {guest_name}\n"
            f"Квартира: {apartment}\n"
            f"Цель: {purpose}"
        ),
        attachments=[visit_confirm_menu()],
    )


@router.state(VisitForm.WAITING_CONFIRM)
async def on_confirm_text(bot: BotClient, update: Any) -> None:
    await bot.reply(
        update,
        "Подтвердите заявку кнопками «Отправить» или «Отмена».",
        attachments=[visit_confirm_menu()],
    )


@router.callback(RESIDENT_CONFIRM)
async def confirm_visit(bot: BotClient, update: Any) -> None:
    user = await _require_visit_creator(bot, update)
    if user is None:
        return
    if fsm.get_state(user.id) != VisitForm.WAITING_CONFIRM:
        await bot.reply(update, "Сначала оформите заявку: нажмите «Оформить визит».")
        return

    data = fsm.get_data(user.id)
    guest_name = str(data.get("guest_name") or "").strip()
    apartment = str(data.get("apartment") or "").strip()
    purpose = str(data.get("purpose") or "").strip()
    if not guest_name or not apartment or not purpose:
        fsm.clear(user.id)
        await bot.reply(update, "Данные заявки потеряны. Начните заново.")
        return

    async with async_session_maker() as session:
        visit = VisitRequest(
            resident_id=user.id,
            guest_name=guest_name,
            apartment=apartment,
            purpose=purpose,
            status=VisitStatus.PENDING,
        )
        session.add(visit)
        await session.flush()
        await session.refresh(visit)
        await notify_guards(session, visit)
        await session.commit()

    fsm.clear(user.id)
    await bot.reply(
        update,
        "Заявка отправлена охраннику",
        attachments=[menu_for_role(user.role)],
    )


@router.callback(RESIDENT_CANCEL)
async def cancel_visit(bot: BotClient, update: Any) -> None:
    user_id = sender_user_id(update)
    fsm.clear(user_id)
    user = await get_user(user_id)
    attachments = [menu_for_role(user.role)] if user is not None else None
    await bot.reply(
        update,
        "Заявка отменена.",
        attachments=attachments,
    )


@router.callback(RESIDENT_MY_REQUESTS)
async def my_requests(bot: BotClient, update: Any) -> None:
    user = await _require_visit_creator(bot, update)
    if user is None:
        return
    fsm.clear(user.id)

    async with async_session_maker() as session:
        visits = (
            await session.scalars(
                select(VisitRequest)
                .where(VisitRequest.resident_id == user.id)
                .order_by(VisitRequest.created_at.desc())
                .limit(10)
            )
        ).all()

    if not visits:
        await bot.reply(update, "У вас пока нет заявок.", attachments=[back_menu()])
        return

    lines = ["Ваши последние заявки:"]
    for visit in visits:
        status = STATUS_LABELS.get(visit.status, visit.status.value)
        created = visit.created_at.strftime("%d.%m.%Y %H:%M") if visit.created_at else "—"
        lines.append(
            f"#{visit.id} · {created} · {status}\n"
            f"{visit.guest_name} · кв. {visit.apartment}: {visit.purpose}"
        )
    await bot.reply(update, "\n\n".join(lines), attachments=[back_menu()])
