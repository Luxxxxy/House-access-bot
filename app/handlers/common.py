"""Общие команды: /start, /help, выбор роли."""

from __future__ import annotations

from typing import Any

from loguru import logger
from sqlalchemy import select

from app.bot.client import BotClient
from app.bot.dispatcher import Router
from app.bot.updates import (
    message_text,
    parse_command,
    sender_name,
    sender_user_id,
    sender_username,
)
from app.config import persist_admin_max_user_id, settings
from app.db.models import GuardAccessRequest, GuardAccessStatus, Role, User
from app.db.session import async_session_maker
from app.fsm.states import AdminForm
from app.fsm.storage import fsm
from app.keyboards.menus import (
    BACK,
    CHANGE_ROLE,
    CHOOSE_ADMIN,
    CHOOSE_GUARD,
    CHOOSE_USER,
    back_menu,
    menu_for_role,
    role_choice_menu,
)
from app.services.notifications import notify_admins
from app.services.permissions import get_user

router = Router(name="common")

ROLE_TITLES = {
    Role.ADMIN: "админ",
    Role.GUARD: "охранник",
    Role.RESIDENT: "жилец",
}

HELP_TEXT = (
    "Справка по боту доступа в дом.\n\n"
    "/start — выбрать роль: пользователь, охранник или админ\n"
    "/help — эта справка\n"
    "/myrole — текущая роль\n"
    "/cancel — сбросить текущее действие\n\n"
    "Охранник в списке новых заявок может ввести номер заявки "
    "(например 12 или #12), чтобы принять или отклонить её.\n\n"
    "Роли:\n"
    "• Админ — заявки на визит, заявки охранников, статистика (нужен код)\n"
    "• Охранник — после кода и одобрения админом подтверждает пропуск\n"
    "• Пользователь — оформляет визит: имя гостя, квартира и цель"
)


async def _upsert_user(update: Any) -> User:
    user_id = sender_user_id(update)
    if user_id is None:
        raise ValueError("В апдейте нет user_id")

    full_name = sender_name(update)
    username = sender_username(update)

    async with async_session_maker() as session:
        user = await session.get(User, user_id)
        if user is None:
            user = User(
                id=user_id,
                username=username,
                full_name=full_name or "Пользователь",
                role=Role.RESIDENT,
                is_active=True,
            )
            session.add(user)
            logger.info("Создан пользователь id={} role={}", user_id, user.role.value)
        else:
            if username and user.username != username:
                user.username = username
            if full_name and user.full_name != full_name:
                user.full_name = full_name
        await session.commit()
        await session.refresh(user)
        return user


async def _set_role(user_id: int, role: Role) -> User:
    async with async_session_maker() as session:
        user = await session.get(User, user_id)
        if user is None:
            user = User(
                id=user_id,
                full_name="Пользователь",
                role=role,
                is_active=True,
                guard_approved=role == Role.GUARD,
            )
            session.add(user)
        else:
            user.role = role
            user.is_active = True
            if role == Role.GUARD:
                user.guard_approved = True
        await session.commit()
        await session.refresh(user)
        return user


async def _send_role_menu(bot: BotClient, update: Any, user: User) -> None:
    name = user.full_name or "коллега"
    await bot.reply(
        update,
        (
            f"Здравствуйте, {name}!\n\n"
            "Кем вы хотите войти?"
        ),
        attachments=[role_choice_menu()],
    )


async def _enter_as(bot: BotClient, update: Any, user: User) -> None:
    title = ROLE_TITLES[user.role]
    await bot.reply(
        update,
        f"Вы вошли как {title}. Выберите действие:",
        attachments=[menu_for_role(user.role)],
    )


async def _pending_guard_request(user_id: int) -> GuardAccessRequest | None:
    async with async_session_maker() as session:
        return await session.scalar(
            select(GuardAccessRequest).where(
                GuardAccessRequest.user_id == user_id,
                GuardAccessRequest.status == GuardAccessStatus.PENDING,
            )
        )


async def _create_guard_application(user_id: int) -> GuardAccessRequest:
    async with async_session_maker() as session:
        request = GuardAccessRequest(
            user_id=user_id,
            status=GuardAccessStatus.PENDING,
        )
        session.add(request)
        await session.flush()
        await session.refresh(request)
        await notify_admins(session, request)
        await session.commit()
        await session.refresh(request)
        return request


@router.command("start")
async def cmd_start(bot: BotClient, update: Any) -> None:
    logger.info("Получена команда /start из MAX")
    fsm.clear(sender_user_id(update))
    user = await _upsert_user(update)
    await _send_role_menu(bot, update, user)


@router.event("bot_started")
async def on_bot_started(bot: BotClient, update: Any) -> None:
    logger.info("Получено событие bot_started из MAX")
    fsm.clear(sender_user_id(update))
    user = await _upsert_user(update)
    await _send_role_menu(bot, update, user)


@router.callback(CHOOSE_USER)
async def choose_user(bot: BotClient, update: Any) -> None:
    user_id = sender_user_id(update)
    if user_id is None:
        await bot.reply(update, "Не удалось определить пользователя.")
        return
    fsm.clear(user_id)
    user = await _set_role(user_id, Role.RESIDENT)
    await _enter_as(bot, update, user)


@router.callback(CHOOSE_GUARD)
async def choose_guard(bot: BotClient, update: Any) -> None:
    user_id = sender_user_id(update)
    if user_id is None:
        await bot.reply(update, "Не удалось определить пользователя.")
        return
    fsm.set_state(user_id, AdminForm.WAITING_GUARD_CODE)
    await bot.reply(
        update,
        "Введите код доступа охранника.",
        attachments=[back_menu()],
    )


@router.callback(CHOOSE_ADMIN)
async def choose_admin(bot: BotClient, update: Any) -> None:
    user_id = sender_user_id(update)
    if user_id is None:
        await bot.reply(update, "Не удалось определить пользователя.")
        return
    fsm.set_state(user_id, AdminForm.WAITING_ADMIN_CODE)
    await bot.reply(
        update,
        "Введите код доступа админа.",
        attachments=[back_menu()],
    )


@router.state(AdminForm.WAITING_ADMIN_CODE)
async def on_admin_code(bot: BotClient, update: Any) -> None:
    user_id = sender_user_id(update)
    if user_id is None:
        return
    if parse_command(message_text(update)):
        await bot.reply(update, "Введите код или /cancel для отмены.", attachments=[back_menu()])
        return

    code = message_text(update)
    if code != settings.admin_access_code:
        await bot.reply(
            update,
            "Неверный код. Попробуйте ещё раз или /cancel.",
            attachments=[back_menu()],
        )
        return

    fsm.clear(user_id)
    user = await _set_role(user_id, Role.ADMIN)
    if settings.admin_max_user_id is None:
        persist_admin_max_user_id(user.id)
    logger.info("Пользователь id={} вошёл как админ по коду", user_id)
    await _enter_as(bot, update, user)


@router.state(AdminForm.WAITING_GUARD_CODE)
async def on_guard_code(bot: BotClient, update: Any) -> None:
    user_id = sender_user_id(update)
    if user_id is None:
        return
    if parse_command(message_text(update)):
        await bot.reply(update, "Введите код или /cancel для отмены.", attachments=[back_menu()])
        return

    code = message_text(update)
    if code != settings.guard_access_code:
        await bot.reply(
            update,
            "Неверный код. Попробуйте ещё раз или /cancel.",
            attachments=[back_menu()],
        )
        return

    fsm.clear(user_id)
    user = await get_user(user_id)
    if user is None:
        user = await _upsert_user(update)

    if user.role == Role.ADMIN and user.is_active:
        await bot.reply(
            update,
            "Админ не может подать заявку на роль охранника.",
            attachments=[menu_for_role(Role.ADMIN)],
        )
        return

    if user.guard_approved:
        user = await _set_role(user.id, Role.GUARD)
        await _enter_as(bot, update, user)
        return

    pending = await _pending_guard_request(user.id)
    if pending is not None:
        await bot.reply(
            update,
            "Заявка уже отправлена админу. Ожидайте решения.",
            attachments=[back_menu()],
        )
        return

    await _create_guard_application(user.id)
    logger.info("Пользователь id={} подал заявку на роль охранника", user_id)
    await bot.reply(
        update,
        "Заявка отправлена админу. Ожидайте решения.",
        attachments=[back_menu()],
    )


@router.callback(CHANGE_ROLE)
async def change_role(bot: BotClient, update: Any) -> None:
    user_id = sender_user_id(update)
    fsm.clear(user_id)
    user = await get_user(user_id)
    if user is None:
        user = await _upsert_user(update)
    await _send_role_menu(bot, update, user)


@router.callback(BACK)
async def go_back(bot: BotClient, update: Any) -> None:
    user_id = sender_user_id(update)
    if user_id is None:
        await bot.reply(update, "Не удалось определить пользователя.")
        return
    state = fsm.get_state(user_id)
    if state in {AdminForm.WAITING_ADMIN_CODE, AdminForm.WAITING_GUARD_CODE}:
        fsm.clear(user_id)
        user = await get_user(user_id)
        if user is None:
            user = await _upsert_user(update)
        await _send_role_menu(bot, update, user)
        return
    fsm.clear(user_id)
    user = await get_user(user_id)
    if user is None:
        user = await _upsert_user(update)
        await _send_role_menu(bot, update, user)
        return
    await _enter_as(bot, update, user)


@router.command("help")
async def cmd_help(bot: BotClient, update: Any) -> None:
    await bot.reply(update, HELP_TEXT)


@router.command("cancel")
async def cmd_cancel(bot: BotClient, update: Any) -> None:
    user_id = sender_user_id(update)
    fsm.clear(user_id)
    user = await get_user(user_id)
    attachments = [menu_for_role(user.role)] if user else None
    await bot.reply(update, "Действие отменено.", attachments=attachments)


@router.command("myrole")
async def cmd_myrole(bot: BotClient, update: Any) -> None:
    user_id = sender_user_id(update)
    if user_id is None:
        await bot.reply(update, "Не удалось определить пользователя.")
        return

    async with async_session_maker() as session:
        user = await session.get(User, user_id)

    if user is None:
        await bot.reply(
            update,
            "Вы ещё не зарегистрированы. Нажмите /start.",
        )
        return

    title = ROLE_TITLES[user.role]
    await bot.reply(update, f"Ваша роль: {title} ({user.role.value}).")
