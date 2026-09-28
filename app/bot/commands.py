"""Команды бота для выпадающего списка по «/»."""

from __future__ import annotations

BOT_COMMANDS: list[tuple[str, str]] = [
    ("start", "Начать работу и выбрать роль"),
    ("help", "Справка по боту"),
    ("myrole", "Показать текущую роль"),
    ("cancel", "Отменить текущее действие"),
]
