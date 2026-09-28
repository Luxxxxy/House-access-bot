"""Обвязка MAX-бота: клиент и диспетчер."""

from app.bot.client import BotClient, MaxBotClient
from app.bot.dispatcher import Dispatcher, Router

__all__ = ["BotClient", "Dispatcher", "MaxBotClient", "Router"]
