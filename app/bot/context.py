"""Текущий экземпляр бота в рамках обработки апдейта."""

from contextvars import ContextVar
from typing import Any

current_bot: ContextVar[Any] = ContextVar("current_bot", default=None)
