"""Точка входа: запуск MAX-бота."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# python app/main.py не кладёт корень репозитория в PYTHONPATH.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from loguru import logger

from app.bot import Dispatcher, MaxBotClient
from app.bot.commands import BOT_COMMANDS
from app.config import settings
from app.db.init_db import init_models, seed_admin
from app.handlers.admin import router as admin_router
from app.handlers.common import router as common_router
from app.handlers.guard import router as guard_router
from app.handlers.resident import router as resident_router


def _setup_logging() -> None:
    logger.remove()
    logger.add(sys.stderr, level=settings.log_level)


def _build_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(common_router)
    dp.include_router(admin_router)
    dp.include_router(guard_router)
    dp.include_router(resident_router)
    return dp


def _require_development_long_polling() -> None:
    if settings.environment.lower() != "development":
        raise SystemExit("MAX Long Polling разрешён только при ENVIRONMENT=development")
    if settings.max_update_mode != "long_polling":
        raise SystemExit(
            "Процесс polling-бота выключен: задайте MAX_UPDATE_MODE=long_polling. "
            "В режиме webhook обновления обрабатывает FastAPI."
        )


async def main() -> None:
    _setup_logging()
    logger.info("Старт house-access-bot")
    _require_development_long_polling()

    if not settings.max_bot_token:
        raise SystemExit("Для запуска MAX Long Polling задайте MAX_BOT_TOKEN")

    bot = MaxBotClient(token=settings.max_bot_token)
    dp = _build_dispatcher()

    await bot.start()
    try:
        await bot.ensure_no_webhook_subscription()
        await init_models()
        await seed_admin()
        await bot.set_commands(BOT_COMMANDS)
        logger.info("Команды бота зарегистрированы")
    except Exception:
        logger.exception("Не удалось зарегистрировать команды бота")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.close()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    asyncio.run(main())
