"""Клавиатуры меню для админа, охранника и жильца."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.db.models import Role

RESIDENT_VISIT = "resident:visit"
RESIDENT_MY_REQUESTS = "resident:my_requests"
RESIDENT_CONFIRM = "resident:confirm"
RESIDENT_CANCEL = "resident:cancel"
GUARD_PENDING = "guard:pending"
GUARD_HISTORY = "guard:history"
VISIT_APPROVE_PREFIX = "visit_approve:"
VISIT_REJECT_PREFIX = "visit_reject:"
VISIT_REJECT_SKIP_PREFIX = "visit_skip_reject:"
ADMIN_GUARDS = "admin:guards"
ADMIN_REMOVE_GUARD = "admin:remove_guard"
ADMIN_STATS = "admin:stats"
ADMIN_DEACTIVATE_PREFIX = "admin:deactivate:"
CHOOSE_USER = "role:user"
CHOOSE_GUARD = "role:guard"
CHOOSE_ADMIN = "role:admin"
BACK = "nav:back"
CHANGE_ROLE = "nav:change_role"
GUARD_APPLY_APPROVE_PREFIX = "guard_apply_approve:"
GUARD_APPLY_REJECT_PREFIX = "guard_apply_reject:"


@dataclass
class CallbackButton:
    text: str
    payload: str
    type: str = "callback"


@dataclass
class InlineKeyboard:
    buttons: list[list[CallbackButton]]


@dataclass
class InlineKeyboardAttachment:
    payload: InlineKeyboard
    type: str = "inline_keyboard"


def _menu(rows: list[list[tuple[str, str]]]) -> InlineKeyboardAttachment:
    buttons: list[list[Any]] = [
        [CallbackButton(text=text, payload=payload) for text, payload in row]
        for row in rows
    ]
    return InlineKeyboardAttachment(payload=InlineKeyboard(buttons=buttons))


def _nav_rows(*, back: bool = False, change_role: bool = False) -> list[list[tuple[str, str]]]:
    if back and change_role:
        return [[("⬅️ Назад", BACK), ("🔄 Сменить роль", CHANGE_ROLE)]]
    if back:
        return [[("⬅️ Назад", BACK)]]
    if change_role:
        return [[("🔄 Сменить роль", CHANGE_ROLE)]]
    return []


def role_choice_menu(*, show_back: bool = True) -> InlineKeyboardAttachment:
    rows = [
        [("👤 Пользователь", CHOOSE_USER)],
        [("🛡 Охранник", CHOOSE_GUARD)],
        [("👑 Админ", CHOOSE_ADMIN)],
    ]
    if show_back:
        rows.extend(_nav_rows(back=True))
    return _menu(rows)


def back_menu() -> InlineKeyboardAttachment:
    return _menu(_nav_rows(back=True))


def guard_access_menu(request_id: int) -> InlineKeyboardAttachment:
    return _menu(
        [
            [
                ("✅ Дать доступ", f"{GUARD_APPLY_APPROVE_PREFIX}{request_id}"),
                ("❌ Отклонить", f"{GUARD_APPLY_REJECT_PREFIX}{request_id}"),
            ]
        ]
    )


def visit_decision_menu(visit_id: int) -> InlineKeyboardAttachment:
    return _menu(
        [
            [
                ("✅ Пропустить", f"{VISIT_APPROVE_PREFIX}{visit_id}"),
                ("❌ Отклонить", f"{VISIT_REJECT_PREFIX}{visit_id}"),
            ]
        ]
    )


def reject_skip_menu(visit_id: int) -> InlineKeyboardAttachment:
    return _menu(
        [
            [("Без комментария", f"{VISIT_REJECT_SKIP_PREFIX}{visit_id}")],
            *_nav_rows(back=True),
        ]
    )


def visit_confirm_menu() -> InlineKeyboardAttachment:
    return _menu(
        [
            [
                ("✅ Отправить", RESIDENT_CONFIRM),
                ("❌ Отмена", RESIDENT_CANCEL),
            ]
        ]
    )


def resident_menu() -> InlineKeyboardAttachment:
    return _menu(
        [
            [("📩 Оформить визит", RESIDENT_VISIT)],
            [("📜 Мои заявки", RESIDENT_MY_REQUESTS)],
            *_nav_rows(back=True, change_role=True),
        ]
    )


def guard_menu() -> InlineKeyboardAttachment:
    return _menu(
        [
            [("📥 Новые заявки", GUARD_PENDING)],
            [("✅ История", GUARD_HISTORY)],
            *_nav_rows(back=True, change_role=True),
        ]
    )


def deactivate_guards_menu(guards: list[tuple[int, str]]) -> InlineKeyboardAttachment:
    rows = [[(f"➖ {label}", f"{ADMIN_DEACTIVATE_PREFIX}{user_id}")] for user_id, label in guards]
    rows = rows[:30]
    rows.extend(_nav_rows(back=True))
    return _menu(rows)


def admin_menu() -> InlineKeyboardAttachment:
    return _menu(
        [
            [("📩 Оформить визит", RESIDENT_VISIT)],
            [("📜 Мои заявки", RESIDENT_MY_REQUESTS)],
            [("👮 Охранники", ADMIN_GUARDS)],
            [("➖ Снять охранника", ADMIN_REMOVE_GUARD)],
            [("📊 Статистика", ADMIN_STATS)],
            *_nav_rows(back=True, change_role=True),
        ]
    )


def menu_for_role(role: Role) -> InlineKeyboardAttachment:
    if role == Role.ADMIN:
        return admin_menu()
    if role == Role.GUARD:
        return guard_menu()
    return resident_menu()
